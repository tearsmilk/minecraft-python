"""Signing in through the official Horizon launcher, until Honoka's own Azure app is approved.

The Horizon launcher already has an approved Microsoft app. A player who signed in there with an
account that owns Minecraft: Java Edition can play through Honoka too: Honoka asks that launcher for
the account (``horizon-launcher --json account list``) and for a game session
(``horizon-launcher --json account session <uuid>``, the read-once session file Horizon's own game
uses). The owner gate stays Horizon's: it reports ``owner`` and hands out a session only for a
signed-in account.

Used only while Honoka has no client ID of its own (config.msa_client_id() is empty).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from . import settings

TIMEOUT = 60
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class BridgeError(Exception):
    pass


def find_launcher() -> Path | None:
    """The Horizon launcher's program: settings.json's horizon_launcher, HONOKA_HORIZON_LAUNCHER, its install folders, PATH."""
    candidates = [settings.load().get("horizon_launcher"), os.environ.get("HONOKA_HORIZON_LAUNCHER")]
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(str(Path(local) / "Programs" / "Horizon Launcher" / "horizon-launcher.exe"))
    elif sys.platform == "darwin":
        for apps in (Path("/Applications"), Path.home() / "Applications"):
            for app in ("Horizon Launcher.app", "Horizon.app"):
                candidates.append(str(apps / app / "Contents" / "MacOS" / "horizon-launcher"))
    candidates.append(shutil.which("horizon-launcher"))
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c)
    return None


def _run(*args: str) -> dict:
    exe = find_launcher()
    if exe is None:
        raise BridgeError("Лаунчер Horizon не найден. Установите его с playhorizon.dev и войдите в нём.")
    try:
        out = subprocess.run(
            [str(exe), "--json", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BridgeError(f"Лаунчер Horizon не ответил: {e}") from None
    try:
        return json.loads(out.stdout)
    except ValueError:
        message = (out.stderr or out.stdout).strip().splitlines()
        raise BridgeError(f"Лаунчер Horizon: {message[-1] if message else 'нет ответа'}") from None


SIGN_IN_LINE = re.compile(r"open (\S+) in a browser and enter the code (\S+)")


def sign_in(on_code: Callable[[str, str], None], cancelled: Callable[[], bool] = lambda: False) -> str:
    """Signs a Microsoft account in in the Horizon launcher, from its command line.

    For computers where its window doesn't open (macOS 11: Horizon.app asks for macOS 12, while the
    program inside it is built for 10.12+ and its commands run). `on_code(link, code)` gets the
    device code to show; returns the account's name once the launcher has signed it in.
    """
    exe = find_launcher()
    if exe is None:
        raise BridgeError("Лаунчер Horizon не найден. Установите его с playhorizon.dev (на macOS 11 тоже: "
                          "перетащите Horizon в «Программы», открывать не нужно).")
    proc = subprocess.Popen(
        [str(exe), "account", "sign-in"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=NO_WINDOW,
    )
    said: list[str] = []

    def read_stderr():
        for line in proc.stderr:
            said.append(line.strip())
            m = SIGN_IN_LINE.search(line)
            if m:
                on_code(m.group(1), m.group(2))

    reader = threading.Thread(target=read_stderr, daemon=True)
    reader.start()
    while proc.poll() is None:
        if cancelled():
            proc.terminate()
            raise BridgeError("Вход отменён.")
        time.sleep(0.3)
    reader.join(timeout=2)
    out = proc.stdout.read() if proc.stdout else ""
    m = re.search(r"Signed in as (.+)\.", out)
    if proc.returncode != 0 or not m:
        last = next((s for s in reversed(said) if s), "") or out.strip()
        raise BridgeError(f"Лаунчер Horizon не смог войти: {last or proc.returncode}")
    name = m.group(1).strip()
    # The game plays as the account just signed in.
    _run("account", "select", name)
    return name


def owner_account() -> dict | None:
    """The account the Horizon launcher plays as, when it owns the game: {"name", "uuid"}; else None."""
    listing = _run("account", "list")
    if not listing.get("owner"):
        return None
    for a in listing.get("accounts", []):
        if a.get("selected"):
            return {"name": a["name"], "uuid": a["uuid"]}
    return None


def session_json() -> tuple[str, str]:
    """(name, the game's session JSON) of the Horizon launcher's owner account, renewed by that launcher."""
    account = owner_account()
    if account is None:
        raise BridgeError(
            "В лаунчере Horizon нет аккаунта с купленной Minecraft: Java Edition. Войдите в нём и выберите его."
        )
    reply = _run("account", "session", account["uuid"])
    path = reply.get("session_file")
    if not path:
        why = (reply.get("authentication") or {}).get("message") or "войдите в лаунчере Horizon снова"
        raise BridgeError(f"Лаунчер Horizon не выдал сессию: {why}")
    file = Path(path)
    try:
        body = file.read_text(encoding="utf-8")
    finally:
        # Read once: nothing with a token stays on disk.
        try:
            file.unlink()
        except OSError:
            pass
    session = json.loads(body)
    if not session.get("access_token") or session.get("user_type", "msa") != "msa":
        raise BridgeError("Лаунчер Horizon выдал неполную сессию.")
    return account["name"], body
