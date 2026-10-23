#!/usr/bin/env python3
"""Look up each episode's Apple TV ID, so Tune in can open the exact episode.

    python3 fetch_episode_ids.py          # shows not fetched yet, plus streamed shows
    python3 fetch_episode_ids.py --redo   # every show again

Source: the episode list tv.apple.com's own pages use —
  https://tv.apple.com/api/uts/v3/shows/<show umc id>/episodes?nextToken=<skip>:<count>
It's undocumented. It needs two keys (utscf, utsk) that tv.apple.com embeds
in every page; they're read fresh from a show page each run rather than
hard-coded, since Apple can rotate them. If Apple changes the API, this
script fails and the guide keeps opening show pages (what it did before).

Matches against catalog-shows.json (the cleaned-up episodes build_tv.py
produces) by TITLE first, since Apple sometimes numbers a show differently (a
split pilot shifts a whole season); numbers break ties, and decide alone only
when a title is a placeholder ("Episode 3", "1801"). An episode with no match
gets no ID, and its Tune in opens the show page as before. Writes episode-ids.json:
  {"<show>": {"<season>x<episode>": "umc.cmc…"}}

Streamed shows (fetch_streaming.py) also get each episode's play link on their
service — Apple's catalog lists, per episode, every service that carries it
and that service's own link (hulu://…, https://play.hbomax.com/…). Tune in
opens that link, which starts the episode in the service's app. Which of your
services plays a show is decided here, from Apple's catalog (what Tune in
really opens), overriding fetch_streaming.py's guess from TMDB. Writes
stream-links.json:
  {"<show>": {"service": "Hulu", "eps": {"<season>x<episode>": "<play link>"}}}
Apple TV+ shows get no links (their episode IDs play in the Apple TV app).
"""
import difflib, json, re, sys, time, tomllib, unicodedata, urllib.parse, urllib.request

from app.services import SERVICES
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "episode-ids.json"
LINKS = ROOT / "stream-links.json"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
                    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"}
PAGE = 100


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8")


def keys(pfm="web"):
    """The query string tv.apple.com's own pages send to the API. pfm="appletv"
    asks as an Apple TV would: the whole catalog (every service), where "web"
    sees only what plays on tv.apple.com (Apple TV+ and purchases)."""
    html = fetch("https://tv.apple.com/us")
    got = {k: re.search(rf'"{k}":"([^"]+)"', html) for k in ("utscf", "utsk", "sf", "v")}
    if not all(got.values()):
        sys.exit("✗ tv.apple.com's page no longer carries the API keys — the page changed. "
                 "Tune in keeps opening show pages.")
    return f"caller=web&pfm={pfm}&locale=en-US&" + "&".join(f"{k}={m.group(1)}" for k, m in got.items())


def search_show(title, year, q):
    """A show's Apple TV ID from Apple's own search (q from keys("appletv")):
    the result with the same title, first aired within a year of `year`."""
    d = json.loads(fetch("https://tv.apple.com/api/uts/v3/search?searchTerm="
                         + urllib.parse.quote(title) + "&" + q))["data"]
    for shelf in d.get("canvas", {}).get("shelves", []):
        for it in shelf.get("items", []):
            y = time.gmtime(it["releaseDate"] / 1000).tm_year if it.get("releaseDate") else None
            if (it.get("type") == "Show" and norm(it.get("title", "")) == norm(title)
                    and (not year or not y or abs(y - year) <= 1)):
                return it["id"]
    return None


