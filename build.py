#!/usr/bin/env python3
"""Turn the Apple TV app's movie export into index.html.

    python3 build.py            # normal run
    python3 build.py --check    # report the diff, write nothing

Reads   movies.tsv, corrections.toml, theatrical.json, library-state.json
Writes  index.html, library-state.json, catalog-movies.json (for build_guide.py),
        and theatrical.json when it fills gaps

Mostly offline. When a film is missing from theatrical.json and a TMDB key is
present, the build looks up just that film and caches it — so a new purchase
gets its real theatrical year from a plain `make`, no separate `make years`.
This is strictly best-effort: capped, short timeout, and on no key / no network
/ any API error it falls back to the store year and carries on. The build must
never fail or hang because TMDB is unreachable.
"""
import json, os, re, sys, unicodedata
from datetime import datetime, timezone
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("Needs Python 3.11+ for tomllib. Try: brew install python")
import tomllib
import lookup_years                              # resolve()/api_key(), import-safe

ROOT = Path(__file__).resolve().parent
if "--root" in sys.argv:                     # point at a fixture dir (tests)
    ROOT = Path(sys.argv[sys.argv.index("--root") + 1]).resolve()
SRC = ROOT / "movies.tsv"
CORRECTIONS = ROOT / "corrections.toml"
STATE = ROOT / "library-state.json"
OUT = ROOT / "index.html"
CHECK_ONLY = "--check" in sys.argv

EDITION_WORDS = ("Unrated", "Director's Cut", "Extended Version", "Extended Edition",
                 "Special Edition", "Remastered Feature", "Newly Remastered",
                 "35th Anniversary Edition")


def split_title(raw):
    """'Old School (Unrated) [2003]' -> ('Old School', 'Unrated')"""
    t = re.sub(r"\s*\[\d{4}\]$", "", raw.strip())
    edition = ""
    if t.endswith(": The Unrated Version"):
        t, edition = t[: -len(": The Unrated Version")], "Unrated"
    for _ in range(2):
        m = re.search(r"\s*\(([^)]+)\)$", t)
        if not m:
            break
        inner = m.group(1)
        if re.fullmatch(r"\d{4}", inner):        # a year — already a column
            t = t[: m.start()]
        elif inner in EDITION_WORDS:
            edition, t = inner, t[: m.start()]
        else:
            break
    return t.strip(), edition


def sort_key(s):
    k = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    k = re.sub(r"^(the|a|an)\s+", "", k)
    k = re.sub(r"[^a-z0-9 ]+", "", k)
    return re.sub(r"\d+", lambda m: m.group().zfill(6), k).strip()


# --------------------------------------------------------------------- inputs
if not SRC.exists():
    sys.exit(f"No {SRC.name}. Run: osascript export.applescript \"{ROOT}\"")

fixes = tomllib.loads(CORRECTIONS.read_text(encoding="utf-8")) if CORRECTIONS.exists() else {}
YEARS = fixes.get("years", {})
DIRECTORS = fixes.get("directors", {})
SERIES = fixes.get("series", {})

# Original US theatrical years from TMDB (see lookup_years.py). Optional — if the
# cache is missing, the build falls back to the store year, so it still runs from
# a bare checkout. CACHE keeps the full records (to write back gap fills); the
# THEATRICAL view is just raw title -> theatrical year.
THFILE = ROOT / "theatrical.json"
CACHE = json.loads(THFILE.read_text(encoding="utf-8")) if THFILE.exists() else {}
THEATRICAL = {k: v.get("theatrical") for k, v in CACHE.items()}


def _compile_series(spec_map):
    """[series."Name"] -> [(name, [compiled match regexes], also set, never set)].
    A bad regex fails here, named, instead of throwing mid-build."""
    rules = []
    for name, spec in spec_map.items():
        pats = []
        for p in spec.get("match", []):
            try:
                pats.append(re.compile(p, re.I))
            except re.error as e:
                sys.exit(f'corrections.toml: bad regex {p!r} in [series."{name}"] — {e}')
        rules.append((name, pats, set(spec.get("also", [])), set(spec.get("never", []))))
    return rules


SERIES_RULES = _compile_series(SERIES)


def series_hits(title):
    """Series (in file order) whose rules claim this cleaned title. `never`
    beats `also` and `match`; callers treat the first hit as the winner."""
    out = []
    for name, pats, also, never in SERIES_RULES:
        if title in never:
            continue
        if title in also or any(p.search(title) for p in pats):
            out.append(name)
    return out

state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
known = state.get("titles", {})
first_run = not known
epoch = os.environ.get("SOURCE_DATE_EPOCH")   # pin the clock for reproducible builds
now = (datetime.fromtimestamp(int(epoch), timezone.utc) if epoch
       else datetime.now(timezone.utc).astimezone())
