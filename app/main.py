"""Movie Loft web server (Railway).

Serves the pages `make` builds (index.html, tv.html, art/, art-tv/) behind a
Google sign-in limited to ALLOWED_EMAILS, plus a small JSON API for the one
thing the static pages can't do on their own: remember tags (Comfort, for now)
in Postgres.

The catalog itself is NOT in the database. It stays as files in git, rebuilt
from the Apple TV app export by `make`; a push redeploys. The database holds
only the owner's own data about the catalog.

Environment:
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET   OAuth client (Google Cloud console)
  ALLOWED_EMAILS                            comma-separated; anyone else is refused
  SESSION_SECRET                            signs the session cookie
  DATABASE_URL                              Postgres (Railway provides it)
  PUBLIC_URL                                e.g. https://movieloft.example.com
  AGENT_TOKEN                               shared secret for the Tune in helper on the Mac
  DEV_NO_AUTH=1                             local only: skip sign-in. Refused when deployed.
"""
import asyncio, os, secrets, time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from . import instance, store

ROOT = Path(__file__).resolve().parent.parent
DEV_NO_AUTH = os.environ.get("DEV_NO_AUTH") == "1"

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
ALLOWED = {e.strip().lower() for e in os.environ.get("ALLOWED_EMAILS", "").split(",") if e.strip()}
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8000").rstrip("/")
# Deployed = reachable from the internet, on any host: an https PUBLIC_URL, or
# Railway (which sets RAILWAY_ENVIRONMENT). Deployed means a real session
# secret, Secure cookies, and no DEV_NO_AUTH.
DEPLOYED = PUBLIC_URL.startswith("https://") or bool(os.environ.get("RAILWAY_ENVIRONMENT"))
if DEV_NO_AUTH and DEPLOYED:
    raise RuntimeError("DEV_NO_AUTH is for local development only — refusing to start when deployed "
                       "(PUBLIC_URL is https, or this is Railway)")
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET") or (
    None if DEPLOYED else "dev-only-not-secret")
if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET must be set when deployed")

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


# ------------------------------------------------------------------ auth gate
# Icons and the manifest are open: browsers fetch them without the session
# cookie (iOS for the home-screen icon, Chrome for the manifest). Nothing in
# them is private.
OPEN_PATHS = {"/health", "/login", "/auth/callback", "/signed-out", "/favicon.ico",
              "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png",
              "/manifest.webmanifest"}


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    # /agent/ is the Mac's Tune in helper: it has no Google session, it has the token
    # (checked in agent_auth below), so the sign-in gate lets it through.
    if (DEV_NO_AUTH or path in OPEN_PATHS or path.startswith("/icons/") or path.startswith("/agent/")
            or request.session.get("email")):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"error": "not signed in"}, status_code=401)
    if path in PAGES:
        # Remember only real pages as the post-login destination. Browsers fire
        # background requests (/favicon.ico, artwork) while signed out; saving
        # those sent the first sign-in to /favicon.ico.
        request.session["next"] = path
    return RedirectResponse("/login")

# Added after the gate so it wraps it: the gate needs request.session.
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, session_cookie="movieloft",
                   max_age=60 * 60 * 24 * 90, same_site="lax", https_only=DEPLOYED)
# Outermost: compress what goes out. The guide carries every episode's Apple TV
# ID (~500 KB raw, ~250 KB gzipped), and Railway's edge doesn't compress.
app.add_middleware(GZipMiddleware, minimum_size=1000)


FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
           '<rect width="64" height="64" rx="12" fill="#171A24"/>'
           '<text x="32" y="44" font-family="Futura,Avenir,sans-serif" font-size="30" '
           'font-weight="600" fill="#E0A340" text-anchor="middle">ML</text></svg>')


@app.get("/favicon.ico")
async def favicon():
    return Response(FAVICON, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=604800"})


MANIFEST = {
    "name": "Movie Loft", "short_name": "Movie Loft", "start_url": "/guide.html",
    "display": "standalone", "background_color": "#171A24", "theme_color": "#171A24",
    "icons": [{"src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
              {"src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png"}],
}


@app.get("/apple-touch-icon.png")
@app.get("/apple-touch-icon-precomposed.png")
async def touch_icon():
    return FileResponse(ROOT / "icons" / "icon-180.png", media_type="image/png",
                        headers={"Cache-Control": "public, max-age=604800"})


@app.get("/manifest.webmanifest")
async def manifest():
    return JSONResponse(MANIFEST, media_type="application/manifest+json")


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/login")
async def login(request: Request):
    if not CLIENT_ID:
        raise HTTPException(500, "GOOGLE_CLIENT_ID is not set")
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    return RedirectResponse(GOOGLE_AUTH + "?" + urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": PUBLIC_URL + "/auth/callback",
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "prompt": "select_account",
    }))


@app.get("/auth/callback")
async def callback(request: Request, code: str = "", state: str = ""):
    expected = request.session.pop("oauth_state", None)
    if not code or not expected or not secrets.compare_digest(state, expected):
        raise HTTPException(400, "Sign-in expired or was tampered with. Go back and try again.")
    async with httpx.AsyncClient(timeout=10) as client:
        tok = await client.post(GOOGLE_TOKEN, data={
            "code": code, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
            "redirect_uri": PUBLIC_URL + "/auth/callback", "grant_type": "authorization_code",
        })
        if tok.status_code != 200:
            raise HTTPException(400, "Google didn't accept the sign-in. Try again.")
        info = await client.get(GOOGLE_USERINFO, headers={
            "Authorization": "Bearer " + tok.json()["access_token"]})
    user = info.json() if info.status_code == 200 else {}
    email = (user.get("email") or "").lower()
    if not email or not user.get("email_verified") or email not in ALLOWED:
        request.session.clear()
        return JSONResponse({"error": f"{email or 'That account'} isn't on the Movie Loft list."},
                            status_code=403)
    request.session["email"] = email
    return RedirectResponse(request.session.pop("next", "/") or "/")


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/signed-out")


