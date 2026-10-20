# CLAUDE.md

Guidance for Claude Code working in this repo. **README.md** covers what Movie
Loft is and how to set it up; this file is the context that isn't obvious from
the code: quirks, invariants, and decisions, mostly things that cost time to
work out the first time.

**If `INSTANCE.md` exists, read it too.** It describes this particular
installation (its host, rooms, machines, and the owner's preferences) and
lives only in the owner's private copy, never in the public repo.

**Public repo vs. private copy.** The public repo (`jnassi/movie-loft`) is
code, docs, example settings, and a test library: **never library data,
cover art, `movieloft.toml`, `corrections.toml`, `INSTANCE.md`, or anything
about a particular household** (names, emails, home paths, device names,
domains). Each owner runs a private copy (made from the template) that adds
those and deploys from them; there, committing data is normal. Code changes
go into the public repo first; a private copy takes them with
`git fetch upstream && git merge upstream/main`. **Never `git pull` across
the two**: with `pull.rebase` on, it tries to rebase the whole private
history onto the public one (`git rebase --abort` undoes it).

**Naming:** the project is **Movie Loft**. Apple's app is always **"the Apple
TV app"**, never "the TV app", so the two can't be confused. The AppleScript
target is still `tell application "TV"`.

---

## Invariants: don't break these

- **The build never fails or hangs on the network.** TMDB, Wikidata, and
  tv.apple.com lookups are best-effort: capped, short timeouts, single try,
  and on any failure the build carries on with what it has. Keep that
  guarantee in anything you add.
- **Read TSVs with `.split("\n")`, never `splitlines()`.** A title carried
  U+0085, which `splitlines()` treats as a line break: the row split in two,
  an episode vanished, and a fake show named `"` appeared. `build_tv.py` also
  maps U+0085 to "…". The fixture has a row with it.
- **Art filenames:** `art/<raw title with ":" and "/" replaced by "_">.jpg`.
  The export and the page's `artPath()`/`safe()` both do this swap; change
  one, change both.
- **Keep `raw` titles unstripped.** One has a trailing space; `raw` is the art
  filename and the tag key. Strip only for lookups.
- **The catalog is files in git, and a push to `main` is the deploy.** `make`
  commits what it regenerates plus `corrections.toml` and `movieloft.toml`
  (only files that exist; a change to either one is enough to trigger a
  commit) and pushes if there's a remote.
- **TMDB attribution in the page footers is required by TMDB's terms.** Don't
  remove it.
- **`template.html` holds the shared CSS** (`__BASE_CSS__` is filled from it
  in the TV and guide pages). Editing it means rebuilding and committing all
  three pages. Templates use `__WORD__` placeholders, so never put a literal
  `__WORD__` in a template unless it's meant to be substituted.
- **Pages must work from `file://`** as well as from the server: relative
  paths (`art/…`, not `/art/…`), no `localStorage` dependence.
- **Run `make test` after touching a build script, the scheduler, or the
  tune queue.** When a golden changes on purpose, run
  `python3 tests/golden_test.py --update` and review the diff.
- **Secrets never go in the repo:** `.tmdb.key` (gitignored),
  `~/.movieloft-agent-token`, `~/.pyatv.conf`, and the server's environment variables.
  Don't print them in output either.

## Setting up a new instance

Follow README.md's four levels in order; each one works before the next
starts. Things that trip people up:

- **The export drives the Apple TV app** (`tell application "TV"`), which
  must be signed in to the library's account. If the export fails, `update.sh`
  stops before touching anything. The first export triggers
  macOS's Automation prompt (Terminal → "TV"); if it was denied, it's in
  System Settings → Privacy & Security → Automation.
- **The Docker build needs the built pages, `art/`, `art-tv/`, and
  `movieloft.toml` committed**, so run `make` before the first deploy.
- **"Deployed" means an `https` `PUBLIC_URL`** (or Railway's
  `RAILWAY_ENVIRONMENT`), not a particular host: deployed requires
  `SESSION_SECRET`, sets Secure cookies, and refuses `DEV_NO_AUTH`. Any
  Docker + Postgres host works; `railway.toml` is Railway's health check.
- **Pairing PINs expire fast**, and the TV must be awake when pairing starts.
  If you're relaying a PIN for the user, start `atvremote … pair` in the
  background reading from a FIFO, and write the PIN to it the moment they
  read it off the screen. Each Apple TV needs **two** pairings: `companion`
  and `airplay`.
- **Local Network permission:** under launchd, the helper's Python needs
  System Settings → Privacy & Security → Local Network, or every scan comes up
  empty ("Couldn't find the … Apple TV") even though Terminal works.
- **OAuth host changes:** add the new redirect URI to the Google client
  first, then change `PUBLIC_URL`. They must name the same host.
- **Instance settings live in `movieloft.toml`** (from
  `movieloft.example.toml`; read by `app/instance.py`): `url`, `[[rooms]]`
  (key, label, apple_tv), optional `[loop]`. The server validates rooms
  against it (the Dockerfile copies it), the helper maps room → Apple TV
  name, and `build_guide.py` embeds the room buttons (`__ROOMS__`) and the
  loop channel. Changing rooms = edit, `make`, then `make helper-restart`.
  Locally, no file = no rooms ("This device" only) and no loop; the Docker
  build requires it. Keep household specifics out of the code; they belong
  here.
- **`corrections.toml` is optional** everywhere (every reader treats a missing
  file as empty); `corrections.example.toml` documents each section.
- **`.dockerignore` excludes `*.toml`** (so `corrections.toml` stays out of
  the image) with a `!movieloft.toml` exception. Without that exception the
  server boots with no rooms and refuses every room tune-in (it happened
  once). A new file the server needs must get past `.dockerignore` too;
  check inside the container (on Railway, `railway ssh -- ls /srv`), not
  just that the build succeeded.
- **The helper runs as a LaunchAgent** from `launchd/movieloft-tuner.plist.in`:
  `make helper-install` fills in the paths and loads it, `make
  helper-restart` after config or code changes, `make helper-log` to watch.
  The label defaults to `local.movieloft.tuner` (`HELPER_LABEL=` overrides).
- **Don't promise the Apple TV app has a Share → Copy Link.** It doesn't. To
  find a missing tv.apple.com link, web-search limited to tv.apple.com;
  tv.apple.com's own search renders with JavaScript, so scripts see only
  recommendations.
- **Apple's iTunes Search API no longer returns movies** (2026). TV seasons
  still work. Don't build on it for movies.

## The Apple TV app's AppleScript dictionary

The app inherits the old iTunes dictionary, trimmed over the years. Verify
before assuming:

```
osascript -e 'tell application "TV" to get properties of track 1 of library playlist 1'
```

- **`media kind`** separates films from episodes (values `movie`,
  `TV show`). There's no `video kind`; guessing it throws `Expected “,” but
  found property. (-2741)`.
- `year` and `release date` are both the store's stamp, and a reissue pushes
  both forward, so neither gives the theatrical year (TMDB does).
  `release date` comes back as a date object; format it yourself and guard
  `missing value`.
- **Ask for a property of a whole query, not of a saved variable.**
  `name of (every track of library playlist 1 whose media kind is movie)`
  works; saving the query to a variable and asking `name of t` fails with
  `Can't get name of {shared track id …}` (-1728). Per-track loops work but
  cost one Apple event per property per title.
- Cover art is `raw data of artwork 1 of <track>`. It errors when there's no
  cached art, so wrap it in `try`. Some are PNG despite `.jpg`; browsers
  sniff the content.
- `export.applescript` writes `movies.tsv`: raw title, year, director,
  release date (unused now), running time in seconds.

## Movies: data quirks and how the build decides

- **Edition suffixes** (`(Unrated)`, `(Extended Version)`, `[2003]`,
  `: The Unrated Version`) are split into a badge by `split_title()`. A
  trailing `(1994)` is a year and is dropped.
- **Duplicates collapse only on identical raw title.** Keying on the derived
  (title, edition, year) made a film vanishable: an untagged remake whose year
  TMDB pulled onto another film's merged and disappeared. Rows that share
  (title, edition, year) but differ in raw title stay separate and print as a
  **collision** under `--check`. Which duplicate survives is deterministic
  (earliest year, then the fuller row, then director; `_survivor`), not export
  order, because the Apple TV app's ordering is unstable.
- **Year precedence, highest first:** a `[years]` entry → an explicit
  `(YYYY)` in the title → TMDB's theatrical year *if it isn't later than the
  store year* → the store year. The `(YYYY)` step is the **remake guard**:
  without it, TMDB pulls `Ghostbusters (2016)` back to 1984 and it collapses
  into the original. A TMDB year *later* than the store year means TMDB
  matched the wrong film.
- **Reissue badge:** store year 2+ years after the theatrical year → "1990
  (reissue 2015)".
- **The build fills `theatrical.json` gaps on its own** when a TMDB key is
  present (capped by `GAP_CAP`, skipped under `--check`), so a new purchase
  gets its real year from a plain `make`. `make years` refreshes everything.
- **`[series]` is rules, not member lists:** `match` (case-insensitive
  regexes against the cleaned title), `also` (exact titles to pull in),
  `never` (exact titles to keep out). `never` beats `also` beats `match`;
  the first series in file order wins; a series needs 2+ present films. A bad
  regex fails at load with the series name. `--check` reports rules that match
  nothing, titles matching more than one series, and ungrouped films sharing a
  leading phrase.
- **"Recent imports" is the newest `firstSeen` batch** from
  `library-state.json`, not the per-build delta (that was true for only one
  build, which broke "Show only these").
- The `--check` suspect-year heuristic is source-free (reissue wording plus a
  same-director duplicate dated 4+ years earlier). It can miss a mis-dated
  reissue with neither tell.

## Page conventions

- Every movie card is the same shape: banner row, 16:9 art, two-line title,
  one-line director, so rows align. Films outside a series still render the
  banner row, hidden. **Don't reintroduce per-series containers**; their
  padding knocked everything out of line.
- Portrait art gets `object-fit: contain` so titles on posters aren't cropped.
- **"Surprise me" reuses the card:** `cardInner(f)` and `loadPoster(art)`
  serve both the grid and the modal. Don't fork them.
- Without `art/`, posters fall back to the iTunes Search API over JSONP.

## TV shows

`export-tv.applescript` → `episodes.tsv` (show, season, episode, title,
seconds, store year) plus one cover per show in `art-tv/`. `build_tv.py` →
`tv.html` and `catalog-shows.json`. The TV export is best-effort: a TV failure
never blocks a movie update.

The episode data is far messier than the movie data, and almost all of
`build_tv.py` is cleanup:

- **Complete-series purchases put every row in season 0** and hide the real
  numbers in the title: `Season 2, Episode 11: The Chinese Restaurant`. The
  spelling varies wildly (`Episode11:`, `Season 4: Episode 20:`, `Season 6A`,
  `Episode 17/18`, `The Final Season, Episode 1:`), so `TITLED` is
  deliberately loose.
- **Bonus material is mixed in with episodes** (trailers, featurettes,
  full-length commentaries). It's filtered by wording (`EXTRA`), by the
  store's 101+ bonus numbering, and by length (under half the show's median
  episode). Extras are counted, never shown as episodes, never scheduled.
