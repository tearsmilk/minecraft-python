"""Horizon's builds: find the newest, check its signature, download and unpack it.

Builds are GitHub releases of horizon-rust/horizon (docs/api/launch-guide.md there, step 1). Each release
carries SHA256SUMS, signed with Horizon's release key: SHA256SUMS.sig over ``horizon release <tag>\\n`` then
the list. A Nightly is checked with SHA256SUMS.v2.sig, signed for its own version
(``nightly-<date>-<commit>``, from its title), so an older Nightly can't pass for a newer one.
"""

from __future__ import annotations

import base64
import json
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from . import config, ed25519, net, paths

API = f"https://api.github.com/repos/{config.HORIZON_REPO}"
DOWNLOAD = f"https://github.com/{config.HORIZON_REPO}/releases/download"
SUMS = "SHA256SUMS"
SIGNATURE = "SHA256SUMS.sig"
SIGNATURE_V2 = "SHA256SUMS.v2.sig"
INSTALLED = "honoka-build.json"


class BuildError(Exception):
    pass


@dataclass(frozen=True)
class Release:
    tag: str  # the GitHub tag the files are under: "v2026.11.10", "nightly"
    version: str  # what it installs as, and the text its signature names: the tag, or "nightly-<date>-<commit>"
    signature: str  # SIGNATURE or SIGNATURE_V2


def asset_name(system: str | None = None, machine: str | None = None) -> str:
    """This computer's build archive."""
    system = system or sys.platform
    machine = (machine or platform.machine()).lower()
    arm = machine in ("arm64", "aarch64")
    if system == "win32":
        return "horizon-windows-arm64.zip" if arm else "horizon-windows-x64.zip"
    if system == "darwin":
        return "horizon-macos-arm64.zip" if arm else "horizon-macos-x64.zip"
    if system.startswith("linux") and machine in ("x86_64", "amd64"):
        return "horizon-linux-x86_64.tar.gz"
    raise BuildError(f"Horizon has no build for {system} {machine}.")


def is_game_tag(tag: str) -> bool:
    """A game release's tag: "v" then a digit. Launcher releases (launcher@...) are in the same repository."""
    return re.fullmatch(r"v\d.*", tag) is not None


def nightly_version(title: str) -> str | None:
    """"Nightly 2026-10-28 · 0c02067" -> "nightly-2026-10-28-0c02067"; None for any other title."""
    m = re.fullmatch(r"Nightly (\d{4}-\d{2}-\d{2}) · ([0-9a-f]{7,40})", title)
    return f"nightly-{m.group(1)}-{m.group(2)}" if m else None


def newest(channel: str) -> Release:
    if channel == "nightly":
        r = net.get_json(f"{API}/releases/tags/nightly")
        version = nightly_version(r.get("name") or "")
        if not version:
            raise BuildError(f"The Nightly's title doesn't name its date and commit: {r.get('name')!r}.")
        return Release("nightly", version, SIGNATURE_V2)
    for r in net.get_json(f"{API}/releases?per_page=50"):
        if is_game_tag(r["tag_name"]) and not r.get("draft") and not r.get("prerelease"):
            return Release(r["tag_name"], r["tag_name"], SIGNATURE)
    raise BuildError("Horizon has no game release yet.")


def trusted_keys() -> list[bytes]:
    return [base64.b64decode(k) for k in config.HORIZON_RELEASE_KEYS]


def signed_message(version: str, sums: bytes) -> bytes:
    return f"horizon release {version}\n".encode() + sums


def check_signature(version: str, sums: bytes, signatures: str, keys: list[bytes]) -> None:
    """Passes when one of `keys` signed `sums` for `version` (one base64 signature per line)."""
    message = signed_message(version, sums)
    for line in signatures.split():
        try:
            signature = base64.b64decode(line, validate=True)
        except ValueError:
            continue
        if any(ed25519.verify(key, message, signature) for key in keys):
            return
    raise BuildError(f"{SUMS} of {version} is not signed with Horizon's key: not installed.")


def parse_sums(text: str) -> dict[str, str]:
    sums = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            sums[parts[1].lstrip("*")] = parts[0]
    return sums


