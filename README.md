# Movie Loft

**Your Apple TV library, with a channel guide.**

Movie Loft reads the movies and TV shows you own in the Apple TV app and turns
them into:

- **Library pages:** every movie and show as a wall of covers, with franchises
  grouped in release order, real theatrical years, cleaned-up seasons, search,
  and "Surprise me."
- **A channel guide:** a cable-style lineup programmed from your own library
  (around 18 channels by default, more if you add HBO2-style copies), the same
  on every device, with On Now and Grid views.
- **Tune in:** tap a program, pick a room, and that Apple TV opens the movie
  or exact episode at the minute the "broadcast" has reached, then waits
  paused for you to press Play.
- **Comfort picks:** ♥ the titles you'd watch any night; filter to them, and
  they get their own channels.

There's a longer product description in [`docs/about.md`](docs/about.md).

> **Built with AI.** Movie Loft was built with
> [Claude Code](https://claude.com/claude-code), Anthropic's AI coding tool,
> which wrote essentially all of the code and documentation here. Jason Nassi
> supplied the idea and the decisions, and tested it on real Apple TVs.
> `CLAUDE.md` is the working notes Claude keeps for itself in this repo.

> **Status:** a personal project that started as one library in one house,
> since generalized so anyone can run it. It works, but expect some setup
> (the levels below) and the occasional rough edge.

---

## How it fits together

```
 Mac with the Apple TV app                    Railway (or any Docker host)
 ─────────────────────────                    ────────────────────────────
 export*.applescript ─► movies.tsv,           app/ (FastAPI)
                        episodes.tsv, art/      ├─ serves the built pages
 fetch_*.py ─► posters, years, Apple TV IDs     ├─ Google sign-in
 build*.py  ─► index.html, tv.html,             ├─ Comfort tags (Postgres)
               guide.html                       └─ Tune in queue (Postgres)
 update.sh (`make`) ─► git commit + push ─────►  deploys on push
                                                     ▲
 tune_agent.py (helper, always on) ── long-polls ────┘  (outbound only)
   └─ tunein.py ─► your Apple TVs (pyatv, home network)
```

- **The catalog lives in git**, not in a database. `make` exports from the
  Apple TV app, rebuilds the pages, and commits them, and the push is the
  deploy.
- **The browser does the scheduling.** The guide's lineup is computed in the
  page from the channel name and the date, so it's identical everywhere with
  no server involved.
- **Nothing at home is exposed.** The Tune in helper on the Mac only makes
  outbound requests to the web server; it never listens for connections.
- **No VPN option.** Tune in always goes through the hosted server. Movie Loft
  doesn't support the other common setup, where your phone joins your home
  network over a VPN (Tailscale, WireGuard, and the like) and talks to the Mac
  directly. That's deliberate: my phone is managed by my employer, so a VPN
  back home isn't an option for me, and I can't build or test it. If you'd
  like to add it, contributions are welcome.

## Requirements

| For | You need |
|---|---|
| Everything | A **Mac** with the **Apple TV app**, signed in to the account that owns your library |
| `make`, `git` | Apple's **Command Line Tools**: run `xcode-select --install` once |
| The build scripts | **Python 3.11 or newer**. The Python that ships with the Command Line Tools is older; get a current one with [Homebrew](https://brew.sh) (`brew install python`) |
| Posters, theatrical years | A free **TMDB** API key ([themoviedb.org](https://www.themoviedb.org/) → Settings → API) |
| Private hosting | **Railway** (or any Docker host + Postgres) and a **Google Cloud** OAuth client |
| Tune in | One or more **Apple TVs** on the same network as an always-on Mac; **Python 3.12** for [pyatv](https://pyatv.dev), which [uv](https://docs.astral.sh/uv/) installs for you (`brew install uv`) |
| Tests | **Node** (`brew install node`); the Tune in queue test also needs the server's packages (see Level 3, *Local server*) |

## Setup

Each level builds on the one before, and you can stop at any level.

### Level 0: your own private copy

**Keep your copy private.** Once you run Movie Loft, your repo holds your
whole library (every title you own, with cover art), and that's yours, not
the internet's. So don't fork this repo on GitHub: forks of a public repo
are public.

Instead, click **Use this template → Create a new repository** on GitHub and
choose **Private**. Then clone your new repo:

```sh
git clone git@github.com:<you>/<your-repo>.git movie-loft && cd movie-loft
```

**Link it to this repo right away, before you change anything**, so you can
pick up later improvements to Movie Loft. A copy made from a template starts
its own history, so this one-time merge tells git the two share a starting
point (`-s ours` keeps your files exactly as they are):

```sh
git remote add upstream https://github.com/jnassi/movie-loft.git
git fetch upstream
git merge -s ours --allow-unrelated-histories upstream/main -m "Link to upstream Movie Loft"
```

After that, updating is:

```sh
git fetch upstream && git merge upstream/main
```

Use `merge`, not `git pull`: if your git is set to rebase on pull, a pull
tries to replay your whole history on top of this repo and stops on
conflicts. (If that happens, `git rebase --abort` puts everything back.)
Your library files never conflict with updates, because this repo doesn't
contain any.

Then make your two settings files from the examples and commit them. Both are
commented, and you can edit them any time:

```sh
cp movieloft.example.toml movieloft.toml        # your server, rooms, a loop channel
cp corrections.example.toml corrections.toml    # fixes and channel rules for your library
git add movieloft.toml corrections.toml && git commit -m "My settings"
```

### Level 1: library pages on your Mac

```sh
echo "<your TMDB v3 key>" > .tmdb.key        # optional, gitignored
```

Open the Apple TV app, then run the steps below. **The first export makes
macOS ask whether Terminal may control the Apple TV app: click OK.** If you
miss it or click Don't Allow, turn it on in System Settings → Privacy &
Security → Automation.

```sh
make export export-tv     # read the library: movies.tsv, episodes.tsv, art/, art-tv/
make years tv-art         # theatrical years and show posters from TMDB (needs the key)
make build build-tv       # index.html (movies) and tv.html (TV shows)
open index.html
```

The pages are static files and work straight off the filesystem.

**`make` is just a list of shortcuts.** Each `make <name>` runs one step
defined in the `Makefile`, and `make help` lists them all. Plain `make`, with
no name, runs the whole update at once (Level 3).

**The first export takes a while** (it saves every cover). After that it only
fetches what's new.

### Level 2: the channel guide

```sh
make apple-ids episode-ids   # Apple TV links, for Tune in later (optional)
make build-guide             # guide.html
open guide.html
```

Channels are defined in `build_guide.py`. By default you get one of each;
to run extra copies of the busy formats, cable style (HBO, HBO2, HBO3), set
`copies` under `[guide]` in `corrections.toml`. See
[Making it yours](#making-it-yours).

### Level 3: private hosting with sign-in

The repo includes a `Dockerfile` and `railway.toml`. These steps use
[Railway](https://railway.com); other hosts work too (see
[Hosting somewhere else](#hosting-somewhere-else)).

**First, run `make` once** (see step 4) so your built pages, art, and settings
are committed. The server is built from your repo, and the build fails
without them.

1. **Google OAuth client.** In Google Cloud Console, create a project and set
   up the OAuth consent screen (External, **Testing** mode, add yourself as a
   test user). Then go to Credentials → Create OAuth client ID → Web
   application, with the redirect URI `https://<your host>/auth/callback`.
2. **Railway.** Create a project from your private repo, add a **Postgres**
   database, and set these variables on the web service:

   | Variable | Value |
   |---|---|
   | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | from step 1 |
   | `ALLOWED_EMAILS` | comma-separated Google accounts allowed in |
   | `SESSION_SECRET` | any long random string |
   | `PUBLIC_URL` | `https://<your host>`, which must match the redirect URI |
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
   | `AGENT_TOKEN` | a long random string (Level 4 uses it) |

   Generate random strings with
   `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
3. **Custom domain (optional).** Add it under the service's Settings →
   Networking, and create the CNAME and TXT records Railway shows at your DNS
   host. Then add the new redirect URI to the OAuth client *before* changing
   `PUBLIC_URL`, so sign-in never breaks in between.
4. **Update with one command.** From now on, after buying something:

   ```sh
   make
   ```

   That runs `update.sh`: export, look up anything new, rebuild every page,
   commit, and push. Railway deploys in a minute or two. If nothing changed,
   it says so and commits nothing.

To let someone else in, add them as a test user on the OAuth consent screen
**and** to `ALLOWED_EMAILS`.

**Local server:** `python3 -m venv .venv && .venv/bin/pip install -r
requirements.txt`, then `DEV_NO_AUTH=1 .venv/bin/uvicorn app.main:app` serves
at localhost:8000 with no sign-in and in-memory storage. The server refuses to
start with `DEV_NO_AUTH` once it's deployed (an `https` `PUBLIC_URL`).

#### Hosting somewhere else

Railway isn't required. The server needs four things from any host:

- **Run a Docker container** from the repo's `Dockerfile`, passing the port
  in `PORT` (defaults to 8000).
- **Postgres**, with its connection string in `DATABASE_URL`. Without one the
  server still runs, but comfort picks are lost on every restart.
- **A public `https` address**, set as `PUBLIC_URL`. Google sign-in requires
  `https`, and an `https` `PUBLIC_URL` is also how the server knows it's
  deployed: it then insists on a real `SESSION_SECRET`, marks cookies
  secure, and refuses `DEV_NO_AUTH`.
- **A way to redeploy** when you push, or a deploy command you run after
  `make`.

Fly.io, Render, or your own server running Docker all fit. Railway-specific
bits: `railway.toml` (its health check), and the `${{Postgres.DATABASE_URL}}`
shorthand in the variables table; elsewhere, paste the real connection string.

### Level 4: Tune in

The helper runs on an always-on Mac on the same network as your Apple TVs.

1. **Python environment for pyatv** (it needs 3.12):

   ```sh
   uv venv --python 3.12 .venv-atv
   uv pip install --python .venv-atv pyatv aiohttp
   ```

2. **Pair each Apple TV**, twice: once for Companion (opening links, buttons)
   and once for AirPlay (playback position and seeking). Keep the TV awake;
   the PIN appears on screen and expires fast.

   ```sh
   .venv-atv/bin/atvremote scan
   .venv-atv/bin/atvremote -n "<Apple TV name>" --protocol companion pair
   .venv-atv/bin/atvremote -n "<Apple TV name>" --protocol airplay pair
   ```

   Credentials are saved in `~/.pyatv.conf`.
3. **Test one tune** with a movie ID from `apple-ids.json`. It should open the
   movie, jump to 10:00, and pause:

   ```sh
   .venv-atv/bin/python tunein.py "<Apple TV name>" \
     "https://tv.apple.com/us/movie/<slug>/umc.cmc.<id>" 600 "<Movie title>"
   ```

4. **Configure your rooms.** In `movieloft.toml` (from Level 0), set `url` to
   your server's address and add a `[[rooms]]` block for each Apple TV, with
   `apple_tv` exactly as `atvremote scan` names it. Then run `make`, which
   rebuilds the guide with the room buttons and commits and pushes, since the
   server reads the file too. Put the same value as your server's
   `AGENT_TOKEN` in `~/.movieloft-agent-token` (`chmod 600`).
5. **Run it at login:**

   ```sh
   make helper-install     # installs and starts it as a LaunchAgent
   make helper-log         # watch it; Ctrl-C to stop watching
   ```

   After changing `movieloft.toml` or updating the code, run
   `make helper-restart`.

6. **Allow Local Network access.** Under launchd, the helper's Python needs
   System Settings → Privacy & Security → Local Network turned on. Without
   it, the helper can't find any Apple TV, even though the same command works
   from Terminal.

**After a restart**, the helper runs only once someone logs in. If FileVault
is on (it usually is), auto-login isn't available, so for a planned restart
use `sudo fdesetup authrestart`, which comes back up logged in.

## Making it yours

| What | Where |
|---|---|
| **Series groupings, director fixes, year overrides** | `corrections.toml`: `[series]` rules (regex `match`, `also`, `never`), `[directors]`, `[years]` |
| **Wrong TV poster** | `[tv_art]` in `corrections.toml` (a TMDB show ID; 0 keeps the episode frame) |
| **Missing Apple TV link** | `[apple_tv]` in `corrections.toml`: paste the tv.apple.com link. A web search limited to tv.apple.com finds it; the Apple TV app has no Copy Link |
| **Streamed shows you don't own** | `[streaming] shows` in `corrections.toml` |
| **Which shows air** | `[guide] min_episodes` and `keep_shows` in `corrections.toml` |
| **Channels** | `build_guide.py`: one `add(...)` per channel; mixed film-and-show channels go under `[channel."Name"]` in `corrections.toml` |
| **Rooms, server address, a loop channel** | `movieloft.toml` (copy `movieloft.example.toml`): `url`, one `[[rooms]]` per Apple TV, and an optional `[loop]` channel that plays one movie all day |
| **How many channels** | `[guide] copies` in `corrections.toml` (extra copies of Movie Roulette, Marathon, The Half Hour, The Hour, Channel Surf), or per format under `[guide.channel_copies]`; 0 turns one off |

`make check` and `make check-tv` report what changed and what looks wrong
(series rules that match nothing, possible new series, per-show episode
counts) without writing anything.

## Commands

| Command | Does |
|---|---|
| `make` | The whole update: export, look up, rebuild, commit, push |
| `make export` / `export-tv` | Read movies / episodes and covers from the Apple TV app |
| `make years` | Refresh theatrical years from TMDB |
| `make tv-art` | TMDB posters for shows not looked up yet |
| `make apple-ids` / `episode-ids` | Apple TV links for movies and shows / for episodes |
| `make build` / `build-tv` / `build-guide` | Rebuild one page |
| `make check` / `check-tv` | What changed, what looks off; writes nothing |
| `make help` | List every command |
| `make test` | Golden tests, guide rules, Tune in queue |
| `make helper-install` / `helper-restart` / `helper-log` | Install, restart, or watch the Tune in helper |

## Repo map

```
export.applescript, export-tv.applescript   read the Apple TV app
build.py, build_tv.py, build_guide.py       build index.html, tv.html, guide.html
template*.html                              page templates (shared CSS in template.html)
lookup_years.py                             TMDB theatrical years → theatrical.json
fetch_tv_art.py                             TMDB show posters → art-tv/, tv-art.json
fetch_streaming.py                          streamed shows from TMDB → streaming.json
fetch_apple_ids.py                          Apple TV movie/show IDs (Wikidata) → apple-ids.json
fetch_episode_ids.py                        Apple TV episode IDs (tv.apple.com) → episode-ids.json
corrections.example.toml → corrections.toml  fixes and channel rules for your library
movieloft.example.toml → movieloft.toml      your instance: server url, rooms, loop channel
app/instance.py                             reads movieloft.toml
update.sh                                   what `make` runs
app/                                        web server: pages, sign-in, tags, Tune in queue
tune_agent.py, tunein.py                    Tune in helper and the Apple TV driver
launchd/                                    LaunchAgent template for the helper
tests/                                      fixture library, goldens, guide and queue tests
docs/about.md                               product description
```

## Tests

```sh
make test
```

- **Golden tests** build a hand-made fixture library (`tests/fixture/`), full
  of the Apple TV app's quirks, and compare the output to checked-in goldens.
  When you change the build on purpose, run
  `python3 tests/golden_test.py --update` and review the diff.
- **Guide test** (`tests/guide_test.mjs`) runs the guide's own scheduler over
  ten days, including both daylight-saving changes, and checks its rules: no
  overlaps, :00/:30 starts, nothing past 6 AM, nothing on two channels at
  once. It runs on a guide built from a made-up library
  (`tests/guide_fixture.py`), so it works in a fresh clone, and on your real
  `guide.html` too once you have one.
- **Queue test** (`tests/tune_test.py`) drives the server's Tune in queue
  in-process: claiming, confirming, requeueing, expiring.

## Data sources and caveats

- **The Apple TV app**, via AppleScript (the old iTunes scripting dictionary).
- **TMDB** for theatrical years, show posters, and streamed shows' episodes.
  *This product uses the TMDB API but is not endorsed or certified by TMDB.*
  The attribution in the page footers is required by TMDB's terms.
- **Wikidata** for Apple TV movie and show IDs, matched on TMDB IDs.
- **tv.apple.com**'s own episode list for episode IDs. It's undocumented and
  could change; when it breaks, episodes fall back to opening the show's page.
- **pyatv** to control Apple TVs. Apple TV seeking is finicky; `tunein.py`
  documents the sequence that works and why.
- US storefront throughout.

`CLAUDE.md` has the detailed notes: quirks, decisions, and the reasons behind
them.

## License

[MIT](LICENSE): use it, change it, share it; keep the copyright notice. The
license covers Movie Loft's code and writing. The movie and TV artwork in the
screenshots under `docs/images/` belongs to its respective studios and isn't
covered by it.