- **Single-season purchases number clips as episodes**, so numbered rows are
  renumbered 1..n per season after clips go.
- **Seasons bought twice:** keep the copy with more episodes (ties go to the
  titled copy). **Don't merge copies by episode number**: Mad Men S6 is one
  2-hour "The Doorway" in one copy and Pt. 1 / Pt. 2 in the other.
- **"The Final Season"** has no number; it's matched by title overlap to a
  numbered season, else it's last + 1.
- **Unnumbered long items** count as episodes only when a show has no
  numbered episodes at all; otherwise they're specials, filed as extras.
- `make check-tv` (add `--episodes` for the full listing) prints per-show
  counts. Sanity-check against real-world counts after touching a rule
  (Breaking Bad 62, Mad Men 92, Sopranos 86, Fringe 100, Game of Thrones 73).
  `tests/fixture/episodes.tsv` catalogs every quirk; add a row for each new
  one.

**Posters:** `fetch_tv_art.py` swaps the episode-frame cover for the TMDB
poster and records matches in `tv-art.json`. Same-named shows are picked by
the library's tags: "(Reboot)" = newest, "(Original)" = oldest, "(2001)" =
closest year. Pin under `[tv_art]` (0 = keep the frame). The iTunes Search
API was tried first and dropped; it's missing whole shows.

