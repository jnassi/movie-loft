#!/usr/bin/env python3
"""Tune in queue test: the phone → server → Mac helper handshake.

    .venv/bin/python tests/tune_test.py

Drives the real FastAPI app in-process (no network, no Apple TV) with the
in-memory store — the same state machine the Postgres table runs:
pending → claimed → working → done | failed, unconfirmed claims requeued after
ACK_SECONDS, unclaimed requests expired after STALE_SECONDS. The SQL versions
of those two rules aren't exercised here (no Postgres needed to run it).
"""
import asyncio, os, sys, time
from pathlib import Path

# A throwaway movieloft.toml with one room, so the test doesn't depend on (or
# need) the instance's own config.
import tempfile
_cfg = Path(tempfile.mkdtemp()) / "movieloft.toml"
_cfg.write_text('[[rooms]]\nkey = "living"\nlabel = "Living Room"\napple_tv = "Test TV"\n')
os.environ.update(DEV_NO_AUTH="1", AGENT_TOKEN="test-token", MOVIELOFT_CONFIG=str(_cfg))
for k in ("DATABASE_URL", "RAILWAY_ENVIRONMENT"):
    os.environ.pop(k, None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from app import main, store

AGENT = {"X-Agent-Token": "test-token"}
LINK = "https://tv.apple.com/us/movie/frozen/umc.cmc.xxxxx"
fails = []


def check(cond, what):
    if not cond:
        fails.append(what)


def back(tid, field, secs):
    """Pretend `field` happened `secs` seconds earlier (no real waiting)."""
    t = store._tunes[tid]
    if field == "requested_at":
        t["requested_at"] = t["requested_at"].fromtimestamp(t["requested_at"].timestamp() - secs,
                                                            t["requested_at"].tzinfo)
    else:
        t[field] -= secs


async def main_():
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        tune = lambda **kw: c.post("/api/tune", json={"room": "living", "link": LINK, "title": "Frozen",
                                                      "position": 600, **kw})
        status = lambda tid: c.get(f"/api/tune/{tid}")

        # Bad input and bad tokens are refused.
        check((await tune(room="garage")).status_code == 400, "unknown room accepted")
        check((await tune(link="https://evil.example/")).status_code == 400, "non-Apple link accepted")
        check((await c.get("/agent/next")).status_code == 401, "agent/next without a token")
        check((await c.get("/agent/next", headers={"X-Agent-Token": "nope"})).status_code == 401,
              "agent/next with a wrong token")

        # The happy path.
        main._agent_seen = 0
        r = (await tune()).json()
        check(r["status"] == "pending" and r["agentOnline"] is False, f"new request: {r}")
        job = (await c.get("/agent/next", headers=AGENT)).json()
        check(job["id"] == r["id"] and job["position"] == 600 and job["link"] == LINK, f"claimed: {job}")
        check((await status(job["id"])).json()["status"] == "claimed", "status after claim")
        check((await c.post("/agent/ack", headers=AGENT, json={"id": job["id"]})).json() == {"ok": True},
              "ack refused")
        check((await status(job["id"])).json()["status"] == "working", "status after ack")
        await c.post("/agent/result", headers=AGENT,
                     json={"id": job["id"], "status": "done", "message": "paused at 10:03 — press play"})
        s = (await status(job["id"])).json()
        check(s["status"] == "done" and s["message"].startswith("paused at"), f"after result: {s}")
        check((await tune()).json()["agentOnline"] is True, "helper not shown online after polling")
        # (drain that one)
        j = (await c.get("/agent/next", headers=AGENT)).json()
        await c.post("/agent/ack", headers=AGENT, json={"id": j["id"]})
        check((await c.post("/agent/result", headers=AGENT, json={"id": j["id"], "status": "bogus"})).status_code
              == 400, "bogus result status accepted")
        await c.post("/agent/result", headers=AGENT, json={"id": j["id"], "status": "failed", "message": "x"})
        check((await status(j["id"])).json()["status"] == "failed", "failed result not recorded")

        # A claim that's never confirmed (dead long poll) goes back in the queue.
        r = (await tune()).json()
        lost = (await c.get("/agent/next", headers=AGENT)).json()
        back(lost["id"], "claimed_at", store.ACK_SECONDS + 1)
        again = await c.get("/agent/next", headers=AGENT, timeout=30)
        again = again.json() if again.status_code == 200 else {"id": None}
        check(again["id"] == r["id"], "unconfirmed claim wasn't requeued")
        await c.post("/agent/ack", headers=AGENT, json={"id": again["id"]})
        await c.post("/agent/result", headers=AGENT, json={"id": again["id"], "status": "done"})

        # An ack that arrives after the claim lapsed back to pending is refused.
        r = (await tune()).json()
        (await c.get("/agent/next", headers=AGENT))
        store._tunes[r["id"]]["status"] = "pending"          # what a lapse leaves behind
        check((await c.post("/agent/ack", headers=AGENT, json={"id": r["id"]})).json() == {"ok": False},
              "late ack accepted")
        store._tunes[r["id"]]["status"] = "done"

        # Nobody picks it up for a minute (Mac off): it expires instead of
        # tuning the TV whenever the Mac comes back.
        r = (await tune()).json()
        back(r["id"], "requested_at", store.STALE_SECONDS + 1)
        check(await store.claim_tune() is None, "stale request was handed out")
        check((await status(r["id"])).json()["status"] == "expired", "stale request not expired")

        # Requests go out oldest first.
        a, b = (await tune(title="A")).json(), (await tune(title="B")).json()
        got = [(await c.get("/agent/next", headers=AGENT)).json()["id"] for _ in range(2)]
        check(got == [a["id"], b["id"]], f"order {got}")
        for tid in got:
            await c.post("/agent/ack", headers=AGENT, json={"id": tid})
            await c.post("/agent/result", headers=AGENT, json={"id": tid, "status": "done"})

        # A waiting long poll answers as soon as a request arrives.
        t0 = time.time()
        poll = asyncio.create_task(c.get("/agent/next", headers=AGENT, timeout=30))
        await asyncio.sleep(0.5)
        r = (await tune()).json()
        job = (await poll).json()
        check(job["id"] == r["id"] and time.time() - t0 < 3, f"long poll took {time.time() - t0:.1f}s")

        # "From the beginning" travels through to the helper.
        r = (await tune(position=0, fromStart=True)).json()
        job = (await c.get("/agent/next", headers=AGENT)).json()
        check(job["id"] == r["id"] and job["from_start"] is True and job["position"] == 0, f"fromStart: {job}")
        await c.post("/agent/ack", headers=AGENT, json={"id": job["id"]})
        await c.post("/agent/result", headers=AGENT, json={"id": job["id"], "status": "done"})
        check((await tune()).json()["from_start"] is False, "join-in-progress is the default")

        check((await status(999999)).status_code == 404, "unknown id")


asyncio.run(main_())
if fails:
    print(f"tune: {len(fails)} problem(s)")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("tune: ok — queue, ack/requeue, expiry, ordering, long-poll wake, from-start")
