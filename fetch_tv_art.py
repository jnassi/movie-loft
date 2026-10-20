#!/usr/bin/env python3
"""Replace TV covers with real show posters from TMDB.

    python3 fetch_tv_art.py           # fetch posters for shows not yet looked up
    python3 fetch_tv_art.py --redo    # look every show up again

The Apple TV app only exposes per-episode artwork, which is a video frame (30
Rock's "cover" was Tina Fey carrying a box of hot dogs). TMDB has proper show
posters. (Apple's own iTunes Search API was tried first and dropped: whole
shows are missing from it — 30 Rock returns nothing.) This writes the poster
over art-tv/<show>.jpg; export-tv.applescript never overwrites an existing
file, so the poster sticks.

Needs the same TMDB key as lookup_years.py (.tmdb.key or $TMDB_API_KEY).

tv-art.json records each show's result, so reruns only look up new shows:
  {"Seinfeld": {"tmdb": 1400, "name": "Seinfeld", "first": "1989"}}   poster saved
  {"Some Show": {"tmdb": null}}                                        no match; frame stays

Picking among same-named shows uses the library's own tags: "(Reboot)" takes
the newest, "(Original)" the oldest, "(2001)" the closest year; otherwise the
most relevant show that premiered by the store year of its earliest episode.

Wrong match, or a combined listing like "Band of Brothers and The Pacific"?
Pin it in corrections.toml by TMDB id (the number in the themoviedb.org URL):
  [tv_art]
  "Band of Brothers and The Pacific" = 4613
  "Some Show" = 0                     # never fetch; keep the frame
"""
import json, re, sys, time, tomllib, unicodedata, urllib.parse, urllib.request
from pathlib import Path

import lookup_years

ROOT = Path(__file__).resolve().parent
EPISODES = ROOT / "episodes.tsv"
CACHE = ROOT / "tv-art.json"
ART = ROOT / "art-tv"
REDO = "--redo" in sys.argv
IMG = "https://image.tmdb.org/t/p/w780"
TAG = re.compile(r"\s*\((Reboot|Original|Remastered|\d{4})\)\s*$")


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"^the\s+", "", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def get(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.load(r)


def year(r):
    return int(r["first_air_date"][:4]) if (r.get("first_air_date") or "")[:4].isdigit() else None


def pick(show, key, store_year):
    m = TAG.search(show)
    tag = m.group(1) if m else ""
    base = TAG.sub("", show).strip()
    res = get("https://api.themoviedb.org/3/search/tv?" + urllib.parse.urlencode(
        {"api_key": key, "query": base, "include_adult": "false"})).get("results", [])
    exact = [r for r in res if r.get("poster_path") and
             norm(base) in (norm(r.get("name", "")), norm(r.get("original_name", "")))]
    if not exact:
        return None
    dated = [r for r in exact if year(r)]
    # Store years run at or after the first air date (a reissue pushes them
    # later, never earlier), so a show that premiered after it can't be ours.
    if store_year:
        dated = [r for r in dated if year(r) <= store_year + 1] or dated
    if tag == "Reboot" and dated:
        return max(dated, key=year)
    if tag == "Original" and dated:
        return min(dated, key=year)
    if tag.isdigit() and dated:
        return min(dated, key=lambda r: abs(year(r) - int(tag)))
    if len(exact) > 1 and dated:
        return dated[0]                   # TMDB's relevance order (US Bachelor over AU)
    return exact[0]


def safe_name(show):
    return show.replace(":", "_").replace("/", "_")


def main():
    key = lookup_years.api_key(required=True, root=ROOT)
    first_year = {}
    for line in EPISODES.read_text(encoding="utf-8").split("\n"):
        p = line.split("\t")
        if len(p) >= 6 and p[5].isdigit() and int(p[5]):
            first_year[p[0]] = min(first_year.get(p[0], 9999), int(p[5]))
        elif p and p[0]:
            first_year.setdefault(p[0], 9999)
    shows = sorted(first_year)
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    pins = tomllib.loads((ROOT / "corrections.toml").read_text(encoding="utf-8") if (ROOT / "corrections.toml").exists() else "").get("tv_art", {})
    todo = [s for s in shows if REDO or s not in cache or (s in pins and cache[s].get("tmdb") != (pins[s] or None))]
    got = miss = 0
    for show in todo:
        try:
            if show in pins:
                if not pins[show]:
                    cache[show] = {"tmdb": None, "pinned": True}
                    continue
                r = get(f"https://api.themoviedb.org/3/tv/{int(pins[show])}?api_key={key}")
            else:
                sy = first_year[show] if first_year[show] != 9999 else None
                r = pick(show, key, sy)
        except Exception as e:                      # network hiccup: leave it for next run
            print(f"  ! {show}: {e}")
            continue
        if r and r.get("poster_path"):
            with urllib.request.urlopen(IMG + r["poster_path"], timeout=20) as img:
                (ART / f"{safe_name(show)}.jpg").write_bytes(img.read())
            cache[show] = {"tmdb": r["id"], "name": r.get("name"), "first": (r.get("first_air_date") or "")[:4]}
            got += 1
            print(f"  + {show} ← {r.get('name')} ({cache[show]['first'] or '?'})")
        else:
            cache[show] = {"tmdb": None}
            miss += 1
            print(f"  · {show}: no TMDB match, keeping the episode frame")
        CACHE.write_text(json.dumps(dict(sorted(cache.items())), ensure_ascii=False, indent=1) + "\n",
                         encoding="utf-8")
        time.sleep(0.25)                            # TMDB allows ~40/s; be gentle anyway
    print(f"\n{got} posters fetched · {miss} without a match · {len(shows) - len(todo)} already done")


if __name__ == "__main__":
    main()
