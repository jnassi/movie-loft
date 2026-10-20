#!/usr/bin/env python3
"""Look up original US theatrical years from TMDB and cache them.

    python3 lookup_years.py             # fill in films not already cached
    python3 lookup_years.py --refresh   # re-look-up every film
    python3 lookup_years.py --limit 10  # stop after N lookups (sampling)

Reads   movies.tsv, theatrical.json
Writes  theatrical.json  (raw title -> {theatrical, digital, tmdbId, matched})

Needs a free TMDB v3 API key in $TMDB_API_KEY, or on the first line of a
.tmdb.key file next to this script (gitignored). This is the deliberate
full-refresh tool; build.py imports resolve()/api_key() from here to fill only
the gaps for newly bought films, and falls back silently if TMDB is unreachable.
"""
import json, os, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "movies.tsv"
CACHE = ROOT / "theatrical.json"
NO_MATCH = {"theatrical": None, "digital": None, "tmdbId": None, "matched": None}


def api_key(required=True, root=ROOT):
    """The TMDB key from $TMDB_API_KEY or <root>/.tmdb.key. Returns None (not
    exit) when required=False, so build.py can ask 'is a key available?' without
    dying. `root` lets build.py look relative to its own root — a fixture build
    then finds no key and stays offline."""
    k = os.environ.get("TMDB_API_KEY", "").strip()
    if not k and (root / ".tmdb.key").exists():
        k = (root / ".tmdb.key").read_text(encoding="utf-8").strip()
    if not k and required:
        sys.exit("No TMDB key. Put it in $TMDB_API_KEY or a .tmdb.key file.\n"
                 "Get one free at themoviedb.org -> Settings -> API -> API Key (v3 auth).")
    return k or None


def get(url, timeout=15, tries=3):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return json.load(r)
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(1.5)


def clean(raw):
    """Strip edition/year suffixes so the search matches the real title."""
    t = re.sub(r"\s*\[\d{4}\]$", "", raw.strip())
    for _ in range(2):
        t = re.sub(r"\s*\((?:Unrated|Director's Cut|Extended[^)]*|Special Edition|"
                   r"[^)]*Remaster[^)]*|[^)]*Anniversary[^)]*|Newly[^)]*|\d{4})\)$",
                   "", t).strip()
    return re.sub(r":\s*The Unrated Version$", "", t).strip()


def search(title, key, hint=None, timeout=15, tries=3):
    """Best match for a title. `hint` (a year) disambiguates remakes that share
    a title — e.g. Ghostbusters 1984 vs 2016 — without which TMDB just returns
    the most popular one."""
    q = urllib.parse.quote(title)
    res = get(f"https://api.themoviedb.org/3/search/movie?api_key={key}&query={q}",
              timeout, tries) or {}
    results = res.get("results", [])
    if not results:
        return None
    tl = title.lower()

    def score(r):
        exact = r.get("title", "").lower() == tl
        ry = (r.get("release_date") or "")[:4]
        near = -abs(int(ry) - hint) if hint and ry.isdigit() else 0
        return (exact, near, r.get("popularity", 0))

    return max(results, key=score)          # exact title, then closest to hint, then popular


def us_dates(movie_id, key, timeout=15, tries=3):
    """(earliest US theatrical year, earliest US digital/physical year)."""
    res = get(f"https://api.themoviedb.org/3/movie/{movie_id}/release_dates?api_key={key}",
              timeout, tries) or {}
    theatrical, later = [], []
    for block in res.get("results", []):
        if block.get("iso_3166_1") != "US":
            continue
        for d in block.get("release_dates", []):
            y = (d.get("release_date") or "")[:4]
            if not y.isdigit():
                continue
            (theatrical if d.get("type") in (2, 3) else later).append(int(y))
    return (min(theatrical) if theatrical else None,
            min(later) if later else None)


def resolve(raw, store_year, key, timeout=15, tries=3):
    """One raw title -> a cache record {theatrical, digital, tmdbId, matched}.
    An explicit (YYYY) in the title beats the store year as the search hint.
    Raises on a network/timeout failure — callers decide whether to stop."""
    paren = re.search(r"\((\d{4})\)", raw)          # a remake tag beats the store year
    hint = int(paren.group(1)) if paren else store_year
    m = search(clean(raw), key, hint, timeout, tries)
    if not m:
        return dict(NO_MATCH)
    th, dig = us_dates(m["id"], key, timeout, tries)
    if th is None:                                  # no US theatrical block; use headline date
        ry = (m.get("release_date") or "")[:4]
        th = int(ry) if ry.isdigit() else None
    return {"theatrical": th, "digital": dig, "tmdbId": m["id"], "matched": m.get("title")}


def main():
    key = api_key()
    refresh = "--refresh" in sys.argv
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    rows = []
    for ln in SRC.read_text(encoding="utf-8").split("\n"):
        if ln.strip():
            p = ln.split("\t")
            rows.append((p[0].strip(), int(p[1]) if len(p) > 1 and p[1].strip().isdigit() else None))

    done = 0
    for raw, yr in rows:
        if raw in cache and not refresh:
            continue
        if limit is not None and done >= limit:
            break
        rec = resolve(raw, yr, key)
        cache[raw] = rec
        if rec["tmdbId"] is None:
            print(f"  ? {raw}: no TMDB match")
        else:
            suspect = (rec["matched"] or "").lower() != clean(raw).lower()
            print(f"  + {raw}: {rec['theatrical']}"
                  f"  [{rec['matched']} #{rec['tmdbId']}]{'  << check match' if suspect else ''}")
        done += 1
        time.sleep(0.25)                    # be polite to the API

    CACHE.write_text(json.dumps(dict(sorted(cache.items())), ensure_ascii=False, indent=1)
                     + "\n", encoding="utf-8")
    print(f"\n{done} looked up, {len(cache)} cached -> {CACHE.name}")


if __name__ == "__main__":
    main()