@app.get("/signed-out")
async def signed_out():
    return JSONResponse({"signedOut": True, "signIn": "/login"})


# ------------------------------------------------------------------- tags API
class TagChange(BaseModel):
    kind: str        # "movie" (key = raw title) or "show" (key = show name)
    key: str
    tag: str         # "comfort" for now
    on: bool


KINDS, TAGS = {"movie", "show"}, {"comfort"}


@app.get("/api/tags")
async def get_tags():
    return await store.all_tags()


@app.put("/api/tags")
async def put_tag(change: TagChange, request: Request):
    if change.kind not in KINDS or change.tag not in TAGS or not change.key or len(change.key) > 500:
        raise HTTPException(400, "unknown kind or tag")
    await store.set_tag(change.kind, change.key, change.tag, change.on,
                        request.session.get("email", "dev"))
    return await store.all_tags()


@app.get("/api/me")
async def me(request: Request):
    return {"email": request.session.get("email") or ("dev" if DEV_NO_AUTH else None)}


# ------------------------------------------------------------------ tune-in
# The phone queues; the helper on the Mac long-polls /agent/next, drives the
# Apple TV, and posts /agent/result; the phone polls /api/tune/{id} for status.
ROOMS = {r["key"] for r in instance.load()["rooms"]}   # from movieloft.toml
_wake = asyncio.Event()          # set when a request arrives, so a waiting agent returns at once
_agent_seen = 0.0                # last time the helper checked in


class TuneRequest(BaseModel):
    room: str                    # a [[rooms]] key from movieloft.toml
    link: str                    # https://tv.apple.com/... (movie or show page)
    title: str                   # what the TV should report playing (movies)
    position: int | None = None  # seconds into the title at the moment of the tap
    fromStart: bool = False      # start at `position` exactly, not where the broadcast is by now


@app.post("/api/tune")
async def tune(req: TuneRequest, request: Request):
    if req.room not in ROOMS or not req.link.startswith("https://tv.apple.com/"):
        raise HTTPException(400, "unknown room or link")
    row = await store.add_tune(req.room, req.link, req.title[:300], req.position,
                               request.session.get("email", "dev"), req.fromStart)
    _wake.set()
    return {**row, "agentOnline": time.time() - _agent_seen < 90}


@app.get("/api/tune/{tid}")
async def tune_status(tid: int):
    row = await store.get_tune(tid)
    if not row:
        raise HTTPException(404)
    return row


def agent_auth(request: Request):
    got = request.headers.get("x-agent-token", "")
    if not AGENT_TOKEN or not secrets.compare_digest(got, AGENT_TOKEN):
        raise HTTPException(401, "bad agent token")


@app.get("/agent/next")
async def agent_next(request: Request):
    """Long poll: returns the next request, or 204 after ~25s with none."""
    global _agent_seen
    agent_auth(request)
    deadline = time.time() + 25
    while True:
        _agent_seen = time.time()
        # A long poll can outlive its caller (helper restarted, network blip),
        # and the "http" middleware hides disconnects from this handler. So a
        # claim isn't final until the helper confirms it via /agent/ack; an
        # unconfirmed claim goes back in the queue after a few seconds.
        row = await store.claim_tune()
        if row:
            return row
        remaining = deadline - time.time()
        if remaining <= 0:
            return Response(status_code=204)
        _wake.clear()
        try:
            await asyncio.wait_for(_wake.wait(), timeout=min(remaining, 5))
        except asyncio.TimeoutError:
            pass


class TuneAck(BaseModel):
    id: int


@app.post("/agent/ack")
async def agent_ack(ack: TuneAck, request: Request):
    agent_auth(request)
    return {"ok": await store.ack_tune(ack.id)}


class TuneResult(BaseModel):
    id: int
    status: str                  # "done" | "failed"
    message: str | None = None


@app.post("/agent/result")
async def agent_result(res: TuneResult, request: Request):
    agent_auth(request)
    if res.status not in {"done", "failed"}:
        raise HTTPException(400, "status must be done or failed")
    await store.finish_tune(res.id, res.status, (res.message or "")[:500])
    return {"ok": True}


# --------------------------------------------------------------- the pages
# Only the built site is served — never source files, the .git folder, or the
# TSVs. (This is the job .assetsignore did on Cloudflare.)
PAGES = {"/": "index.html", "/index.html": "index.html", "/tv.html": "tv.html",
         "/guide.html": "guide.html"}
ART_DIRS = {"art", "art-tv", "icons"}


@app.get("/{path:path}")
async def site(path: str):
    rel = PAGES.get("/" + path)
    if rel:
        return FileResponse(ROOT / rel, headers={"Cache-Control": "no-cache"})
    top, _, rest = path.partition("/")
    if top in ART_DIRS and rest:
        f = (ROOT / top / rest).resolve()
        if f.is_file() and f.parent == (ROOT / top).resolve():
            return FileResponse(f, headers={"Cache-Control": "public, max-age=86400"})
    raise HTTPException(404)


@app.on_event("startup")
async def startup():
    await store.connect()


@app.on_event("shutdown")
async def shutdown():
    await store.close()
