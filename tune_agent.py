#!/usr/bin/env python3
"""The Tune in helper. Runs on an always-on Mac on the same network as the Apple TVs.

Waits on the Movie Loft server for Tune in requests from the guide, drives the
chosen Apple TV with tunein.py, and reports back. It only ever makes outbound
requests — nothing on the home network is exposed (decided Oct 2026; Tailscale
would need a VPN on every phone, which isn't always possible).

    .venv-atv/bin/python tune_agent.py

Config:
  ~/.movieloft-agent-token   the shared secret (chmod 600; same value as
                             AGENT_TOKEN on the server)
  movieloft.toml             rooms (key → Apple TV name) and the server's url
  MOVIELOFT_URL              overrides the url
Started at login by a LaunchAgent (`make helper-install`, from
launchd/movieloft-tuner.plist.in); logs to ~/Library/Logs/movieloft-tuner.log.
"""
import asyncio, os, time, traceback
from pathlib import Path

import aiohttp

from app import instance
from tunein import TuneError, tune

CONFIG = instance.load()
BASE = (os.environ.get("MOVIELOFT_URL") or CONFIG["url"]).rstrip("/")
if not BASE:
    raise SystemExit("No server address: set url in movieloft.toml (or MOVIELOFT_URL)")
TOKEN = (Path.home() / ".movieloft-agent-token").read_text().strip()
ROOMS = {r["key"]: r["apple_tv"] for r in CONFIG["rooms"]}
HEAD = {"X-Agent-Token": TOKEN}


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


async def handle(session, job):
    # Confirm first: an unconfirmed claim goes back in the queue after ~5s.
    async with session.post(f"{BASE}/agent/ack", headers=HEAD, json={"id": job["id"]}) as r:
        r.raise_for_status()
        if not (await r.json()).get("ok"):
            log(f"#{job['id']} lapsed before I confirmed it; skipping")
            return
    name = ROOMS.get(job["room"])
    if not name:
        log(f"#{job['id']} is for room {job['room']!r}, which isn't in movieloft.toml")
        async with session.post(f"{BASE}/agent/result", headers=HEAD, json={
                "id": job["id"], "status": "failed",
                "message": "That room isn't set up on the Mac (movieloft.toml)"}) as r:
            r.raise_for_status()
        return
    log(f"#{job['id']} {job['title']!r} → {name} at {job['position']}s")
    target = None
    if job["position"] is not None and job.get("from_start"):
        target = lambda: job["position"]         # "From the beginning": exactly there
    elif job["position"] is not None:
        # Where the program is NOW: its position at the tap, plus the time
        # since. Asked at the moment of the jump, so tuning time is covered.
        target = lambda: job["position"] + (time.time() - job["requested_at"])
    try:
        result = await asyncio.wait_for(tune(name, job["link"], target, job["title"], log=log), timeout=150)
        status, msg = "done", result
    except TuneError as e:
        status, msg = "failed", str(e)
    except asyncio.TimeoutError:
        status, msg = "failed", "The Apple TV took too long to respond"
    except Exception as e:                       # report it rather than die
        traceback.print_exc()
        status, msg = "failed", f"Something went wrong: {e}"
    log(f"#{job['id']} {status}: {msg}")
    async with session.post(f"{BASE}/agent/result", headers=HEAD,
                            json={"id": job["id"], "status": status, "message": msg}) as r:
        r.raise_for_status()


async def main():
    log(f"tune-in helper started, talking to {BASE}")
    timeout = aiohttp.ClientTimeout(total=40)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            try:
                async with session.get(f"{BASE}/agent/next", headers=HEAD) as r:
                    if r.status == 204:
                        continue                 # nothing in ~25s; ask again
                    if r.status == 401:
                        log("The server rejected the token — check ~/.movieloft-agent-token against its AGENT_TOKEN")
                        await asyncio.sleep(60)
                        continue
                    r.raise_for_status()
                    job = await r.json()
                await handle(session, job)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                log(f"network hiccup ({type(e).__name__}); retrying in 5s")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
