#!/usr/bin/env bash
#
# The one command. After buying a movie, run `make` (which runs this) and walk
# away. It:
#   1. pulls your library out of the Apple TV app  (movies.tsv, episodes.tsv + any
#      new cover art)
#   2. looks up posters, years, and Apple TV links for anything new, and
#      rebuilds index.html, tv.html, and guide.html
#   3. if anything changed, commits the inputs + the built pages + new art and
#      pushes — which deploys, if your host builds from the repo (Railway does)
#   4. opens the local page so you can see it
#
# Nothing to remember, no flags. If the export fails (the Apple TV app isn't
# signed in, or macOS hasn't allowed Terminal to control it), it says so and
# stops before touching anything.

set -euo pipefail
cd "$(dirname "$0")"

echo "→ Reading your library from the Apple TV app…"
if ! osascript export.applescript "$PWD"; then
    echo "✗ Couldn't read the Apple TV app. Open it, make sure you're signed in, and try again." >&2
    exit 1
fi
echo

echo "→ Reading TV episodes from the Apple TV app…"
# Best-effort: if the TV export fails, keep the last episodes.tsv and carry on,
# so a TV hiccup never blocks a movie update.
if ! osascript export-tv.applescript "$PWD"; then
    echo "⚠ Couldn't read TV episodes — keeping the previous episodes.tsv." >&2
fi
# Streamed shows (Apple TV+) from TMDB — new episodes appear on their own.
python3 fetch_streaming.py 2>/dev/null | tail -2 || echo "⚠ Couldn't refresh streamed shows — keeping what's there." >&2
# Posters for any show not looked up yet (best-effort: no TMDB key or no
# network just means the episode frame stays for now).
python3 fetch_tv_art.py 2>/dev/null | tail -1 || echo "⚠ Couldn't fetch TV posters — keeping what's there." >&2
echo

echo "→ Rebuilding the pages…"
report="$(python3 build.py)"
echo "$report"
# Apple TV IDs for anything new, so the guide can tune to it (best-effort).
# After build.py and fetch_tv_art.py, because it looks titles up by their
# TMDB IDs, which those two fill in for new purchases. (Running it first left
# every new title without a Tune in link until the next make.)
python3 fetch_apple_ids.py 2>/dev/null | head -1 || echo "⚠ Couldn't look up Apple TV IDs — keeping what's there." >&2
tvreport=""
if [ -f episodes.tsv ]; then
    tvreport="$(python3 build_tv.py)"
    echo "$tvreport"
    # Episode IDs for exact-episode Tune in. Runs after build_tv.py (it matches
    # against catalog-shows.json). Best-effort: if Apple's undocumented episode
    # list breaks, episodes fall back to opening the show's page.
    python3 fetch_episode_ids.py 2>&1 | tail -1 || true
    python3 build_guide.py | tail -1
    # The guide's rules (no double-booking, :00/:30 starts, nothing past 6 AM)
    # against the new library. A warning, not a gate: a scheduling bug
    # shouldn't hold up a purchase, but it should be seen.
    if command -v node >/dev/null; then
        node tests/guide_test.mjs || echo "⚠ The guide broke one of its own rules — worth a look (make test)."
    fi
fi
echo

# Did anything that changes the site actually change? Check the inputs — a new
# purchase (movies.tsv + art), a hand edit (corrections.toml, movieloft.toml), or a years
# refresh (theatrical.json). index.html itself can't be the signal: it carries
# a per-build timestamp, so it churns every run. On a true no-op, drop that
# churn (index.html + library-state.json) and stop without committing.
if [ -z "$(git status --porcelain -- movies.tsv corrections.toml movieloft.toml theatrical.json art episodes.tsv art-tv tv-art.json apple-ids.json streaming.json episode-ids.json)" ]; then
    git checkout -- library-state.json index.html tv.html guide.html 2>/dev/null || true
    echo "✓ Nothing new since last time. Done."
    exit 0
fi

# Guard: never deploy with missing posters. The art is committed, so this
# should never trip — but if an export went wrong and wiped art/, pushing it
# would ship a page that makes every visitor hammer the iTunes API. Bail loudly
# rather than deploy that. (Deploy = this push; Railway auto-builds from it.)
movies=$(grep -c . movies.tsv)
posters=$(ls art 2>/dev/null | wc -l | tr -d ' ')
if [ "$posters" -lt "$(( movies / 2 ))" ]; then
    echo "✗ art/ has $posters posters for $movies titles — that's too thin, not deploying." >&2
    echo "  Open the Apple TV app and run 'make export', then try again." >&2
    exit 1
fi
if [ -f episodes.tsv ]; then
    shows=$(cut -f1 episodes.tsv | sort -u | grep -c . || true)
    covers=$(ls art-tv 2>/dev/null | wc -l | tr -d ' ')
    if [ "$covers" -lt "$(( shows / 2 ))" ]; then
        echo "✗ art-tv/ has $covers covers for $shows shows — too thin, not deploying." >&2
        exit 1
    fi
fi

echo "→ Saving…"
# Only what exists: corrections.toml, the TV files and the ID caches are all
# optional on a new instance.
files=()
for f in movies.tsv corrections.toml movieloft.toml theatrical.json library-state.json index.html art \
         episodes.tsv tv.html guide.html art-tv tv-art.json apple-ids.json streaming.json episode-ids.json; do
    [ -e "$f" ] && files+=("$f")
done
git add "${files[@]}"
git commit -q -m "Update library $(date +%Y-%m-%d)" -m "$report" ${tvreport:+-m "$tvreport"}
# Pushing is the deploy (a host like Railway builds from the repo). No remote
# yet — e.g. still running locally — just means it stays committed here.
if git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
    git push -q
    echo "✓ Committed and pushed. If your host deploys on push, the site updates in a minute or two."
else
    echo "✓ Committed. (No remote to push to yet, so nothing was deployed.)"
fi

open index.html
