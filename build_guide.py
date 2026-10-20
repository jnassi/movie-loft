#!/usr/bin/env python3
"""Build guide.html — Movie Loft's channel guide.

    python3 build_guide.py

Reads   catalog-movies.json (build.py), catalog-shows.json (build_tv.py),
        apple-ids.json (fetch_apple_ids.py; optional — no Tune in without it),
        template-guide.html, and template.html's <style> block (shared look)
Writes  guide.html

This file decides WHAT each channel can air (its pool). WHEN things air is
worked out in the browser (template-guide.html), from a seed made of the
channel and the date, so every device shows the same lineup all day and no
server is involved. Comfort channels fill their pools at runtime from the
tags the Movie Loft server stores.

Channel kinds (the page's scheduler implements each):
  movies    shuffle a pool of movies
  blocks    movies in groups — a franchise in release order, or a director's
            films shuffled — one group at a time
  episodes  a random show from the pool, then a random episode of it — every
            show equally likely, so a 300-episode show doesn't swamp the rest
  epref     same, but from a named per-show episode list (the half-hour and
            hour channels, filtered by running time)
  marathon  one show at a time, a run of consecutive episodes, then the next
  loop      one movie, back to back all day ([loop] in movieloft.toml)
  mixed     films and episodes together (Super Heroes, Starfleet); defined
            under [channel."Name"] in corrections.toml
  comfort-movies / comfort-shows   pool comes from Comfort tags at runtime
"""
import json, os, re, sys, tomllib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import instance

ROOT = Path(__file__).resolve().parent
if "--root" in sys.argv:
    ROOT = Path(sys.argv[sys.argv.index("--root") + 1]).resolve()
OUT = ROOT / "guide.html"
CONFIG = instance.load(ROOT)        # rooms and the loop channel (movieloft.toml)

movies = json.loads((ROOT / "catalog-movies.json").read_text(encoding="utf-8"))
shows = json.loads((ROOT / "catalog-shows.json").read_text(encoding="utf-8"))
movies = [m for m in movies if m.get("secs")]            # can't schedule without a running time

# Shows with only a few episodes are mostly one-off purchases from the DVR
# years (an episode bought because the TiVo missed it). They stay in the TV
# Shows catalog but never air. 6 total, not "a 6-episode season", so Sherlock's
# three-episode seasons still count. [guide] keep_shows in corrections.toml
# lets a short show back in.
GUIDE = tomllib.loads((ROOT / "corrections.toml").read_text(encoding="utf-8") if (ROOT / "corrections.toml").exists() else "").get("guide", {})
MIN_EPISODES = GUIDE.get("min_episodes", 6)
KEEP = set(GUIDE.get("keep_shows", []))
# How many copies of the busy channel formats to run, like HBO, HBO2, HBO3.
# [guide] copies sets the default (1); [guide.channel_copies] overrides one
# format, and 0 turns it off. The name seeds the schedule, so "Marathon 2"
# runs a different lineup from "Marathon".
COPIES, PER = GUIDE.get("copies", 1), GUIDE.get("channel_copies", {})
FAMILIES = ("Movie Roulette", "Marathon", "The Half Hour", "The Hour", "Channel Surf")
for f in PER:
    if f not in FAMILIES:
        print(f"  ? [guide.channel_copies] {f!r} isn't one of: {', '.join(FAMILIES)}")


def copies(family):
    n = int(PER.get(family, COPIES))
    return [""] + [f" {k}" for k in range(2, n + 1)] if n > 0 else []
airs = {i for i, s in enumerate(shows) if len(s["eps"]) >= MIN_EPISODES or s["show"] in KEEP}
benched = sorted(s["show"] for i, s in enumerate(shows) if i not in airs)

channels = []
REFS_ALL = {}        # named episode lists (filled below), so add() can tell an empty one
MIXED = tomllib.loads((ROOT / "corrections.toml").read_text(encoding="utf-8") if (ROOT / "corrections.toml").exists() else "").get("channel", {})


def add(name, kind, blurb, **pool):
    # A channel with nothing to air is left out (a small library may have no
    # show long enough for a Marathon, say). Comfort channels fill at runtime.
    empty = (("pool" in pool and not pool["pool"]) or ("groups" in pool and not pool["groups"])
             or ("refs" in pool and not REFS_ALL.get(pool["refs"]))
             or (kind == "mixed" and not pool["movies"] and not pool["shows"]))
    if empty:
        print(f"  – {name}: nothing to air yet, left out")
        return
    channels.append({"num": len(channels) + 2, "name": name, "kind": kind, "blurb": blurb, **pool})


