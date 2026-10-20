#!/usr/bin/env python3
"""Golden test for build.py.

Builds the hand-made fixture library under tests/fixture/ and compares the
result against the checked-in goldens. If a code change alters the page or the
--check report for the same inputs, this fails and prints a diff.

    python3 tests/golden_test.py            # check; exit 1 on any mismatch
    python3 tests/golden_test.py --update   # regenerate the goldens

Reproducibility: the build runs with SOURCE_DATE_EPOCH pinned (so __UPDATED__
and any "removed on" date are fixed) and with --root pointed at a throwaway
copy of the fixture (so the real movies.tsv / index.html are never touched).
The fixture's library-state.json is pre-seeded, so nothing is flagged as new.
"""
import difflib, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIXTURE = HERE / "fixture"
GOLDEN = HERE / "golden"
EPOCH = "1723766400"          # 2024-08-16 00:00:00 UTC — a fixed instant
INPUTS = ("movies.tsv", "corrections.toml", "library-state.json", "theatrical.json")


def build(args):
    """Run build.py against a fresh copy of the fixture; return (index, stdout)."""
    work = Path(tempfile.mkdtemp(prefix="movieloft-test-"))
    try:
        for name in INPUTS:
            shutil.copy(FIXTURE / name, work / name)
        shutil.copy(ROOT / "template.html", work / "template.html")
        env = {**os.environ, "SOURCE_DATE_EPOCH": EPOCH}
        env.pop("TMDB_API_KEY", None)   # keep the test offline — no gap-fill lookups
        out = subprocess.run(
            [sys.executable, str(ROOT / "build.py"), "--root", str(work), *args],
            capture_output=True, text=True, env=env, check=True)
        index_path = work / "index.html"   # not written on a --check run
        index = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
        return index, out.stdout
    finally:
        shutil.rmtree(work, ignore_errors=True)


def build_tv_check():
    """build_tv.py --check against the fixture episodes; returns stdout. The
    fixture is a catalog of the Apple TV app's metadata quirks (season-0 titles,
    interleaved clips, duplicate purchases, a split two-parter, "The Final
    Season"), so this golden pins the cleanup rules."""
    work = Path(tempfile.mkdtemp(prefix="movieloft-tvtest-"))
    try:
        shutil.copy(FIXTURE / "episodes.tsv", work / "episodes.tsv")
        out = subprocess.run(
            [sys.executable, str(ROOT / "build_tv.py"), "--root", str(work), "--check", "--episodes"],
            capture_output=True, text=True, check=True)
        return out.stdout
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    update = "--update" in sys.argv
    index_html, _ = build([])          # full build -> index.html
    _, check_txt = build(["--check"])  # report only -> stdout
    cases = {"index.html": index_html, "check.txt": check_txt,
             "tv-check.txt": build_tv_check()}

    if update:
        GOLDEN.mkdir(exist_ok=True)
        for name, got in cases.items():
            (GOLDEN / name).write_text(got, encoding="utf-8")
            print(f"wrote golden {name} ({len(got)} bytes)")
        return 0

    failed = False
    for name, got in cases.items():
        path = GOLDEN / name
        if not path.exists():
            print(f"MISSING golden {name} — run: python3 tests/golden_test.py --update")
            failed = True
            continue
        want = path.read_text(encoding="utf-8")
        if got == want:
            print(f"ok   {name}")
            continue
        failed = True
        print(f"FAIL {name} — build output no longer matches the golden:")
        diff = difflib.unified_diff(
            want.splitlines(), got.splitlines(),
            fromfile=f"golden/{name}", tofile=f"built/{name}", lineterm="")
        for line in list(diff)[:60]:
            print("   " + line)

    if failed:
        print("\nIf the change was intentional, refresh with: "
              "python3 tests/golden_test.py --update")
        return 1
    print("\nall golden cases match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
