#!/usr/bin/env python3
"""Pull in shows you stream but don't own, from TMDB.

    python3 fetch_streaming.py

The Apple TV app export only sees library items; streamed shows aren't
library items. So the list is chosen by hand in corrections.toml:

  [streaming]
  services = ["HBO Max", "Hulu", "Disney+"]   # yours, in order of preference
  shows = ["The Pitt", "The Bear", "Andor", "Ted Lasso"]
  # optional pins when TMDB's search picks the wrong show:
  # [streaming.tmdb]
  # "Shrinking" = 136311
  # optional: which service, when the guess is wrong:
  # [streaming.on]
  # "The Bear" = "Hulu"

(An older form, `service = "Apple TV+"` with no `services`, still works.)
Service names are the ones in app/services.py, which lists what Tune in can
play; "Max", "Disney Plus" and so on are understood too.

Each show is matched to the first of your services that TMDB's watch-provider
data (from JustWatch, US) says carries it. A show on none of them is skipped
with a note saying where TMDB does list it. Apple TV+ is assumed when you
haven't listed services at all (that older form).

For each show this fetches every aired episode (season, episode, title,
running time) and the poster, and writes streaming.json, which build_tv.py
merges into the TV catalog — badged with the service, mixed into the guide's
channels like any other show (decided Oct 17, 2026). Specials (season 0) and
episodes that haven't aired yet are skipped. Re-fetches every run, so new
episodes appear on their own. Needs the TMDB key (.tmdb.key).
"""
import json, re, sys, tomllib, urllib.parse, urllib.request
from datetime import date
from pathlib import Path

import lookup_years
from app.services import SERVICES, canonical

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "streaming.json"
ART = ROOT / "art-tv"
IMG = "https://image.tmdb.org/t/p/w780"


def get(path, key, **params):
    q = urllib.parse.urlencode({"api_key": key, **params})
    with urllib.request.urlopen(f"https://api.themoviedb.org/3{path}?{q}", timeout=20) as r:
        return json.load(r)


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def providers(tid, key):
    """TMDB watch-provider IDs and names for a show (US subscription services)."""
    us = get(f"/tv/{tid}/watch/providers", key).get("results", {}).get("US", {})
    flat = us.get("flatrate", []) + us.get("ads", [])
    return {p["provider_id"] for p in flat}, [p["provider_name"] for p in flat]


def pick(ids, mine):
    """The first of my services the provider IDs include."""
    return next((s for s in mine if ids & set(SERVICES[s]["tmdb"])), None)


def your_services(spec):
    """corrections.toml's services, as Movie Loft's names; unknown ones reported."""
    names = spec.get("services") or [spec.get("service", "Apple TV+")]
    mine = []
    for n in names:
        c = canonical(n)
        if c:
            mine.append(c)
        else:
            print(f"  ? [streaming] services: {n!r} isn't one Movie Loft can play "
                  f"({', '.join(SERVICES)})")
    return mine


def main():
    spec = tomllib.loads((ROOT / "corrections.toml").read_text(encoding="utf-8") if (ROOT / "corrections.toml").exists() else "").get("streaming", {})
    shows, pins, forced = spec.get("shows", []), spec.get("tmdb", {}), spec.get("on", {})
    if not shows:
        print("No [streaming] shows in corrections.toml")
        return
    mine = your_services(spec)
    legacy = not spec.get("services")             # the one-service form: trust it
    key = lookup_years.api_key(required=True, root=ROOT)
    today = date.today().isoformat()
    out = {}
    for show in shows:
        tid = pins.get(show)
        if tid:
            info = get(f"/tv/{tid}", key)
            ids, names = providers(tid, key)
        else:
            res = get("/search/tv", key, query=show).get("results", [])
            exact = [r for r in res if norm(r.get("name", "")) == norm(show)]
            if not exact:
                print(f"  ? {show}: not found on TMDB — pin it under [streaming.tmdb]")
                continue
            # Same-named shows are common ("The Studio"); prefer the one on one
            # of your services.
            info = None
            for r in exact[:6]:
                ids, names = providers(r["id"], key)
                if pick(ids, mine) or len(exact) == 1:
                    info = get(f"/tv/{r['id']}", key)
                    break
            if info is None:
                info = get(f"/tv/{exact[0]['id']}", key)
                ids, names = providers(exact[0]["id"], key)
            tid = info["id"]
        if show in forced:
            service = canonical(forced[show])
            if not service:
                print(f"  ? [streaming.on] {show!r}: {forced[show]!r} isn't a service Movie Loft can play")
                continue
        elif legacy and mine:
            service = mine[0]
        else:
            service = pick(ids, mine)
        if not service:
            where = ", ".join(names) or "nowhere TMDB knows of"
            print(f"  ? {show}: not on your services — TMDB lists it on {where}. Skipped "
                  f"(set [streaming.on] if TMDB is wrong).")
            continue
        default = (info.get("episode_run_time") or [30])[0] * 60
        eps = []
        for season in info.get("seasons", []):
            n = season.get("season_number", 0)
            if not n:
                continue                          # specials
            for e in get(f"/tv/{tid}/season/{n}", key).get("episodes", []):
                if not e.get("air_date") or e["air_date"] > today:
                    continue                      # not out yet
                secs = (e.get("runtime") or 0) * 60 or default
                eps.append([n, e["episode_number"], e.get("name") or f"Episode {e['episode_number']}", secs])
        if info.get("poster_path"):
            with urllib.request.urlopen(IMG + info["poster_path"], timeout=20) as r:
                (ART / (show.replace(":", "_").replace("/", "_") + ".jpg")).write_bytes(r.read())
        listed = [s for s in SERVICES if ids & set(SERVICES[s]["tmdb"])]   # every service TMDB lists
        out[show] = {"tmdb": tid, "service": service, "listed": listed,
                     "first": int((info.get("first_air_date") or "0")[:4] or 0), "eps": eps}
        print(f"  + {show} ({service}): {len(eps)} episodes, {len({e[0] for e in eps})} seasons "
              f"· TMDB {tid} · {info.get('first_air_date', '')[:4]}")
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    by = {}
    for rec in out.values():
        by[rec["service"]] = by.get(rec["service"], 0) + 1
    print(f"{len(out)} streamed shows: " + ", ".join(f"{n} on {s}" for s, n in by.items()))


if __name__ == "__main__":
    main()
