#!/usr/bin/env python3
"""Pull in shows you stream but don't own (Apple TV+), from TMDB.

    python3 fetch_streaming.py

The Apple TV app export only sees library items; Apple TV+ shows aren't
library items. So the list is chosen by hand in corrections.toml:

  [streaming]
  service = "Apple TV+"
  shows = ["Ted Lasso", "Shrinking"]
  # optional pins when TMDB's search picks the wrong show:
  # [streaming.tmdb]
  # "Shrinking" = 136311

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


def main():
    spec = tomllib.loads((ROOT / "corrections.toml").read_text(encoding="utf-8") if (ROOT / "corrections.toml").exists() else "").get("streaming", {})
    shows, service, pins = spec.get("shows", []), spec.get("service", "Apple TV+"), spec.get("tmdb", {})
    if not shows:
        print("No [streaming] shows in corrections.toml")
        return
    key = lookup_years.api_key(required=True, root=ROOT)
    today = date.today().isoformat()
    out = {}
    for show in shows:
        tid = pins.get(show)
        if not tid:
            res = get("/search/tv", key, query=show).get("results", [])
            exact = [r for r in res if norm(r.get("name", "")) == norm(show)]
            if not exact:
                print(f"  ? {show}: not found on TMDB — pin it under [streaming.tmdb]")
                continue
            # Same-named shows are common ("The Studio"); prefer the one on the
            # service's own network.
            info = None
            for r in exact[:6]:
                cand = get(f"/tv/{r['id']}", key)
                if any(service.split("+")[0].strip().lower() in (n.get("name") or "").lower()
                       for n in cand.get("networks", [])):
                    info = cand
                    break
            if info is None:
                print(f"  ? {show}: no {service} match among same-named shows; using TMDB's top hit")
                info = get(f"/tv/{exact[0]['id']}", key)
            tid = info["id"]
        else:
            info = get(f"/tv/{tid}", key)
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
        out[show] = {"tmdb": tid, "service": service, "first": int((info.get("first_air_date") or "0")[:4] or 0),
                     "eps": eps}
        nets = ", ".join(n.get("name", "") for n in info.get("networks", []))
        print(f"  + {show} ({service}): {len(eps)} episodes, {len({e[0] for e in eps})} seasons "
              f"· TMDB {tid} · {info.get('first_air_date', '')[:4]} · {nets}")
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