# ---- movies
add("Comfort Movies", "comfort-movies", "The ones you'd watch any night.")
series = defaultdict(list)
for i, m in enumerate(movies):
    if m["set"]:
        series[m["set"]].append(i)
add("Franchise Channel", "blocks", "Whole series, in release order.", order="in-order",
    groups=[sorted(v, key=lambda i: movies[i]["idx"]) for _, v in sorted(series.items()) if len(v) >= 2])
decades = defaultdict(list)
for i, m in enumerate(movies):
    if m["year"]:
        decades[min(m["year"] // 10 * 10, 2020) if m["year"] >= 1980 else 1900].append(i)
for d in sorted(decades):
    if len(decades[d]) < 15:
        continue
    label = "Classics" if d == 1900 else (f"The '{str(d)[2:]}s" if d < 2000 else f"The {d}s")
    blurb = "Before 1980." if d == 1900 else f"Released {d}–{d + 9}."
    add(label, "movies", blurb, pool=decades[d])
directors = defaultdict(list)
for i, m in enumerate(movies):
    for d in re.split(r"\s*&\s*|\s*,\s*", m["director"] or ""):
        if d:
            directors[d].append(i)
add("Director's Chair", "blocks", "One director at a time.", order="shuffle",
    groups=[v for _, v in sorted(directors.items()) if len(v) >= 3],
    labels=[k for k, v in sorted(directors.items()) if len(v) >= 3])
for n in copies("Movie Roulette"):
    add("Movie Roulette" + n, "movies", "Anything in the library.", pool=list(range(len(movies))))


def mixed(name, blurb):
    spec = MIXED.get(name)
    if not spec:
        return
    pats = [re.compile(p, re.I) for p in spec.get("match", [])]
    never, sets = set(spec.get("never", [])), set(spec.get("series", []))
    mv = [i for i, m in enumerate(movies) if m["title"] not in never
          and (m["set"] in sets or any(p.search(m["title"]) for p in pats))]
    spats = [re.compile(p, re.I) for p in spec.get("show_match", [])]
    names = set(spec.get("shows", []))
    sh = [i for i, s in enumerate(shows) if i in airs
          and (s["show"] in names or any(p.search(s["show"]) for p in spats))]
    unknown = sets - {m["set"] for m in movies} | names - {s["show"] for s in shows}
    if unknown:
        print(f"  ? [channel.\"{name}\"] names nothing in the library: {', '.join(sorted(unknown))}")
    add(name, "mixed", blurb, movies=mv, shows=sh, share=spec.get("movie_share", 0.5))


mixed("Super Heroes", "Capes, cowls, and the occasional hammer.")

# ---- TV
add("Comfort TV", "comfort-shows", "Comfort Shows, any episode.")
mixed("Starfleet", "Every Star Trek you own, films and series.")
long_runs = [i for i, s in enumerate(shows) if len(s["eps"]) >= 8]
# Grouped by show ([show, [episode, …]]) so the page can pick a show first,
# then an episode — every show gets an equal shot, however many episodes it has.
def by_show(keep):
    out = []
    for si, s in enumerate(shows):
        if si not in airs:
            continue
        eis = [ei for ei, e in enumerate(s["eps"]) if e[3] and keep(s, e)]
        if eis:
            out.append([si, eis])
    return out


half = by_show(lambda s, e: e[3] < 35 * 60)
# Star Trek is ~700 hour-long episodes — it would swamp The Hour, and it has
# Starfleet to itself anyway.
hour = by_show(lambda s, e: e[3] >= 38 * 60 and not s["show"].startswith("Star Trek"))
REFS_ALL.update(half=half, hour=hour)
for n in copies("Marathon"):
    add("Marathon" + n, "marathon", "One show, episode after episode.", pool=long_runs)
for n in copies("The Half Hour"):
    add("The Half Hour" + n, "epref", "Sitcoms and other half-hour shows.", refs="half")
for n in copies("The Hour"):
    add("The Hour" + n, "epref", "Hour-long dramas.", refs="hour")
for n in copies("Channel Surf"):
    add("Channel Surf" + n, "episodes", "Any episode of anything.", pool=sorted(airs))

# The loop channel ([loop] in movieloft.toml). Added last so existing channel
# numbers don't shift.
LOOP = CONFIG["loop"]
if LOOP:
    looped = [i for i, m in enumerate(movies) if m["title"] == LOOP["movie"]]
    if looped:
        add(LOOP["name"], "loop", LOOP.get("blurb", f"{LOOP['movie']}, all day."), pool=looped[:1])
    else:
        print(f"  ? [loop] movie {LOOP['movie']!r} isn't in the library (or has no running time)")

# Episode lists shared by several channels are embedded once and named.
REFS = {"half": half, "hour": hour}
print(f"{len(channels)} channels · {len(movies)} schedulable movies · "
      f"{len(airs)} of {len(shows)} shows on the air (fewer than {MIN_EPISODES} episodes sit out)")
if benched:
    print(f"  benched: {', '.join(benched)}")
for c in channels:
    size = (len(c.get("pool", [])) or len(c.get("groups", [])) or
            (f"{len(REFS[c['refs']])} shows / {sum(len(x[1]) for x in REFS[c['refs']])} eps" if c.get("refs") else 0)
            or (f"{len(c['movies'])} films + {len(c['shows'])} shows" if c["kind"] == "mixed" else "tags"))
    print(f"  {c['num']:>2}  {c['name']:<20} {c['kind']:<15} {size}")

epoch = os.environ.get("SOURCE_DATE_EPOCH")
now = (datetime.fromtimestamp(int(epoch), timezone.utc) if epoch
       else datetime.now(timezone.utc).astimezone())
movie_tpl = (ROOT / "template.html").read_text(encoding="utf-8")
base_css = movie_tpl[movie_tpl.index("<style>") + 7: movie_tpl.index("</style>")]
# Apple TV IDs (fetch_apple_ids.py) for the Tune in button; "" = can't tune.
apple = json.loads((ROOT / "apple-ids.json").read_text(encoding="utf-8")) if (ROOT / "apple-ids.json").exists() else {}
am, ash = apple.get("movies", {}), apple.get("shows", {})
compact_movies = [[m["raw"], m["title"], m["year"] or 0, m["director"], m["secs"], am.get(m["raw"], "")]
                  for m in movies]
# Episodes carry their own Apple TV ID (fetch_episode_ids.py) as a 5th field,
# minus the "umc.cmc." prefix to keep the page small; "" = no ID, so Tune in
# opens the show's page instead.
eids = json.loads((ROOT / "episode-ids.json").read_text(encoding="utf-8")) if (ROOT / "episode-ids.json").exists() else {}
compact_shows = [[s["show"],
                  [[*ep[:4], eids.get(s["show"], {}).get(f"{ep[0]}x{ep[1]}", "").removeprefix("umc.cmc.")]
                   for ep in s["eps"]],
                  ash.get(s["show"], ""), s.get("svc", "")] for s in shows]
print(f"Tune in: {sum(1 for m in compact_movies if m[5])}/{len(compact_movies)} movies, "
      f"{sum(1 for s in compact_shows if s[2])}/{len(compact_shows)} shows, "
      f"{sum(1 for s in compact_shows for e in s[1] if e[4])}/{sum(len(s[1]) for s in compact_shows)} episodes "
      f"have Apple TV IDs")
page = ((ROOT / "template-guide.html").read_text(encoding="utf-8")
        .replace("__BASE_CSS__", base_css)
        .replace("__MOVIES__", json.dumps(compact_movies, ensure_ascii=False, separators=(",", ":")))
        .replace("__SHOWS__", json.dumps(compact_shows, ensure_ascii=False, separators=(",", ":")))
        .replace("__CHANNELS__", json.dumps(channels, ensure_ascii=False, separators=(",", ":")))
        .replace("__REFS__", json.dumps(REFS, separators=(",", ":")))
        .replace("__ROOMS__", json.dumps([[r["key"], r["label"]] for r in CONFIG["rooms"]], ensure_ascii=False))
        .replace("__UPDATED__", now.strftime("%b %-d, %Y at %-I:%M %p")))
OUT.write_text(page, encoding="utf-8")
print(f"\nwrote {OUT.name} ({OUT.stat().st_size // 1024} KB)")
