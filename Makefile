# After buying a movie, just run `make`. It pulls new purchases from the Apple TV
# app, rebuilds the page, commits + pushes the purchase record, and opens the
# page. The other targets are for development.
.PHONY: help update export export-tv tv-art apple-ids episode-ids helper-install helper-restart helper-log build build-tv build-guide check check-tv test years open clean

update:                  ## the only command you need — export, rebuild, commit, push, open
	@./update.sh

export:                  ## pull movies.tsv + new cover art out of the Apple TV app
	osascript export.applescript "$(CURDIR)"

export-tv:               ## pull episodes.tsv + new show covers out of the Apple TV app
	osascript export-tv.applescript "$(CURDIR)"

build:                   ## regenerate index.html and update library-state.json
	python3 build.py

tv-art:                  ## fetch TMDB posters for shows not looked up yet (needs .tmdb.key)
	python3 fetch_tv_art.py

apple-ids:               ## look up Apple TV IDs (Wikidata) for titles not yet known
	python3 fetch_apple_ids.py

episode-ids:             ## look up each episode's Apple TV ID (tv.apple.com's episode list)
	python3 fetch_episode_ids.py

build-tv:                ## regenerate tv.html from episodes.tsv
	python3 build_tv.py

build-guide:             ## regenerate guide.html (after build + build-tv)
	python3 build_guide.py

check-tv:                ## per-show episode/extras counts, nothing written
	python3 build_tv.py --check

check:                   ## show the diff without writing anything
	python3 build.py --check

test:                    ## goldens + guide scheduler rules + tune-in queue
	python3 tests/golden_test.py
	node tests/guide_test.mjs "$$(python3 tests/guide_fixture.py)" "guide (made-up library)"
	@if [ -f guide.html ]; then node tests/guide_test.mjs guide.html "guide (your library)"; fi
	@if [ -x .venv/bin/python ]; then .venv/bin/python tests/tune_test.py; \
	 else echo "tune: skipped (needs the server's packages: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)"; fi

# ---- Tune in helper (an always-on Mac; see README, Level 4)
HELPER_LABEL ?= local.movieloft.tuner
HELPER_PLIST := $(HOME)/Library/LaunchAgents/$(HELPER_LABEL).plist
HELPER_LOG   := $(HOME)/Library/Logs/movieloft-tuner.log

helper-install:          ## install + start the Tune in helper as a LaunchAgent (runs at login)
	@test -x .venv-atv/bin/python || { echo "✗ No .venv-atv yet — see README, Level 4, step 1"; exit 1; }
	@test -f $(HOME)/.movieloft-agent-token || { echo "✗ No ~/.movieloft-agent-token — see README, Level 4"; exit 1; }
	@mkdir -p $(HOME)/Library/LaunchAgents
	sed -e 's|__LABEL__|$(HELPER_LABEL)|' -e 's|__REPO__|$(CURDIR)|g' -e 's|__LOG__|$(HELPER_LOG)|g' \
	    launchd/movieloft-tuner.plist.in > $(HELPER_PLIST)
	-launchctl bootout gui/$$(id -u) $(HELPER_PLIST) 2>/dev/null
	launchctl bootstrap gui/$$(id -u) $(HELPER_PLIST)
	@echo "✓ Helper installed. Watch it with: make helper-log"

helper-restart:          ## restart the helper (after changing movieloft.toml or the code)
	launchctl kickstart -k gui/$$(id -u)/$(HELPER_LABEL)

helper-log:              ## follow the helper's log
	tail -f $(HELPER_LOG)

years:                   ## refresh theatrical years from TMDB (needs .tmdb.key)
	python3 lookup_years.py

open: build              ## rebuild and open the page in your browser
	open index.html

clean:
	rm -f index.html tv.html guide.html

help:                    ## list every command
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:[^#]*## /\t/' | expand -t 18