today = now.date().isoformat()

# "\n" only, not splitlines(): U+0085 and friends inside a title would split the
# row (bit the TV export — see build_tv.py). Movies have none today; stay safe.
src_lines = SRC.read_text(encoding="utf-8").split("\n")

# Opportunistic gap fill: a film bought today isn't in theatrical.json yet, so it
# would show the store year until someone runs `make years`. Fill just the gaps
# here from TMDB so a plain `make` gets it right. Strictly best-effort — capped,
# short timeout, single try — and any failure (no key, offline, API error) falls
# back to the store year. Skipped entirely under --check (writes nothing).
GAP_CAP = 12            # a purchase is a handful of films; a full backfill is `make years`
want, filled = [], []
tmdb_key = None if CHECK_ONLY else lookup_years.api_key(required=False, root=ROOT)
if tmdb_key:
    seen_raw = set()
    for line in src_lines:
        if not line.strip():
            continue
        p = line.split("\t")
        raw = p[0].strip()
        if raw in CACHE or raw in seen_raw:      # already cached, or already queued
            continue
        seen_raw.add(raw)
        want.append((raw, int(p[1]) if len(p) > 1 and p[1].strip().isdigit() else None))
    for raw, sy in want[:GAP_CAP]:
        try:
            rec = lookup_years.resolve(raw, sy, tmdb_key, timeout=6, tries=1)
        except Exception:
            break                                # network hiccup — stop, fall back silently
        CACHE[raw] = rec
        THEATRICAL[raw] = rec["theatrical"]
        filled.append(raw)
    if filled:
        THFILE.write_text(json.dumps(dict(sorted(CACHE.items())), ensure_ascii=False,
                                     indent=1) + "\n", encoding="utf-8")

rows = []
for line in src_lines:
    if not line.strip():
        continue
    parts = line.split("\t")
    raw0 = parts[0]
    raw = raw0.strip()
    year = parts[1] if len(parts) > 1 else ""
    director = parts[2] if len(parts) > 2 else ""
    # (parts[3], the export's release date, is left unread — it turned out to be
    #  the same reissue date as the store year, so TMDB is the theatrical source.)
    secs = int(parts[4]) if len(parts) > 4 and parts[4].strip().isdigit() else None
    title, edition = split_title(raw)
    store = int(year) if year.strip().isdigit() else None   # the Apple TV app's stamp (reissue-ish)
    tmdb = THEATRICAL.get(raw)                               # original US theatrical, if known
    paren = re.search(r"\((\d{4})\)", raw)                   # "Ghostbusters (2016)": the library's
    paren_year = int(paren.group(1)) if paren else None      # own way of telling remakes apart
    # theatrical year: a hand [years] entry wins; then an explicit (YYYY) in the
    # title (so TMDB can't pull a remake back to the original's year); then TMDB,
    # but only when it isn't later than the store stamp (a later year means a
    # wrong match); else the store stamp.
    if raw in YEARS:
        y = YEARS[raw]
    elif paren_year:
        y = paren_year
    elif tmdb and (store is None or tmdb <= store):
        y = tmdb
    else:
        y = store
    reissue = store if (store and y and store - y >= 2) else None
    director = DIRECTORS.get(raw, director)
    hits = series_hits(title)
    rows.append({
        "raw": raw0, "key": raw, "title": title, "edition": edition, "year": y,
        "store": store, "reissue": reissue,
        "director": "" if director.strip() in ("", "Unknown") else director,
        "set": hits[0] if hits else "", "hits": hits, "secs": secs,
    })

# Collapse only rows with the identical raw title — the same film bought twice.
# Two different raw strings never merge, so a film can't silently vanish because
# TMDB happened to map it onto another film's (title, edition, year). (Good Will
# Hunting is the one real dup: bought twice, identical raw, collapses to one.)
# Which of the duplicates survives is deterministic, not export order (the Apple TV app
# orders by director, unstable across renames): earliest year wins, then the more
# populated row, then director name — so a re-export can't quietly change what's
# shown.
def _survivor(r):
    populated = sum(1 for v in (r["director"], r["reissue"]) if v)
    return (r["year"] if r["year"] is not None else 9999, -populated, r["director"])
by_raw = {}
for r in rows:
    by_raw.setdefault(r["raw"], []).append(r)
rows = [min(group, key=_survivor) for group in by_raw.values()]

# Near-miss: rows that WOULD have merged under the old (title, edition, year) key
# but have different raw titles. They stay as separate cards now; surface them so
# a real collision (e.g. an untagged remake pulled onto another film's year) is
# loud instead of a quietly dropped card.
_by_tey = {}
for r in rows:
    _by_tey.setdefault((r["title"], r["edition"], r["year"]), []).append(r["raw"])
