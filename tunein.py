#!/usr/bin/env python3
"""Tune an Apple TV to a title at a given minute — one connection, start to finish.

    .venv-atv/bin/python tunein.py "<Apple TV name>" <tv.apple.com link> <seconds> [title]

Used by tune_agent.py (the helper behind the guide's Tune in button) and
runnable on its own for testing. Needs pyatv (in .venv-atv — Python 3.12;
pyatv doesn't run on 3.14 yet) and the Companion + AirPlay pairings stored by
`atvremote pair` in ~/.pyatv.conf.

Sequence (tested on a 4K Apple TV, Oct 2026 — ~5.5s, no visible opening footage):
open the title's page, press Select (titles with extras open a PLAY / EXTRAS /
CAST & CREW menu first, so press again if it isn't playing), wait for playback
to actually start, then pause → jump, and leave it paused (the viewer presses Play
when ready). A partly watched title resumes
where it was left, not at 0:00 — the jump handles both. Each separate
connection costs seconds, which is why it's all one connection.
"""
import asyncio, json, re, sys, time
from pathlib import Path

import pyatv
from pyatv.const import DeviceState
from pyatv.storage.file_storage import FileStorage


class TuneError(Exception):
    """A failure worth showing on the phone, in plain words."""


def hms(secs):
    h, rem = divmod(int(secs), 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}" if h else f"{rem // 60}:{rem % 60:02d}"


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


async def state(atv):
    p = await atv.metadata.playing()
    return p.device_state, p.position, p.title


async def wait_playing(atv, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if (await state(atv))[0] == DeviceState.Playing:
            return True
        await asyncio.sleep(0.15)
    return False


async def wait_stopped(atv, timeout=4.0):
    """After opening the page, let any earlier playback stop, so it isn't
    mistaken for the new one."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if (await state(atv))[0] != DeviceState.Playing:
            return
        await asyncio.sleep(0.15)


# Remembering each Apple TV's address saves a full network search (~4s, and
# the search sometimes misses a TV that's just waking up). Unicast-scan the
# remembered address first; fall back to a full search and update the cache
# if the TV moved (DHCP) or isn't answering there.
CACHE = Path.home() / ".movieloft-atv-cache.json"


def _load_cache():
    try:
        return json.loads(CACHE.read_text())
    except Exception:
        return {}


async def _find(loop, storage, name):
    cache = _load_cache()
    hit = cache.get(name)
    if hit:
        confs = await pyatv.scan(loop, hosts=[hit["address"]], storage=storage, timeout=2)
        confs = [c for c in confs if c.identifier == hit["identifier"]]
        if confs:
            return confs[0], "remembered address"
    for timeout in (5, 8):                       # full search; a sleepy TV can be slow to answer
        confs = [c for c in await pyatv.scan(loop, storage=storage, timeout=timeout) if c.name == name]
        if confs:
            cache[name] = {"identifier": confs[0].identifier, "address": str(confs[0].address)}
            CACHE.write_text(json.dumps(cache, indent=1))
            return confs[0], f"network search ({timeout}s)"
    return None, ""


async def connect(name, log=print):
    loop = asyncio.get_running_loop()
    storage = FileStorage.default_storage(loop)
    await storage.load()
    t0 = time.monotonic()
    conf, how = await _find(loop, storage, name)
    if not conf:
        raise TuneError(f"Couldn't find the {name} Apple TV on the network — is it on?")
    log(f"found {name} at {conf.address} via {how} in {time.monotonic() - t0:.1f}s")
    missing = [p.protocol.name for p in conf.services if p.protocol.name in ("Companion", "AirPlay")
               and p.credentials is None]
    if missing:
        raise TuneError(f"{name} isn't paired yet")
    return await pyatv.connect(conf, loop, storage=storage)


async def tune(name, link, target=None, title="", log=print):
    """Open `link` on the Apple TV called `name`. If `target` is given (a
    function returning the seconds to jump to, asked at the moment of the
    jump so it can account for time spent tuning), start playback there.
    Returns a short description of what's on the TV."""
    atv = await connect(name, log)
    t0 = time.monotonic()
    mark = lambda what: log(f"{time.monotonic() - t0:6.2f}s  {what}")
    try:
        try:
            await atv.power.turn_on()             # wakes a sleeping Apple TV (and the TV, via HDMI-CEC)
        except Exception:
            pass
        await atv.apps.launch_app(link)
        mark("opened the page")
        if target is None:
            return "opened"                       # a show page: the viewer picks the episode
        await wait_stopped(atv)
        await asyncio.sleep(2.5)                  # let the page load
        await atv.remote_control.select()
        mark("select")
        if not await wait_playing(atv, 3):
            await atv.remote_control.select()     # the extras menu: now PLAY
            mark("select (PLAY in the menu)")
            if not await wait_playing(atv, 12):
                raise TuneError("The movie never started playing")
        # Land on the frame and STAY PAUSED — deliberate (Oct 2026):
        # the viewer presses Play when settled. (A play() right after the jump was
        # being dropped anyway while the seek settled.)
        # How the Apple TV actually behaves (probed Oct 2026, with someone
        # watching the screen):
        #  - after a jump the player shows a loading spinner; pausing during it
        #    leaves a half-paused player (first Play only completes the pause)
        #    or a new frame with the playhead still at the old spot;
        #  - a jump sent the instant playback starts is silently dropped;
        #  - the position reported while PLAYING is stale; PAUSED is truthful;
        #  - reported state lags commands.
        # So: let it PLAY through the jump, pause
        # only once it has loaded (~3s), then read the paused position — and
        # jump again if it isn't there. Lands ~3s past the broadcast point.
        SETTLE = 3.0
        await asyncio.sleep(1.0)                  # a jump at the very first instant gets dropped
        for attempt in range(4):
            secs = max(0, int(target()))
            await atv.remote_control.set_position(secs)
            await asyncio.sleep(0.5)
            if (await state(atv))[0] != DeviceState.Playing:
                await atv.remote_control.play()   # a jump from paused should resume; make sure
            await asyncio.sleep(SETTLE)
            await atv.remote_control.pause()
            end = time.monotonic() + 3.0
            while time.monotonic() < end and (await state(atv))[0] != DeviceState.Paused:
                await asyncio.sleep(0.15)
            await asyncio.sleep(0.4)
            st, pos, now_title = await state(atv)
            if pos is not None and secs - 5 <= pos <= secs + SETTLE + 15:
                break
            mark(f"jump to {hms(secs)} didn't take (paused at {pos}s); retrying")
        else:
            raise TuneError(f"The TV wouldn't jump to {hms(secs)} — it's paused near the start")
        mark(f"jumped to {hms(secs)}, paused (TV reports {pos}s)")
        if title and now_title and not norm(now_title).startswith(norm(title)[:12]):
            raise TuneError(f"The TV has “{now_title}”, not “{title}” — its Apple TV link may be wrong")
        return f"paused at {hms(secs)} — press play"
    finally:
        await asyncio.gather(*atv.close())


if __name__ == "__main__":
    name, link, secs = sys.argv[1], sys.argv[2], int(sys.argv[3])
    title = sys.argv[4] if len(sys.argv) > 4 else ""
    print(asyncio.run(tune(name, link, (lambda: secs), title)))