**Streamed shows:** Apple TV+ shows the user streams but doesn't own aren't
library items, so `[streaming] shows` lists them; `fetch_streaming.py` pulls
aired episodes and posters from TMDB into `streaming.json` (preferring the
Apple TV network when names clash), and `build_tv.py` merges them in with
`svc: "Apple TV+"`. An owned copy wins. They mix into every TV channel.

## Channel guide (guide.html)

`build_guide.py` decides each channel's **pool** from `catalog-movies.json`
and `catalog-shows.json` (gitignored intermediates) and embeds it in the page.
**The browser does the scheduling** (`template-guide.html`):

- **Seeded, not random:** each channel's day comes from
  `seeded(channel name|date)`, so every device shows the same lineup.
  **Renaming a channel reshuffles it** ("Marathon 2" differs from "Marathon"
  only by name).
- **Broadcast day = 6 AM to 6 AM** (`nextDayStart`, not +24h: DST days are 23
  or 25 hours). Programs start on :00/:30. The last program must end by 6 AM;
  if nothing fits, the channel signs off with a test pattern, so each day is
  self-contained.
- **Nothing airs on two channels at once: a movie, or a show (any episode)**,
  via the per-day `airing` map; episodes are keyed by show (`s<idx>`).
- **Scheduling order:** Marathons → everything else → Comfort. Marathons
  don't yield mid-run (skipping an episode breaks it), but **a marathon checks
  its whole run against earlier marathons before starting it** (`run` and
  `next.reject()`; two Marathons once both aired the same show). Comfort
  channels go last, so tagging only ever reshuffles Comfort channels; their
  pools come from `/api/tags`. A `loop` channel is exempt from the
  one-channel rule both ways.