collisions = {k: sorted(v) for k, v in _by_tey.items() if len(set(v)) > 1}

# ----------------------------------------------------------------- the diff
present = {r["key"] for r in rows}
added = sorted(present - set(known))
removed = sorted(set(known) - present)
for r in rows:
    entry = known.setdefault(r["key"], {"firstSeen": today})
    r["added"] = entry["firstSeen"]
gone = [{"title": t, "lastSeen": known[t]["firstSeen"], "removedOn": today}
        for t in removed]
for t in removed:
    known.pop(t)

# "Recent imports" = the films sharing the newest firstSeen date, i.e. the last
# time anything was added. Unlike the per-build `added` delta, this survives
# later rebuilds, so the page's "show only these" keeps working days later. On a
# fresh baseline every film shares one date, so there's no distinct batch.
adds = [r["added"] for r in rows]
recent_date = max(adds) if adds else None
recent_set = ({r["key"] for r in rows if r["added"] == recent_date}
              if recent_date and recent_date != min(adds) else set())
for r in rows:
    r["isNew"] = r["key"] in recent_set

# --------------------------------------------------------------- group & sort
groups, singles = {}, []
for r in rows:
    if r["set"]:
        groups.setdefault(r["set"], []).append(r)
    else:
        singles.append(r)
for name in [n for n, v in groups.items() if len(v) < 2]:
    singles.extend(groups.pop(name))

blocks = []
for name, films in groups.items():
    films.sort(key=lambda r: (r["year"] or 0, sort_key(r["title"]), r["edition"]))
    blocks.append({"name": name, "sortKey": sort_key(name), "films": films})
for r in singles:
    r["set"] = ""
    blocks.append({"name": "", "sortKey": sort_key(r["title"]), "films": [r]})
blocks.sort(key=lambda b: b["sortKey"])

flat = [{
    "raw": r["raw"], "title": r["title"], "edition": r["edition"], "year": r["year"],
    "reissue": r["reissue"], "director": r["director"], "set": b["name"],
    "idx": i, "of": len(b["films"]), "gk": b["sortKey"],
    "added": r["added"], "isNew": r["isNew"],
} for b in blocks for i, r in enumerate(b["films"], 1)]

total = len(flat)
setcount = sum(1 for b in blocks if b["name"])
fixed = sum(1 for r in rows if r["store"] and r["year"] != r["store"])
nodir = sum(1 for r in flat if not r["director"])
matched = {h for r in rows for h in r["hits"]}
dead = [name for name, *_ in SERIES_RULES if name not in matched]
multi = {r["title"]: r["hits"] for r in rows if len(r["hits"]) > 1}

# ------------------------------------------------------------------- report
print(f"{total} titles · {setcount} series · {fixed} year fixes · "
      f"{nodir} without a director")
if filled:
    print(f"\nFilled {len(filled)} theatrical-year gap(s) from TMDB: {', '.join(filled)}")
remaining = len(want) - len(filled)
if remaining > 0:      # cap reached, or TMDB went unreachable mid-fill — don't hide it
    why = "cap reached" if len(filled) >= GAP_CAP else "TMDB unreachable"
    print(f"\n{remaining} film(s) still on the store year ({why}) — "
          f"run `make` again or `make years` to finish.")
if first_run:
    print("First run — baseline recorded, nothing flagged as new.")
if added and not first_run:
    print(f"\nAdded ({len(added)}):")
    for t in added:
        print("  +", t)
if gone:
    print(f"\nGone ({len(gone)}):")
    for g in gone:
        print("  -", g["title"])
if dead:
    print("\nSeries rules that match nothing (typo?):")
    for name in dead:
        print("  ?", name)
if multi:
    print("\nTitles matching more than one series (first wins):")
    for title, hits in multi.items():
        print(f"  ! {title} — {', '.join(hits)}")
if collisions:
    print("\nCollision — same title/edition/year, different raw titles (both kept):")
    for (title, edition, year), raws in collisions.items():
        tag = f" [{edition}]" if edition else ""
        print(f"  ! {title}{tag} {year or '—'}: {', '.join(raws)}")
    print("  → usually two different films where one's year is wrong: pin the"
          " mis-dated raw title with a [years] entry so they no longer share a"
          " year. If they're genuinely one film, leave both (different raw titles"
          " never merge by design).")
# The [years] entries are a labelled set: how many would the TMDB lookup have
# derived on its own? (A high number means those [years] entries are redundant.)
labelled = [(r, YEARS[r["key"]]) for r in rows if r["key"] in YEARS]
if labelled:
    got = sum(1 for r, yr in labelled if THEATRICAL.get(r["key"]) == yr)
    print(f"\nTMDB reproduces {got}/{len(labelled)} of the [years] corrections "
          f"on its own.")
