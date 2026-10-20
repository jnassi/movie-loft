#!/usr/bin/env python3
"""Turn the TV.app episode export into tv.html.

    python3 build_tv.py            # normal run
    python3 build_tv.py --check    # report only, write nothing
    python3 build_tv.py --check --episodes   # …plus every show's episode list

Reads   episodes.tsv (from export-tv.applescript), streaming.json (optional;
        fetch_streaming.py — Apple TV+ shows), template-tv.html, and the
        <style> block of template.html (shared look)
Writes  tv.html

The TV app's episode metadata is messy, and most of this file is cleanup:

- Many complete-series purchases store every row as season 0, with the real
  season and episode inside the title: "Season 2, Episode 11: The Chinese
  Restaurant". Spelling varies ("Episode11:", "Episode 1, Pilot",
  "Season 4: Episode 20:", "Season 6A", "Episode 17/18"), so the parse is loose.
- Bonus material (trailers, featurettes, commentaries, deleted scenes) is
  mixed in with the episodes. It's split out as "extras": counted, but never
  shown as an episode or scheduled on a channel.
- Shows bought twice (individual seasons plus a complete series) list the
  same episode twice. Episodes collapse on (season, episode).
"""
import json, re, sys, unicodedata
from datetime import datetime, timezone
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if "--root" in sys.argv:
    ROOT = Path(sys.argv[sys.argv.index("--root") + 1]).resolve()
SRC = ROOT / "episodes.tsv"
OUT = ROOT / "tv.html"
CHECK_ONLY = "--check" in sys.argv

TITLED = re.compile(
    r"^(?:Season\s*(\d+)[A-Z]?|(The Final Season))\s*[,:]\s*Episode\s*(\d+)?"
    r"(?:\s*(?:/|and|&)\s*\d+)?\s*[:,]?\s*(.*)$", re.I)
EXTRA = re.compile(
    r"commentary|trailer|featurette|deleted scene|making of|making the|behind the|"
    r"^inside |inside the episode|wrap up|a look at|special feature|first look|"
    r"roundtable|panel|comic-con|sneak peek|in character|recap|preview|"
    r"laws of reflection|hack into|the art of|gag reel|writers' room|bonus video", re.I)
MIN_UNTITLED = 20 * 60      # see classify(): only counts for shows with no numbered episodes
FINAL = -1                  # placeholder season for "The Final Season", resolved per show

def sort_key(s):
    k = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    k = re.sub(r"^(the|a|an)\s+", "", k)
    k = re.sub(r"[^a-z0-9 ]+", "", k)
    return re.sub(r"\d+", lambda m: m.group().zfill(6), k).strip()


def classify(season, episode, name, secs):
    """-> (kind, source, season, episode, title). kind is 'episode', 'extra', or
    'long' (an unnumbered item 20+ minutes long, decided per show later).
    source says where the numbering came from, so duplicate purchases of the
    same season can be told apart: 'titled' (parsed out of a season-0 title)
    or 'numbered' (the TV app's own season/episode fields)."""
    m = TITLED.match(name)
    if m and not EXTRA.search(m.group(4) or ""):
        s = FINAL if m.group(2) else int(m.group(1))
        e = int(m.group(3)) if m.group(3) else 0
        return "episode", "titled", s, e, (m.group(4) or "").strip() or name
    if EXTRA.search(name):
        return "extra", "", season, episode, name
    if season > 0 and 0 < episode < 100:   # the store numbers bonus clips 101, 102…
        return "episode", "numbered", season, episode, name
    if secs >= MIN_UNTITLED:
        return "long", "untitled", season, episode, name
    return "extra", "", season, episode, name


if not SRC.exists():
    sys.exit(f"No {SRC.name}. Run: osascript export-tv.applescript \"{ROOT}\"")

