"""This instance's settings, from movieloft.toml at the repo root.

Everything specific to one household lives there — the server's address, the
rooms with an Apple TV, an optional loop channel — so the code itself carries
none of it. Copy movieloft.example.toml to movieloft.toml to start. Read by
the web server (room validation), the Tune in helper (room → Apple TV name,
server URL) and build_guide.py (room buttons, loop channel).

MOVIELOFT_CONFIG can point somewhere else (the tests use it).
No file means no rooms and no loop channel: the pages and guide still work,
and Tune in offers only "This device".
"""
import os, re, tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY = re.compile(r"^[a-z][a-z0-9-]{0,30}$")


def load(root=ROOT):
    path = Path(os.environ.get("MOVIELOFT_CONFIG") or Path(root) / "movieloft.toml")
    raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    rooms = []
    for r in raw.get("rooms", []):
        key, label, atv = r.get("key", ""), r.get("label", ""), r.get("apple_tv", "")
        if not (KEY.match(key) and label and atv):
            raise ValueError(f"movieloft.toml: each [[rooms]] needs key (lowercase letters), "
                             f"label and apple_tv — got {r!r}")
        if key == "here" or key in {x["key"] for x in rooms}:
            raise ValueError(f"movieloft.toml: room key {key!r} is reserved or used twice")
        rooms.append({"key": key, "label": label, "apple_tv": atv})
    loop = raw.get("loop") or None
    if loop and not (loop.get("name") and loop.get("movie")):
        raise ValueError("movieloft.toml: [loop] needs name and movie")
    return {"url": raw.get("url", "").rstrip("/"), "rooms": rooms, "loop": loop}