# Store years that are probably a digital-reissue date, not the original
# release. Two source-free tells, only for films not already fixed (the shown
# year still equals the store stamp):
#   1. reissue wording in the title paired with a recent (>=2000) year;
#   2. a same-director copy of the same film already in the library, dated
#      4+ years earlier — the newer one is the suspect. Same-director keeps
#      genuine reboots (different director, same title) from flagging.
REISSUE = re.compile(r"remaster|restored|restoration|anniversar|collector|"
                     r"deluxe|ultimate|special edition|definitive|4k|newly", re.I)
by_norm = {}
for r in rows:
    by_norm.setdefault(sort_key(r["title"]), []).append(r)
suspect = []
for r in rows:
    if not r["year"] or (r["store"] and r["year"] != r["store"]):
        continue    # no year, or already fixed away from the store stamp
    why = []
    if r["year"] >= 2000 and REISSUE.search(r["raw"]):
        why.append("reissue wording")
    older = [o["year"] for o in by_norm[sort_key(r["title"])]
             if o is not r and o["year"] and o["director"]
             and o["director"] == r["director"] and o["year"] <= r["year"] - 4]
    if older:
        why.append(f"same-director copy dated {min(older)}")
    if why:
        suspect.append((r, why))
if suspect:
    print("\nWorth an eyeball (store year may be a reissue date, not the original):")
    for r, why in suspect:
        print(f"  ? {r['raw']} {r['year']} — {', '.join(why)}")
if CHECK_ONLY:
    # Ungrouped films sharing a 2+ word leading phrase are a series waiting to
    # be declared. Advisory only — never written back to corrections.toml.
    STOP = {"the", "a", "an", "of", "in", "on", "to", "and", "or", "for"}
    buckets = {}
    for r in rows:
        if r["hits"]:
            continue
        toks = r["title"].split()               # keep apostrophes: "Lampoon's" stays whole
        if len(toks) >= 2:
            buckets.setdefault(tuple(t.lower() for t in toks[:2]), {})[r["title"]] = toks
    suggest = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        seqs = list(members.values())
        prefix = []                             # longest shared leading run of words
        for i in range(min(len(s) for s in seqs)):
            if len({s[i].lower() for s in seqs}) == 1:
                prefix.append(seqs[0][i])
            else:
                break
        if all(w.lower() in STOP for w in prefix):   # "In the ...", too generic to suggest
            continue
        starter = "^" + " ".join(re.escape(w) for w in prefix)
        suggest.append((sorted(members), starter))
    if suggest:
        print("\nUngrouped films that look like a series (add a [series] rule):")
        for titles, starter in sorted(suggest):
            print(f'  + {", ".join(titles)} → match = ["{starter}"]')
    print("\n--check: nothing written.")
    sys.exit(0)

# -------------------------------------------------------------------- output
recent_fmt = (datetime.strptime(recent_date, "%Y-%m-%d").strftime("%b %-d, %Y")
              if recent_set else "")
TEMPLATE = (ROOT / "template.html").read_text(encoding="utf-8")
page = (TEMPLATE
        .replace("__DATA__", json.dumps(flat, ensure_ascii=False,
                                        separators=(",", ":")))
        .replace("__TOTAL__", str(total))
        .replace("__SETS__", str(setcount))
        .replace("__FIXED__", str(fixed))
        .replace("__NODIR__", str(nodir))
        .replace("__UPDATED__", now.strftime("%b %-d, %Y at %-I:%M %p"))
        .replace("__ADDED__", str(len(recent_set)))
        .replace("__RECENT__", recent_fmt)
        .replace("__GONE__", json.dumps(gone, ensure_ascii=False)))
OUT.write_text(page, encoding="utf-8")

# The channel guide (build_guide.py) schedules from this. Derived, gitignored.
(ROOT / "catalog-movies.json").write_text(json.dumps([{
    "raw": r["raw"], "title": r["title"], "year": r["year"], "director": r["director"],
    "set": b["name"], "idx": i, "secs": r["secs"],
} for b in blocks for i, r in enumerate(b["films"], 1)], ensure_ascii=False,
    separators=(",", ":")), encoding="utf-8")

STATE.write_text(json.dumps({
    "lastRun": now.isoformat(timespec="seconds"),
    "lastAdded": [] if first_run else added,
    "lastRemoved": [g["title"] for g in gone],
    "titles": dict(sorted(known.items())),
}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

print(f"\nwrote {OUT.name} ({OUT.stat().st_size // 1024} KB) and {STATE.name}")