shows = {}
# Split on "\n" only, never splitlines(): titles can carry U+0085 (a stray
# Mac-Roman ellipsis — The West Wing's "He Shall, From Time to Time…"), which
# splitlines() treats as a line break, silently cutting the row in two.
for line in SRC.read_text(encoding="utf-8").split("\n"):
    if not line.strip():
        continue
    p = line.split("\t")
    if len(p) < 6:
        continue
    show, name = p[0], p[3].replace("\x85", "…")
    s, e, secs, year = int(p[1] or 0), int(p[2] or 0), int(p[4] or 0), int(p[5] or 0)
    kind, source, s, e, title = classify(s, e, name, secs)
    rec = shows.setdefault(show, {"items": [], "extras": 0, "years": set()})
    if kind == "extra":
        rec["extras"] += 1
        continue
    rec["items"].append({"kind": kind, "src": source, "s": s, "e": e, "t": title,
                         "d": secs, "raw": e})
    if year:
        rec["years"].add(year)


def pick_episodes(rec):
    """Resolve one show's items into a clean episode list."""
    items = rec["items"]
    numbered = [x for x in items if x["kind"] == "episode"]
    if not numbered:                       # a miniseries in parts, a pilot, a special:
        eps = [x for x in items]           # the long untitled items ARE the show
        for i, x in enumerate(sorted(eps, key=lambda x: x["raw"]), 1):
            x["s"], x["e"] = 1, i
        return eps
    rec["extras"] += sum(1 for x in items if x["kind"] == "long")   # docs, finales-specials
    # Short clips that slipped past the wording filter ("Inside Breaking Bad",
    # recaps): anything under half the show's typical episode length.
    durs = sorted(x["d"] for x in numbered)
    floor = durs[len(durs) // 2] / 2 if durs else 0
    short = [x for x in numbered if x["d"] < floor]
    rec["extras"] += len(short)
    numbered = [x for x in numbered if x["d"] >= floor]
    # "The Final Season, Episode 3: …" carries no season number. If its titles
    # match a numbered season (Breaking Bad sells it as "Season 6"), it's that
    # season; otherwise it's one past the last.
    finals = [x for x in numbered if x["s"] == FINAL]
    if finals:
        names = {sort_key(x["t"]) for x in finals}
        overlap = {}
        for x in numbered:
            if x["s"] != FINAL and sort_key(x["t"]) in names:
                overlap[x["s"]] = overlap.get(x["s"], 0) + 1
        top = max([x["s"] for x in numbered if x["s"] > 0] or [0])
        target = max(overlap, key=overlap.get) if overlap else top + 1
        for x in finals:
            x["s"] = target
    # The TV app's own numbering counts bonus clips as episodes ("Inside Mad Men"
    # sits at e2 between e1 and e3), so after the clips are gone, renumber each
    # season's numbered rows 1..n in their original order.
    by = {}
    for x in numbered:
        by.setdefault((x["s"], x["src"]), []).append(x)
    for (season, src), xs in by.items():
        if src == "numbered":
            for i, x in enumerate(sorted(xs, key=lambda x: x["raw"]), 1):
                x["e"] = i
    # Same season bought twice (single season + complete series): keep ONE copy of
    # the season — the source with more episodes, ties going to the titled copy.
    # Merging the two by episode number would pair up the wrong episodes when one
    # copy splits a two-parter and the other doesn't.
    keep = {}
    for (season, src), xs in by.items():
        best = keep.get(season)
        if best is None or (len(xs), src == "titled") > (len(best), best[0]["src"] == "titled"):
            keep[season] = xs
    eps = [x for xs in keep.values() for x in xs]
    rec["extras"] += len(numbered) - len(eps)        # dropped duplicates
    rec["dupes"] = len(numbered) - len(eps)
    return eps


out, dropped = [], []
for show, rec in shows.items():
    eps = pick_episodes(rec)
    eps.sort(key=lambda x: (x["s"], x["e"], sort_key(x["t"])))
    if not eps:
        dropped.append((show, rec["extras"]))
        continue
    yrs = sorted(rec["years"])
    out.append({
        "show": show,
        "gk": sort_key(show),
        "seasons": len({x["s"] for x in eps}),
        "count": len(eps),
        "hours": round(sum(x["d"] for x in eps) / 3600),
        "years": (f"{yrs[0]}" if len(yrs) == 1 else f"{yrs[0]}–{yrs[-1]}") if yrs else "",
        "first": yrs[0] if yrs else 0,
        "extras": rec["extras"] - rec.get("dupes", 0),
        "eps": [[x["s"], x["e"], x["t"], x["d"]] for x in eps],
    })
# Streamed shows (fetch_streaming.py → streaming.json): not in the Apple TV app
# library, so not in episodes.tsv. Already clean (TMDB), so no cleanup — just
# add them, badged with their service. They mix into every TV channel.
STREAM = ROOT / "streaming.json"
streamed = json.loads(STREAM.read_text(encoding="utf-8")) if STREAM.exists() else {}
for show, rec in streamed.items():
    if show in shows or not rec.get("eps"):
        continue                                   # owned copy wins
    eps = sorted(rec["eps"])
    out.append({
        "show": show, "gk": sort_key(show),
        "seasons": len({e[0] for e in eps}), "count": len(eps),
        "hours": round(sum(e[3] for e in eps) / 3600),
        "years": str(rec.get("first") or ""), "first": rec.get("first") or 0,
        "extras": 0, "eps": eps, "svc": rec.get("service", ""),
    })

out.sort(key=lambda r: r["gk"])

total_eps = sum(r["count"] for r in out)
total_extras = sum(r["extras"] for r in out) + sum(n for _, n in dropped)
total_dupes = sum(rec.get("dupes", 0) for rec in shows.values())
n_stream = sum(1 for r in out if r.get("svc"))
print(f"{len(out)} shows ({n_stream} streamed) · {total_eps} episodes · {total_extras} extras set aside · "
      f"{total_dupes} duplicate-purchase episodes collapsed")
if dropped:
    print("\nNo episodes left after removing extras (not shown):")
    for show, n in dropped:
        print(f"  - {show} ({n} extras)")
if CHECK_ONLY:
    print("\nPer show (episodes / extras):")
    for r in out:
        print(f"  {r['count']:4d} / {r['extras']:3d}  {r['show']}")
        if "--episodes" in sys.argv:                 # full listing (the golden test uses it)
            for s_, e_, t_, d_ in r["eps"]:
                print(f"           S{s_} E{e_}  {t_}  ({d_ // 60} min)")
    print("\n--check: nothing written.")
    sys.exit(0)

epoch = os.environ.get("SOURCE_DATE_EPOCH")
now = (datetime.fromtimestamp(int(epoch), timezone.utc) if epoch
       else datetime.now(timezone.utc).astimezone())
# The movie page's stylesheet is the single source of the shared look.
movie_tpl = (ROOT / "template.html").read_text(encoding="utf-8")
base_css = movie_tpl[movie_tpl.index("<style>") + 7: movie_tpl.index("</style>")]
page = ((ROOT / "template-tv.html").read_text(encoding="utf-8")
        .replace("__BASE_CSS__", base_css)
        .replace("__DATA__", json.dumps(out, ensure_ascii=False, separators=(",", ":")))
        .replace("__SHOWS__", str(len(out)))
        .replace("__EPISODES__", f"{total_eps:,}")
        .replace("__UPDATED__", now.strftime("%b %-d, %Y at %-I:%M %p")))
OUT.write_text(page, encoding="utf-8")
# The channel guide (build_guide.py) schedules from this. Derived, gitignored.
(ROOT / "catalog-shows.json").write_text(json.dumps(
    [{"show": r["show"], "first": r["first"], "eps": r["eps"], "svc": r.get("svc", "")} for r in out],
    ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"\nwrote {OUT.name} ({OUT.stat().st_size // 1024} KB)")