def episodes(show_id, q):
    """Every episode Apple lists for the show: [(season, episode, umc id, title,
    {service: play link})] — the links only when q asks as an Apple TV."""
    out, skip, total = [], 0, None
    while total is None or skip < total:
        d = json.loads(fetch(f"https://tv.apple.com/api/uts/v3/shows/{show_id}/episodes?{q}"
                             f"&nextToken={skip}:{PAGE}"))["data"]
        eps = d.get("episodes") or []
        total = d.get("totalEpisodeCount", len(eps))
        chans = {k: c.get("name", "") for k, c in (d.get("channels") or {}).items()}
        plays = d.get("playables") or {}

        def links(eid):
            got = {}
            for ref in (d.get("episodesPlayables") or {}).get(eid, []):
                p = plays.get(ref.get("playableId"), {})
                url = (p.get("punchoutUrls") or {}).get("play")
                if url:
                    got.setdefault(chans.get(p.get("channelId"), ""), url)
            return got

        out += [(e["seasonNumber"], e["episodeNumber"], e["id"], e.get("title") or "", links(e["id"]))
                for e in eps if e.get("seasonNumber") and e.get("episodeNumber") and e.get("id")]
        if not eps:
            break
        skip += len(eps)
        time.sleep(0.3)                 # be polite
    return out


PARTS = {"one": "1", "two": "2", "three": "3", "i": "1", "ii": "2", "iii": "3"}


def norm(t):
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower().replace("&", "and")
    # "Part I" / "Pt. 1" / "Part One" / "(1)" all → "part1"
    t = re.sub(r"\b(?:part|pt)\.?\s*(one|two|three|iii|ii|i|\d+)\b",
               lambda m: "part" + PARTS.get(m.group(1), m.group(1)), t)
    t = re.sub(r"\((\d)\)\s*$", r"part\1", t)
    t = re.sub(r"\(.*?\)|\[.*?\]", "", t)
    return re.sub(r"[^a-z0-9]+", "", re.sub(r"^(the|a|an) ", "", t.strip()))


def same(a, b):
    """Same episode title, give or take punctuation, "Part 1" styling, and a
    leading article."""
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    da, db = re.findall(r"\d+", a), re.findall(r"\d+", b)
    if da and db and da != db:          # "Part 1" is not "Part 2"
        return False
    if a == b or (min(len(a), len(b)) >= 6 and (a in b or b in a)):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


WORDS = "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
GENERIC = re.compile(rf"^(\d+|(episode|season\d+episode|part|chapter|week)(\d+|{WORDS}))$")


def generic(title, show):
    """A placeholder title ("01", "Episode Two", "1801", the show's own name)."""
    t = norm(title)
    return not t or bool(GENERIC.match(t)) or t == norm(show)


def match(show, mine, apple):
    """{"<s>x<e>": umc id} for my episodes, each Apple episode used at most
    once. Three passes: number and title agree; then title alone, anywhere in
    the show (Apple sometimes numbers differently: a pilot split in two shifts
    a whole season), nearest number winning a tie; then number alone, only
    when a title is a placeholder. Returns (ids, unmatched)."""
    ids, used = {}, set()
    by_num = {(s, e): a for a in apple for s, e in [a[:2]]}
    todo = [(s, e, t) for s, e, t, *_ in mine]

    def take(k, a):
        ids[k] = a[2]
        used.add(a[2])

    for s, e, t in todo:
        a = by_num.get((s, e))
        if a and not generic(t, show) and same(t, a[3]):
            take(f"{s}x{e}", a)
    for s, e, t in todo:
        k = f"{s}x{e}"
        if k in ids or generic(t, show):
            continue
        hits = sorted((a for a in apple if a[2] not in used and same(t, a[3])),
                      key=lambda a: (a[0] != s, abs(a[1] - e)))
        if hits:
            take(k, hits[0])
    for s, e, t in todo:
        k, a = f"{s}x{e}", by_num.get((s, e))
        if k not in ids and a and a[2] not in used and (generic(t, show) or generic(a[3], show)):
            take(k, a)
    miss = [f"{s}x{e} {t!r}" + (f" (Apple's is {by_num[(s, e)][3]!r})" if (s, e) in by_num else "")
            for s, e, t in todo if f"{s}x{e}" not in ids]
    return ids, miss


