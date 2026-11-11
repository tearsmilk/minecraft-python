"""What this computer is, and what Honoka says about it.

macOS 11 on Intel: Horizon lists macOS 12 as its minimum, but its Intel programs (horizon-client,
horizon-prepare) are built for macOS 10.12 and later (their Mach-O LC_VERSION_MIN_MACOSX, checked on the
2026-11-11 Nightly), so they start on macOS 11. Honoka runs there with a warning, and prefers a Java 25
the player installed (mojang.find_java) over Mojang's, in case Mojang's needs a newer macOS.
"""

from __future__ import annotations

import platform
import sys


def macos_version() -> tuple[int, int] | None:
    """(major, minor) on macOS, None elsewhere. A Python built with an old SDK reports macOS 11+ as 10.16."""
    if sys.platform != "darwin":
        return None
    text = platform.mac_ver()[0]
    try:
        parts = [int(p) for p in text.split(".")[:2]] + [0]
    except ValueError:
        return None
    major, minor = parts[0], parts[1]
    if (major, minor) == (10, 16):
        return (11, 0)
    return (major, minor)


def is_intel_mac() -> bool:
    return sys.platform == "darwin" and platform.machine().lower() in ("x86_64", "amd64", "i386")


def warnings() -> list[str]:
    """What the player should know before playing on this computer."""
    found = []
    mac = macos_version()
    if mac is not None:
        if mac < (11, 0):
            found.append(
                f"macOS {mac[0]}.{mac[1]} слишком старая: игре нужна macOS 11 или новее."
            )
        elif mac < (12, 0):
            found.append(
                "macOS 11: Horizon официально поддерживает macOS 12+. Игра собрана и для 11, "
                "но это проверено меньше. Если подготовка ресурсов не идёт, установите Java 25 "
                "(например, Temurin 25 с adoptium.net): Honoka возьмёт её вместо Java от Mojang."
            )
    return found


def supported() -> bool:
    mac = macos_version()
    return mac is None or mac >= (11, 0)
