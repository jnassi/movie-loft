#!/usr/bin/env python3
"""Build a guide.html from a made-up library, for tests/guide_test.mjs.

    python3 tests/guide_fixture.py      # prints the path of the built guide.html

The real guide.html is built from someone's own library, which a fresh clone
doesn't have. This makes a deterministic stand-in big enough to fill every
channel (movies across six decades with directors and series, Star Trek films
and shows for Starfleet, superhero titles, half-hour and hour-long shows,
a loop movie), using the example config files, and runs the real
build_guide.py on it in a throwaway folder.
"""
import json, random, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
rng = random.Random(7)
work = Path(tempfile.mkdtemp(prefix="movieloft-guide-"))

movies = []
def movie(title, year, director, set_="", secs=None):
    movies.append({"raw": title, "title": title, "year": year, "director": director, "set": set_,
                   "idx": len(movies) + 1, "secs": secs or rng.randint(85, 150) * 60})

directors = [f"Director {c}" for c in "ABCDEFGHIJKL"]
for i in range(120):
    movie(f"Feature {i:03d}", 1972 + i % 54, directors[i % len(directors)])
for name in ("Alpha", "Bravo", "Charlie", "Delta", "Echo"):
    for n in range(1, 4):
        movie(f"{name} Saga {n}", 1980 + n * 3, directors[n], set_=f"{name} Saga")
for n in ("", " II", " III"):
    movie(f"Star Trek{n}: The Test", 1990, "Director T", set_="Star Trek")
for t in ("Iron Man", "Thor", "Wonder Woman", "Superman Returns"):
    movie(t, 2008, "Director H")
movie("Frozen", 2013, "Director F", secs=102 * 60)

shows = []
def show(name, n, minutes, svc=""):
    eps = [[1 + e // 10, 1 + e % 10, f"{name} {e + 1}", minutes * 60 + rng.randint(-90, 90)] for e in range(n)]
    shows.append({"show": name, "first": 2000, "eps": eps, "svc": svc})

for i in range(10):
    show(f"Sitcom {i}", rng.randint(10, 60), 22)
for i in range(8):
    show(f"Drama {i}", rng.randint(10, 60), 44)
show("Star Trek: The Test Generation", 40, 45)
show("Superman & Friends", 20, 42)
show("Streamed Show", 12, 30, svc="Apple TV+")
show("Short Show", 3, 30)                       # under min_episodes: sits out

(work / "catalog-movies.json").write_text(json.dumps(movies))
(work / "catalog-shows.json").write_text(json.dumps(shows))
for f in ("template.html", "template-guide.html"):
    shutil.copy(ROOT / f, work / f)
shutil.copy(ROOT / "corrections.example.toml", work / "corrections.toml")
shutil.copy(ROOT / "movieloft.example.toml", work / "movieloft.toml")
out = subprocess.run([sys.executable, str(ROOT / "build_guide.py"), "--root", str(work)],
                     capture_output=True, text=True)
if out.returncode:
    sys.exit(out.stdout + out.stderr)
print(work / "guide.html")
