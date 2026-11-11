"""Everything Honoka-specific in one place."""

from __future__ import annotations

import os

APP_NAME = "Honoka"

# The server Play joins. branding/links.json in this repository can move it without a release.
SERVER_NAME = "Hoka"
SERVER_ADDRESS = "mc.hoka.ink"
WEBSITE = "https://hoka.ink"
LINKS_URL = "https://raw.githubusercontent.com/tearsmilk/minecraft-python/main/branding/links.json"

# Where Horizon's builds come from.
HORIZON_REPO = "horizon-rust/horizon"
# "release": the newest game release (v...), kept for good. "nightly": the newest Nightly, deleted after 7 days.
DEFAULT_CHANNEL = "release"
# Horizon's release-signing public keys (crates/horizon-release-sign/release-keys.txt), base64 Ed25519.
HORIZON_RELEASE_KEYS = ("MU4oiIQcCxkZvbwSjjXs7SySCuM6ywRQ3nGaJYZG0gw=",)

# The server is older than the game (1.21.11 behind Velocity): Horizon's adapter for older servers is on.
# The server's status ping picks the adapter; a 26.3 server plays as before.
GAME_ENV = {"HORIZON_OLDER_SERVERS": "1"}

# The Azure app the players sign in with (Microsoft Entra ID, personal accounts, public client flows on,
# approved by Mojang for the Minecraft API). README.md, "Вход".
MSA_CLIENT_ID = ""


def msa_client_id() -> str:
    """The app's client ID: HONOKA_MSA_CLIENT_ID, else the built-in one, else settings.json's."""
    from . import settings

    for value in (os.environ.get("HONOKA_MSA_CLIENT_ID"), MSA_CLIENT_ID, settings.load().get("msa_client_id")):
        if value and value.strip():
            return value.strip()
    return ""


USER_AGENT = "Honoka-Launcher"
