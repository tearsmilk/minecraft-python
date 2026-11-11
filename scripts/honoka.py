#!/usr/bin/env python3
"""Honoka: the Horizon launcher with our patches on it.

The repository keeps only our changes: Horizon's source is fetched at the commit pinned in
upstream.json into upstream/ (not committed), and patches/*.patch are applied on it.

    python scripts/honoka.py sync            fetch Horizon at the pinned commit, apply the patches
    python scripts/honoka.py build           sync, then build the launcher into dist/
    python scripts/honoka.py check           sync, then cargo check (fast: no binary)
    python scripts/honoka.py refresh         write upstream/'s changes back into patches/
    python scripts/honoka.py bump COMMIT     pin another Horizon commit (then sync; fix the patch)

Needs git, Python 3.10+ and, to build, Rust (cargo). On Windows also the MSVC build tools.

Sign-in: the launcher signs players in with a Microsoft app's client ID, taken at build time from
HORIZON_MSA_CLIENT_ID. Without it the built launcher can't sign in (README.md, "Вход").
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM = ROOT / "upstream"
PATCHES = ROOT / "patches"
DIST = ROOT / "dist"
LOCK = ROOT / "upstream.json"
PATCH_NAME = "0001-honoka-launcher.patch"
# What the patch may touch: the launcher only.
PATCHED_PATHS = ["launcher"]


def run(*args: str, cwd: Path = UPSTREAM, env: dict | None = None, capture: bool = False) -> str:
    print("+", " ".join(args), flush=True)
    out = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return out.stdout if capture else ""


def lock() -> dict:
    return json.loads(LOCK.read_text(encoding="utf-8"))


def sync() -> None:
    pin = lock()
    if not (UPSTREAM / ".git").is_dir():
        UPSTREAM.mkdir(exist_ok=True)
        run("git", "init", "-q")
        run("git", "remote", "add", "upstream", pin["repo"])
    else:
        run("git", "remote", "set-url", "upstream", pin["repo"])
    have = subprocess.run(
        ["git", "cat-file", "-e", pin["commit"] + "^{commit}"],
        cwd=UPSTREAM,
        stderr=subprocess.DEVNULL,
    ).returncode == 0
    if not have:
        run("git", "fetch", "--depth", "1", "upstream", pin["commit"])
    # Back to Horizon's files exactly, then our patches: what upstream/ holds is always reproducible.
    run("git", "checkout", "-q", "-f", "--detach", pin["commit"])
    run("git", "clean", "-q", "-fd", "--", *PATCHED_PATHS)
    for patch in sorted(PATCHES.glob("*.patch")):
        run("git", "apply", "--whitespace=nowarn", str(patch))
    print(f"upstream/ is Horizon {pin['commit'][:10]} with {len(list(PATCHES.glob('*.patch')))} patch(es).")


def refresh() -> None:
    """Writes every change in upstream/'s launcher (new files too) back as the one patch."""
    run("git", "add", "-N", "--", *PATCHED_PATHS)
    diff = run("git", "diff", "--full-index", "--", *PATCHED_PATHS, capture=True)
    run("git", "reset", "-q", "--", *PATCHED_PATHS)
    for old in PATCHES.glob("*.patch"):
        old.unlink()
    (PATCHES / PATCH_NAME).write_text(diff, encoding="utf-8", newline="\n")
    print(f"patches/{PATCH_NAME}: {diff.count(chr(10))} lines.")


def bump(commit: str) -> None:
    pin = lock()
    pin["commit"] = commit
    LOCK.write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")
    print(f"Pinned {commit}. Run sync; if a hunk fails, fix upstream/ by hand and run refresh.")


def cargo(*args: str) -> None:
    env = dict(os.environ)
    if not env.get("HORIZON_MSA_CLIENT_ID"):
        print(
            "warning: HORIZON_MSA_CLIENT_ID is not set: this launcher will not be able to sign in.",
            file=sys.stderr,
        )
    run("cargo", *args, cwd=UPSTREAM / "launcher", env=env)


def build() -> None:
    sync()
    cargo("build", "--release", "--bin", "horizon-launcher")
    exe = ".exe" if os.name == "nt" else ""
    DIST.mkdir(exist_ok=True)
    built = UPSTREAM / "launcher" / "target" / "release" / f"horizon-launcher{exe}"
    out = DIST / f"honoka-launcher{exe}"
    shutil.copy2(built, out)
    print(f"Built {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync")
    sub.add_parser("build")
    sub.add_parser("check")
    sub.add_parser("refresh")
    b = sub.add_parser("bump")
    b.add_argument("commit")
    a = parser.parse_args()
    if a.cmd == "sync":
        sync()
    elif a.cmd == "build":
        build()
    elif a.cmd == "check":
        sync()
        cargo("check", "--all-targets")
    elif a.cmd == "refresh":
        refresh()
    elif a.cmd == "bump":
        bump(a.commit)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