def signed_digest(release: Release, asset: str, keys: list[bytes] | None = None) -> str:
    """The SHA-256 Horizon signed for `asset` in `release`."""
    base = f"{DOWNLOAD}/{release.tag}"
    try:
        sums = net.get_bytes(f"{base}/{SUMS}")
        signatures = net.get_bytes(f"{base}/{release.signature}").decode()
    except net.HttpError as e:
        raise BuildError(f"{release.version} has no signed {SUMS}: not installed ({e}).") from None
    check_signature(release.version, sums, signatures, keys or trusted_keys())
    digest = parse_sums(sums.decode()).get(asset)
    if not digest:
        raise BuildError(f"{release.version} has no {asset}.")
    return digest


def build_dir(version: str) -> Path:
    return paths.builds() / version


def installed() -> list[str]:
    root = paths.builds()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / INSTALLED).is_file())


def program(version: str, name: str) -> Path:
    exe = ".exe" if sys.platform == "win32" else ""
    return build_dir(version) / f"{name}{exe}"


def _safe_target(root: Path, member: str) -> Path | None:
    """Where `member` unpacks under `root`, without the archive's top folder; None for a path that leaves it."""
    parts = PurePosixPath(member.replace("\\", "/")).parts[1:]
    if not parts or any(p in ("..", "") for p in parts) or PurePosixPath(member).is_absolute():
        return None
    return root.joinpath(*parts)


def unpack(archive: Path, dest: Path) -> None:
    """Unpacks a build into `dest`, dropping its top folder (horizon-<platform>/)."""
    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive) as tar:
            for m in tar.getmembers():
                target = _safe_target(dest, m.name)
                if target is None or not (m.isfile() or m.isdir()):
                    continue
                if m.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(m) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                if m.mode & 0o111:
                    target.chmod(0o755)
    else:
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                target = _safe_target(dest, info.filename)
                if target is None:
                    continue
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                if (info.external_attr >> 16) & 0o111:
                    target.chmod(0o755)
    if sys.platform == "darwin":
        # The build is signed ad hoc: without this, macOS refuses to start what was downloaded.
        subprocess.run(
            ["xattr", "-dr", "com.apple.quarantine", str(dest)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def install(release: Release, progress: Callable[[str, float | None], None]) -> str:
    """Downloads and unpacks `release` unless it is already installed. Returns its version."""
    if (build_dir(release.version) / INSTALLED).is_file():
        return release.version
    asset = asset_name()
    progress(f"Проверяю подпись Horizon {release.version}…", None)
    digest = signed_digest(release, asset)
    archive = paths.builds() / f".{release.version}-{asset}"
    progress(f"Скачиваю Horizon {release.version}…", 0.0)
    net.download(
        f"{DOWNLOAD}/{release.tag}/{asset}",
        archive,
        sha256=digest,
        progress=lambda done, total: progress(f"Скачиваю Horizon {release.version}…", done / total if total else None),
    )
    progress("Распаковываю…", None)
    dest = build_dir(release.version)
    tmp = dest.with_name(dest.name + ".unpacking")
    shutil.rmtree(tmp, ignore_errors=True)
    unpack(archive, tmp)
    (tmp / INSTALLED).write_text(json.dumps({"version": release.version, "asset": asset, "sha256": digest}))
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)
    archive.unlink(missing_ok=True)
    for name in ("horizon-client", "horizon-prepare"):
        p = program(release.version, name)
        if p.exists() and sys.platform != "win32":
            p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return release.version


def remove_old(keep: list[str]) -> None:
    """Removes builds other than `keep`, and their prepared resources."""
    for version in installed():
        if version not in keep:
            shutil.rmtree(build_dir(version), ignore_errors=True)
            shutil.rmtree(paths.prepared(version), ignore_errors=True)


def research_lock(version: str) -> dict:
    """The build's pins: which Minecraft version it prepares from and the Java it needs."""
    return json.loads((build_dir(version) / "research-lock.json").read_text(encoding="utf-8"))["minecraft"]
