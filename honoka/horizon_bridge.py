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

from . import paths, settings

TIMEOUT = 60
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class BridgeError(Exception):
    pass


# The launcher release used when GitHub's API can't be asked for the newest (its files are still checked).
KNOWN_LAUNCHER = "launcher@0.2.59"


def launcher_asset() -> str:
    import platform as _platform

    machine = _platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if sys.platform == "win32":
        return "horizon-launcher-windows-arm64.zip" if arm else "horizon-launcher-windows-x64.zip"
    if sys.platform == "darwin":
        return "horizon-launcher-macos-arm64.zip" if arm else "horizon-launcher-macos-x64.zip"
    return "horizon-launcher-linux-x86_64.tar.gz"


def _installed_dir() -> Path:
    return paths.home() / "horizon-launcher"


def _program_in(folder: Path) -> Path | None:
    name = "horizon-launcher.exe" if sys.platform == "win32" else "horizon-launcher"
    mac = folder / "Horizon.app" / "Contents" / "MacOS" / "horizon-launcher"
    if mac.is_file():
        return mac
    for found in sorted(folder.rglob(name)) if folder.is_dir() else []:
        if found.is_file():
            return found
    return None


def install_launcher(progress: Callable[[str, "float | None"], None]) -> Path:
    """Downloads the Horizon launcher into Honoka's folder, checked against Horizon's signature.

    Only its command line is used (sign-in and the game's session), so it works where its window
    doesn't open (macOS 11): nothing has to be installed or opened by hand.
    """
    from . import builds, net

    from . import system

    tag = KNOWN_LAUNCHER
    mac = system.macos_version()
    # macOS 11: the version whose program was checked to run there (built for macOS 10.12+); a newer
    # one could ask for a newer macOS.
    newest = mac is None or mac >= (12, 0)
    try:
        for r in net.get_json(f"{builds.API}/releases?per_page=50") if newest else []:
            if r["tag_name"].startswith("launcher@") and not r.get("draft") and not r.get("prerelease"):
                tag = r["tag_name"]
                break
    except (OSError, ValueError, net.HttpError):
        pass
    dest = _installed_dir() / tag
    found = _program_in(dest)
    if found:
        return found
    asset = launcher_asset()
    progress("Проверяю подпись лаунчера Horizon…", None)
    digest = builds.signed_digest(builds.Release(tag, tag, builds.SIGNATURE), asset)
    archive = _installed_dir() / f".{asset}"
    net.download(
        f"{builds.DOWNLOAD}/{tag}/{asset}",
        archive,
        sha256=digest,
        progress=lambda done, total: progress("Скачиваю лаунчер Horizon…", done / total if total else None),
    )
    tmp = dest.with_name(dest.name + ".unpacking")
    shutil.rmtree(tmp, ignore_errors=True)
    builds.unpack(archive, tmp, strip_top=False)
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)
    archive.unlink(missing_ok=True)
    found = _program_in(dest)
    if found is None:
        raise BridgeError("В архиве лаунчера Horizon нет его программы.")
    if sys.platform != "win32":
        found.chmod(0o755)
    # Older versions are no longer needed.
    for old in _installed_dir().iterdir():
        if old.is_dir() and old.name != tag and not old.name.startswith("."):
            shutil.rmtree(old, ignore_errors=True)
    return found


def ensure_launcher(progress: Callable[[str, "float | None"], None]) -> Path:
    return find_launcher() or install_launcher(progress)


def find_launcher() -> Path | None:
    """The Horizon launcher's program: settings.json's horizon_launcher, HONOKA_HORIZON_LAUNCHER, the one Honoka
    downloaded, the player's own install, PATH."""
    candidates = [settings.load().get("horizon_launcher"), os.environ.get("HONOKA_HORIZON_LAUNCHER")]
    if candidates[1]:
        # Set explicitly (tests, scripts): only that one.
        return Path(candidates[1]) if Path(candidates[1]).is_file() else None
    if _installed_dir().is_dir():
        for folder in sorted(_installed_dir().iterdir(), reverse=True):
            found = _program_in(folder) if folder.is_dir() and not folder.name.startswith(".") else None
            if found:
                candidates.append(str(found))
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
        raise BridgeError("Войдите аккаунтом Microsoft, на котором куплена игра (кнопка «Войти»).")
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


def sign_in(
    on_code: Callable[[str, str], None],
    cancelled: Callable[[], bool] = lambda: False,
    progress: Callable[[str, "float | None"], None] | None = None,
) -> str:
    """Signs a Microsoft account in in the Horizon launcher, from its command line.

    For computers where its window doesn't open (macOS 11: Horizon.app asks for macOS 12, while the
    program inside it is built for 10.12+ and its commands run). `on_code(link, code)` gets the
    device code to show; returns the account's name once the launcher has signed it in.
    """
    exe = ensure_launcher(progress or (lambda text, fraction=None: None))
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
