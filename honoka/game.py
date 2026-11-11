"""Preparing the resources with the build's horizon-prepare and starting horizon-client (Launch API 0.1)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

from . import builds, config, paths

Progress = Callable[[str, "float | None"], None]
# Hide the console window horizon-prepare and the game would open on Windows.
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def prepared_is_current(version: str) -> bool:
    """`horizon-prepare --check`: exit 0 when the resources are complete and current for this build."""
    out = paths.prepared(version)
    if not out.is_dir():
        return False
    result = subprocess.run(
        [str(builds.program(version, "horizon-prepare")), "--check", "--output", str(out)],
        cwd=builds.build_dir(version),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=NO_WINDOW,
    )
    return result.returncode == 0


def prepare(version: str, minecraft_dir: Path, server_jar: Path, java_home: Path, progress: Progress) -> None:
    """Prepares the build's resources from the owner's game files, reading `--progress json`'s lines."""
    out = paths.prepared(version)
    out.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(builds.program(version, "horizon-prepare")),
        "--prepare",
        "--server-jar", str(server_jar),
        "--minecraft-dir", str(minecraft_dir),
        "--java-home", str(java_home),
        "--output", str(out),
        "--complete",
        "--progress", "json",
    ]
    message, error = "Готовлю ресурсы игры…", None
    progress(message, 0.0)
    log = paths.home() / "prepare.log"
    with open(log, "w", encoding="utf-8") as stderr, subprocess.Popen(
        cmd,
        cwd=builds.build_dir(version),
        stdout=subprocess.PIPE,
        stderr=stderr,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=NO_WINDOW,
    ) as proc:
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            if "message" in event:
                message = str(event["message"])
                progress(message, None)
            if "fraction" in event:
                progress(message, float(event["fraction"]))
            if "error" in event:
                error = str(event["error"])
    if proc.returncode != 0:
        raise RuntimeError(error or f"Подготовка не удалась (код {proc.returncode}). Подробности: {log}")


def start(version: str, session_json: str, server: str | None) -> subprocess.Popen:
    """Starts the game in Honoka's game folder, with the owner's session on standard input."""
    game_dir = paths.game()
    game_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(builds.program(version, "horizon-client")),
        "--resources", str(paths.prepared(version)),
        "--game-dir", str(game_dir),
        "--home", str(game_dir),
        "--session-stdin",
    ]
    if server:
        cmd += ["--quickPlayMultiplayer", server]
    env = {**os.environ, **config.GAME_ENV, "HORIZON_HOME": str(game_dir)}
    stderr = open(game_dir / "honoka-stderr.log", "w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        cwd=game_dir,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=stderr,
        creationflags=NO_WINDOW,
    )
    stderr.close()
    # The token goes on standard input, never on the command line where other programs can read it.
    proc.stdin.write(session_json.encode())
    proc.stdin.close()
    return proc


def exit_message(code: int) -> str | None:
    """What to tell the player when the game ended (Launch API exit codes)."""
    if code == 0:
        return None
    log = paths.game() / "honoka-stderr.log"
    try:
        lines = [l for l in log.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    except OSError:
        lines = []
    last = lines[-1] if lines else ""
    if code == 2:
        return f"Игра не приняла параметры запуска (ошибка лаунчера): {last}"
    return f"Игра завершилась с ошибкой ({code}). {last}".strip()