def your_services():
    from fetch_streaming import your_services as parse
    spec = tomllib.loads((ROOT / "corrections.toml").read_text(encoding="utf-8")
                         if (ROOT / "corrections.toml").exists() else "").get("streaming", {})
    return parse(spec)


def choose(ids, by_id, mine, listed=()):
    """Which of my services plays a streamed show, going by Apple's catalog
    (it's what Tune in actually opens): the first, in my order, that carries
    at least half the episodes I have — else the one carrying the most.
    Services TMDB also lists (`listed`) go first: Apple's catalog files
    add-on channels under the store that sells them (Paramount+ bought
    through Prime shows up as Prime Video), and TMDB tells those apart. Apple
    TV+ episodes carry no outside link (they play in the Apple TV app), so
    "no links at all" counts as Apple TV+.
    Returns (service, {"<s>x<e>": play link}) — no links for Apple TV+."""
    def carried(svc):
        if svc == "Apple TV+":
            return {k: "" for k, i in ids.items() if not by_id.get(i)}
        name = SERVICES[svc]["apple"]
        return {k: by_id[i][name] for k, i in ids.items() if name in by_id.get(i, {})}
    for pool in ([s_ for s_ in mine if s_ in listed], mine):
        cover = [(svc, carried(svc)) for svc in pool]
        cover = [(svc, eps) for svc, eps in cover if eps]
        if cover:
            svc, eps = next(((s_, e_) for s_, e_ in cover if len(e_) * 2 >= len(ids)),
                            max(cover, key=lambda c: len(c[1])))
            return svc, ({} if svc == "Apple TV+" else eps)
    return None, {}


def main():
    redo = "--redo" in sys.argv
    shows = json.loads((ROOT / "apple-ids.json").read_text(encoding="utf-8"))["shows"]
    catalog = {s["show"]: s for s in json.loads((ROOT / "catalog-shows.json").read_text(encoding="utf-8"))}
    streamed = json.loads((ROOT / "streaming.json").read_text(encoding="utf-8")) \
        if (ROOT / "streaming.json").exists() else {}
    have = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() and not redo else {}
    links = {}                                     # rebuilt every run: streamed shows come and go
    todo = [s for s in shows if s in catalog and (s not in have or s in streamed)]
    if not todo:
        if not streamed and LINKS.exists():
            LINKS.write_text("{}\n", encoding="utf-8")
        print("Episode IDs: nothing new to look up")
        return
    q_web, q_tv = keys(), (keys("appletv") if streamed else None)
    mine = your_services() if streamed else []
    for show in todo:
        try:
            apple = episodes(shows[show], q_tv if show in streamed else q_web)
        except Exception as e:                 # one show failing shouldn't sink the rest
            print(f"  ? {show}: {e}")
            continue
        have[show], miss = match(show, catalog[show]["eps"], apple)
        if show in streamed:
            svc, eps = choose(have[show], {a[2]: a[4] for a in apple}, mine,
                              streamed[show].get("listed", ()))
            if svc:
                links[show] = {"service": svc, "eps": eps}
                if svc != "Apple TV+" and len(eps) < len(have[show]):
                    print(f"  ~ {show}: {len(eps)}/{len(have[show])} episodes have a {svc} link")
            else:
                print(f"  ? {show}: Apple's catalog has it on none of your services — "
                      "Tune in opens its page")
        if miss:
            print(f"  ~ {show}: {len(have[show])}/{len(catalog[show]['eps'])} episodes matched")
            for m in miss[:3]:
                print("      no match:", m)
    OUT.write_text(json.dumps(dict(sorted(have.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    LINKS.write_text(json.dumps(dict(sorted(links.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    n = sum(len(s["eps"]) for name, s in catalog.items() if name in shows)
    got = sum(len(v) for k, v in have.items() if k in catalog)
    print(f"Episode IDs: {got}/{n} episodes of {len(have)} shows"
          + (f" · play links for {sum(len(v['eps']) for v in links.values())} streamed episodes" if links else ""))


if __name__ == "__main__":
    main()
