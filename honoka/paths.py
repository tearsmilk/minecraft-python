"""Where Honoka keeps its files: one folder in the platform's data directory (HONOKA_HOME overrides it).

    builds/<version>/         Horizon builds, unpacked
    prepared/<version>/       the resources horizon-prepare made for that build
    minecraft/                the game's files from Mojang, in the official launcher's layout
    runtime/<component>/      Mojang's Java
    game/                     the game folder: options.txt, servers.dat, logs, screenshots
    account.json              the signed-in account (tokens protected, see account.py)
    settings.json
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def home() -> Path:
    override = os.environ.get("HONOKA_HOME")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "Honoka"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Honoka"
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "honoka"


def builds() -> Path:
    return home() / "builds"


def prepared(version: str) -> Path:
    return home() / "prepared" / version


def minecraft() -> Path:
    return home() / "minecraft"


def runtime() -> Path:
    return home() / "runtime"


def game() -> Path:
    return home() / "game"


def account_file() -> Path:
    return home() / "account.json"


def settings_file() -> Path:
    return home() / "settings.json"


def official_minecraft() -> Path:
    """The official launcher's game folder, whose files are reused when they match."""
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / ".minecraft"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "minecraft"
    return Path.home() / ".minecraft"