- **Channel kinds:** `movies`, `blocks` (franchise in order / director
  shuffled), `episodes` (pick a show, then an episode, so big shows don't
  swamp small ones), `epref` (shared episode lists split by running time: The
  Half Hour / The Hour; the Apple TV app's genre field isn't used),
  `marathon`, `mixed` (films + episodes, defined under `[channel."Name"]` in
  corrections.toml with `movie_share`), `comfort-movies`, `comfort-shows`,
  `loop`. Adding a channel is one `add(...)`; any `[channel."Name"]` in
  corrections.toml becomes a mixed channel (Super Heroes and Starfleet keep
  their slots; others follow in file order, with an optional `blurb`). The
  build warns about series/show names that match nothing.
- **Hard-coded taste:** shows starting "Star Trek" stay off The Hour (they'd
  swamp it, and Starfleet covers them), in `build_guide.py`.
- Shared episode lists are embedded once in `REFS`, not per channel.
- **Channel copies are configurable:** `[guide] copies` (default 1) runs
  "Movie Roulette 2", "Marathon 3", etc. for the five busy formats;
  `[guide.channel_copies]` overrides one format, and 0 turns it off. Channel
  numbers are assigned in order, so changing copies renumbers what follows.
- **A channel with nothing to air is left out** at build time (a small
  library may have no show long enough for a Marathon), and the page's feeds
  return nothing for an empty pool as a backstop. An empty Marathon pool used
  to crash the scheduler.
- **Short shows sit out:** fewer than `[guide] min_episodes` episodes owned
  (mostly one-off purchases) means it never airs, except on Comfort TV if
  tagged. `keep_shows` overrides (e.g. a four-part miniseries).
- Movies need a running time (export column 5) to air.
- Episodes carry their Apple TV episode ID as a 5th field, minus the
  `umc.cmc.` prefix, which keeps the page around 500 KB. The server gzips.

## Apple TV IDs

- **Movies and shows:** `fetch_apple_ids.py` → `apple-ids.json`, from
  Wikidata via TMDB IDs (P4947 → P9586 for movies, P4983 → P9751 for shows).
  Misses get pinned under `[apple_tv]` with the tv.apple.com link; pins win.
- **Episodes:** `fetch_episode_ids.py` → `episode-ids.json`, from the
  undocumented episode list tv.apple.com's pages use
  (`/api/uts/v3/shows/<show id>/episodes?nextToken=<skip>:<count>`; the
  `utscf`/`utsk` keys are scraped fresh from a show page each run).
  **Matching is by title first**, because Apple numbers some shows
  differently (Star Trek pilots split in two shift whole seasons). Numbers
  break ties and decide alone only for placeholder titles ("Episode 3",
  "1801"); each Apple episode is used once (three passes: number + title,
  title, number for placeholders); digits in both titles must agree ("Part 1"
  ≠ "Part 2"). About 98% match; the rest open the show's page.
  `update.sh` runs it after `build_tv.py`, since it needs
  `catalog-shows.json`.
- Link formats: `https://tv.apple.com/us/movie/<slug>/<id>`,
  `…/us/show/<slug>/<id>`, `…/us/episode/<slug>/<id>?showId=<show id>`.

## Tune in

**Path of a tap:** guide → `POST /api/tune` (Postgres `tune_requests`) → the
helper (`tune_agent.py`, long-polling `/agent/next` with `AGENT_TOKEN`) →
`tunein.py` drives the Apple TV over pyatv → `/agent/result` → the phone
polls `/api/tune/{id}`. The helper only makes outbound requests.

- **Claims must be confirmed** (`/agent/ack`) within 5s or they go back in the
  queue. A long poll can outlive a restarted helper, and the "http"
  middleware hides disconnects from the handler; without the ack, a dead
  connection silently swallowed a request.
- Statuses: pending → claimed → working → done | failed; pending for over 60s
  → expired (so a request made while the helper was down never fires later).
