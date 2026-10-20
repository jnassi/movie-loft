#!/usr/bin/env python3
"""Look up each title's Apple TV ID, so the guide can tune an Apple TV to it.

    python3 fetch_apple_ids.py          # look up anything not yet in apple-ids.json
    python3 fetch_apple_ids.py --redo   # look everything up again

Source: Wikidata, matched on TMDB IDs Movie Loft already has —
  movies: theatrical.json tmdbId  → Wikidata P4947 (TMDB movie ID) → P9586 (Apple TV movie ID)
  shows:  tv-art.json tmdb        → Wikidata P4983 (TMDB TV ID)    → P9751 (Apple TV show ID)
(Apple's iTunes Search API stopped returning movies in 2026, and the Apple TV
app's library file is encrypted, so neither is an option.)

The ID is a "umc.cmc.…" string; the tv.apple.com link is built from it at
tune-in time. Titles Wikidata doesn't know are pinned by hand in
corrections.toml with their tv.apple.com link. (The Apple TV app has no
Share → Copy Link; a web search limited to tv.apple.com finds them —
tv.apple.com's own search only renders results with JavaScript.)
  [apple_tv]
  "Seven" = "https://tv.apple.com/us/movie/se7en/umc.cmc.xxxxx"
Pins win over Wikidata. Writes apple-ids.json:
  {"movies": {"<raw title>": "umc.cmc…"}, "shows": {"<show>": "umc.cmc…"}}
"""
import json, re, sys, tomllib, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "apple-ids.json"
# Wikidata asks for a descriptive User-Agent with a way to reach the project.
UA = {"User-Agent": "MovieLoft/0.1 (personal media catalog; https://github.com/jnassi/movie-loft)"}
UMC = re.compile(r"umc\.cmc\.[a-z0-9]+")


def sparql(query):
    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": query, "format": "json"})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
        return json.load(r)["results"]["bindings"]


def lookup(tmdb_ids, tmdb_prop, apple_prop):
    """{tmdb id (str) -> umc id} for the ids Wikidata knows, in batches."""
    out, ids = {}, sorted({str(i) for i in tmdb_ids})
    for k in range(0, len(ids), 200):
        vals = " ".join(f'"{i}"' for i in ids[k:k + 200])
        for row in sparql(f"SELECT ?t ?a WHERE {{ VALUES ?t {{ {vals} }} "
                          f"?x wdt:{tmdb_prop} ?t . ?x wdt:{apple_prop} ?a . }}"):
            out.setdefault(row["t"]["value"], row["a"]["value"])
    return out


def main():
    redo = "--redo" in sys.argv
    pins = tomllib.loads((ROOT / "corrections.toml").read_text(encoding="utf-8") if (ROOT / "corrections.toml").exists() else "").get("apple_tv", {})
    prev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() and not redo else {}
    have_m, have_s = prev.get("movies", {}), prev.get("shows", {})

    movies = {raw: v["tmdbId"] for raw, v in json.loads((ROOT / "theatrical.json").read_text(encoding="utf-8")).items()
              if v.get("tmdbId")}
    raws = [l.split("\t")[0] for l in (ROOT / "movies.tsv").read_text(encoding="utf-8").split("\n") if l.strip()]
    shows = {s: v["tmdb"] for s, v in json.loads((ROOT / "tv-art.json").read_text(encoding="utf-8")).items()
             if v.get("tmdb")}
    if (ROOT / "streaming.json").exists():          # streamed shows (Apple TV+) too
        for s, v in json.loads((ROOT / "streaming.json").read_text(encoding="utf-8")).items():
            shows.setdefault(s, v["tmdb"])

    want_m = {r: movies[r.strip()] for r in raws if r.strip() in movies and r not in have_m}
    want_s = {s: t for s, t in shows.items() if s not in have_s}
    got_m = lookup(want_m.values(), "P4947", "P9586") if want_m else {}
    got_s = lookup(want_s.values(), "P4983", "P9751") if want_s else {}
    for r, t in want_m.items():
        if str(t) in got_m:
            have_m[r] = got_m[str(t)]
    for s, t in want_s.items():
        if str(t) in got_s:
            have_s[s] = got_s[str(t)]
    for title, link in pins.items():                    # hand pins win
        m = UMC.search(link or "")
        if not m:
            print(f"  ? [apple_tv] {title!r}: no umc.cmc… ID in {link!r}")
            continue
        (have_s if title in shows and title not in raws else have_m)[title] = m.group(0)

    OUT.write_text(json.dumps({"movies": dict(sorted(have_m.items())), "shows": dict(sorted(have_s.items()))},
                              ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    miss_m = sorted(r for r in raws if r not in have_m)
    print(f"{len(have_m)}/{len(raws)} movies and {len(have_s)}/{len(shows)} shows have an Apple TV ID")
    if miss_m:
        print("Movies still without one (pin under [apple_tv] in corrections.toml):")
        for r in miss_m:
            print("  -", r)


if __name__ == "__main__":
    main()
