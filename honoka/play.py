"""Play: everything between the button and the game, in order."""

from __future__ import annotations

import subprocess
from typing import Callable

from . import account, builds, config, game, mojang, net, settings, system

Progress = Callable[[str, "float | None"], None]


def server_address() -> str:
    """The server Play joins: branding/links.json from the repository, else the built-in one."""
    try:
        links = net.get_json(config.LINKS_URL)
        address = str(links.get("official_server", "")).strip()
        if address:
            return address
    except (OSError, ValueError, net.HttpError):
        pass
    return config.SERVER_ADDRESS


def ensure_build(progress: Progress) -> str:
    """The newest build of the chosen channel, installed; the installed one when GitHub can't be reached."""
    channel = settings.load().get("channel", config.DEFAULT_CHANNEL)
    current = settings.load().get("build")
    try:
        release = builds.newest(channel)
    except (OSError, net.HttpError) as e:
        if current and current in builds.installed():
            progress(f"GitHub недоступен ({e}), играю на установленной сборке {current}.", None)
            return current
        raise
    version = builds.install(release, progress)
    if version != current:
        settings.update(build=version)
        # Keep the one before, so the player can go back while its release still exists.
        builds.remove_old([v for v in (version, current) if v])
    return version


def ensure_prepared(version: str, progress: Progress) -> None:
    progress("Проверяю ресурсы игры…", None)
    if game.prepared_is_current(version):
        return
    pins = builds.research_lock(version)
    mc = pins["version"]
    minecraft_dir = mojang.game_files(mc, progress)
    server = mojang.server_jar(mc, progress)
    java = mojang.java_home(mojang.java_component(mc), progress, major=pins.get("java_major"))
    game.prepare(version, minecraft_dir, server, java, progress)


def play(progress: Progress) -> subprocess.Popen:
    """Checks the owner, installs, prepares and starts the game on the server. Raises with a message for the player."""
    if not system.supported():
        raise RuntimeError(system.warnings()[0])
    progress("Проверяю аккаунт…", None)
    session = account.session()  # the owner gate: nothing below runs for an account without the game
    version = ensure_build(progress)
    ensure_prepared(version, progress)
    server = server_address()
    progress(f"Запускаю игру на {server}…", None)
    return game.start(version, session.game_json(), server)