- **The jump target is computed at the moment of the jump:** position at the
  tap plus seconds since. With **From the start** (`fromStart` →
  `tune_requests.from_start`), it's exactly `position` (0).
- **This device** opens the title in the Apple TV app locally and says where
  to start; those devices can't be remote-controlled. iPhone/iPad take the
  tv.apple.com link; **a Mac needs `com.apple.tv://tv.apple.com/…`** (a plain
  link opens the browser). iPadOS reports "MacIntel", so they're told apart by
  touch points.
- **The tune sequence** (`tunein.py`): power on → open link → Select (twice
  if the PLAY/EXTRAS menu appears) → wait for playback → ~1s → **jump while
  playing → play ~3s through the loading spinner → pause → read the PAUSED
  position → jump again if off**. It lands paused ~3s past the target; one
  Play resumes. Learned by probing with someone watching the screen: pausing
  during the post-jump spinner leaves a half-paused player, or a new frame
  with the playhead still at the old spot; a jump sent the instant playback
  starts is dropped; the position reported while PLAYING is stale, while
  PAUSED it's truthful; reported state lags commands. Several "pause first,
  then jump" variants failed. Don't go back to them.
- **Title check:** after tuning, the TV's now-playing title is compared to
  the expected one, so a wrong ID is reported, not silently wrong. **For an
  episode the TV reports the show's name** as the title, with no season or
  episode metadata, so the guide sends the show name. A wrong episode of the
  right show wouldn't be caught (`total_time` does match the episode, if
  that's ever needed).
- **Remembered addresses:** `~/.movieloft-atv-cache.json` (name → identifier
  and IP). Connecting unicast-scans the remembered IP (~0.5s) and only falls
  back to a full search (5s, then 8s) if the TV moved. Some Apple TVs take
  well over 5s to answer a full search.
- pyatv needs **Python 3.12** (`.venv-atv/`, gitignored). Pairings live in
  `~/.pyatv.conf`: Companion (open links, buttons) and AirPlay (now playing,
  seeking) per Apple TV. One connection per tune; each `atvremote` call costs
  seconds.

## Server (app/)

- FastAPI. Serves only the built pages (`/`, `/index.html`, `/tv.html`,
  `/guide.html`) and files directly inside `art/`, `art-tv/`, `icons/`, plus
  the favicon, touch icons, manifest, and `/health`. Everything else 404s.
  **Add a new public file to `PAGES`/`ART_DIRS`** or it won't be served.
- **Sign-in is Google OAuth**, limited to `ALLOWED_EMAILS`; keeping the
  Google client in Testing mode adds a second lock and skips app review.
  Only real pages are remembered as the post-login destination (background
  requests for the favicon used to overwrite it).
- `/agent/*` skips the sign-in gate and checks `X-Agent-Token` instead. Icons
  and the manifest are open, since browsers fetch them without cookies.
- **The database holds only the user's data about the catalog:** `tags`
  (Comfort, keyed by raw movie title or show name; a renamed title loses its
  tag) and `tune_requests`. Tables are created at startup; a new column is an
  `ALTER TABLE … ADD COLUMN IF NOT EXISTS` there.
- Without `DATABASE_URL`, an in-memory store mirrors the SQL rules (local dev
  and tests).
- `DEV_NO_AUTH=1` skips sign-in locally; the server refuses it when deployed
  and refuses to start deployed without `SESSION_SECRET`.
- `update.sh` refuses to push when `art/` or `art-tv/` is suspiciously thin
  (fewer files than half the titles or shows).

## Tests

- `tests/golden_test.py` builds the fixture library in a throwaway copy and
  diffs `index.html`, the `--check` report, and `build_tv.py --check
  --episodes` against `tests/golden/`. Reproducibility comes from two
  build.py hooks: `--root DIR` and `SOURCE_DATE_EPOCH`.
- `tests/guide_test.mjs` (Node) lifts the scheduler out of a built
  `guide.html`, so it tests exactly what ships, and runs `buildDay()` over ten
  days in America/Denver, both DST changes included: day boundaries, :00/:30
  starts, no overlaps, nothing past 6 AM, test pattern only as sign-off, no
  double-booking, determinism, and Comfort isolation. `make test` runs it on
  a guide built from a made-up library (`tests/guide_fixture.py`, so it works
  in a fresh clone) and on the real `guide.html` if there is one. `update.sh`
  runs it on the real one as a warning, not a gate.
- `tests/tune_test.py` (needs `.venv`) drives the app in-process with the
  in-memory store: validation, the state machine, requeue, expiry, ordering,
  long-poll wake, `fromStart`. The SQL itself isn't exercised.
