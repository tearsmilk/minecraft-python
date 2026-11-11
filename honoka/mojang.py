"""The game's files from Mojang and Mojang's Java, for a signed-in owner only.

horizon-prepare reads them in the official launcher's layout (docs/api/launch-guide.md, step 3): the
version JSON, the client jar, this system's libraries, the asset index and objects, the server jar (first
preparation only), and a Java of the pinned major. Files already in the player's own official install are
copied from there when their sha1 matches; the rest come from Mojang's own servers, never a mirror, each
checked against the sha1 Mojang lists.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import net, paths

MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
JAVA_RUNTIMES = (
    "https://launchermeta.mojang.com/v1/products/java-runtime/2ec0cc96c44e5a76b9c8b7c39df7210883d12871/all.json"
)
RESOURCES = "https://resources.download.minecraft.net"
WORKERS = 16

Progress = Callable[[str, "float | None"], None]


@dataclass(frozen=True)
class Needed:
    path: Path  # relative to the minecraft folder
    sha1: str
    url: str


def os_name() -> str:
    return {"win32": "windows", "darwin": "osx"}.get(sys.platform, "linux")


def java_platform() -> str:
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if sys.platform == "win32":
        return "windows-arm64" if arm else "windows-x64"
    if sys.platform == "darwin":
        return "mac-os-arm64" if arm else "mac-os"
    return "linux"


def rules_allow(rules: list[dict] | None, os_: str | None = None, arch: str | None = None) -> bool:
    """Mojang's library rules: the last rule that matches decides; no rules means allowed."""
    if not rules:
        return True
    os_ = os_ or os_name()
    arch = arch or ("x86" if platform.machine().lower() in ("i386", "i686", "x86") else "x86_64")
    allowed = False
    for rule in rules:
        cond = rule.get("os", {})
        matches = (not cond.get("name") or cond["name"] == os_) and (not cond.get("arch") or cond["arch"] == arch)
        if "features" in rule:
            matches = False  # launcher features (demo, custom resolution...) are never on here
        if matches:
            allowed = rule.get("action") == "allow"
    return allowed


def libraries(version_json: dict, os_: str | None = None) -> list[Needed]:
    os_ = os_ or os_name()
    needed = []
    for lib in version_json.get("libraries", []):
        if not rules_allow(lib.get("rules"), os_):
            continue
        downloads = lib.get("downloads", {})
        artifact = downloads.get("artifact")
        if artifact and artifact.get("url"):
            needed.append(Needed(Path("libraries") / artifact["path"], artifact["sha1"], artifact["url"]))
        natives = lib.get("natives", {}).get(os_)
        if natives:
            classifier = downloads.get("classifiers", {}).get(natives.replace("${arch}", "64"))
            if classifier:
                needed.append(Needed(Path("libraries") / classifier["path"], classifier["sha1"], classifier["url"]))
    return needed


def _have(root: Path, item: Needed) -> bool:
    target = root / item.path
    return target.is_file() and net.file_digest(target, "sha1") == item.sha1


def _fetch(root: Path, item: Needed, official: Path) -> None:
    """Makes `item` whole under `root`: kept, copied from the player's own install, or downloaded."""
    if _have(root, item):
        return
    target = root / item.path
    theirs = official / item.path
    if theirs.is_file() and net.file_digest(theirs, "sha1") == item.sha1:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(theirs, target)
        return
    net.download(item.url, target, sha1=item.sha1)


def _fetch_all(root: Path, items: list[Needed], label: str, progress: Progress) -> None:
    official = paths.official_minecraft()
    total = len(items)
    if not total:
        return
    done = 0
    progress(label, 0.0)
    with ThreadPoolExecutor(WORKERS) as pool:
        futures = [pool.submit(_fetch, root, item, official) for item in items]
        for future in as_completed(futures):
            future.result()
            done += 1
            if done % 50 == 0 or done == total:
                progress(label, done / total)


def version_json(version: str) -> dict:
    """The version JSON: the player's own when it is there, else Mojang's (saved in the official layout)."""
    root = paths.minecraft()
    path = root / "versions" / version / f"{version}.json"
    manifest = net.get_json(MANIFEST)
    entry = next((v for v in manifest["versions"] if v["id"] == version), None)
    if entry is None:
        raise RuntimeError(f"Mojang не знает версию {version}.")
    _fetch(root, Needed(path.relative_to(root), entry["sha1"], entry["url"]), paths.official_minecraft())
    return json.loads(path.read_text(encoding="utf-8"))


def game_files(version: str, progress: Progress) -> Path:
    """The version JSON, client jar, libraries and assets of `version`, under paths.minecraft(). Returns it."""
    root = paths.minecraft()
    progress(f"Получаю файлы Minecraft {version}…", None)
    vj = version_json(version)
    client = vj["downloads"]["client"]
    items = [Needed(Path("versions") / version / f"{version}.jar", client["sha1"], client["url"])]
    items += libraries(vj)
    _fetch_all(root, items, "Библиотеки Minecraft…", progress)

    index = vj["assetIndex"]
    index_item = Needed(Path("assets") / "indexes" / f"{index['id']}.json", index["sha1"], index["url"])
    _fetch(root, index_item, paths.official_minecraft())
    objects = json.loads((root / index_item.path).read_text(encoding="utf-8"))["objects"]
    assets = {
        o["hash"]: Needed(Path("assets") / "objects" / o["hash"][:2] / o["hash"], o["hash"], f"{RESOURCES}/{o['hash'][:2]}/{o['hash']}")
        for o in objects.values()
    }
    _fetch_all(root, list(assets.values()), "Ресурсы Minecraft (звуки, языки)…", progress)
    return root


def server_jar(version: str, progress: Progress) -> Path:
    """The server jar, which the first preparation reads. Kept beside the version, as no launcher keeps it."""
    root = paths.minecraft()
    vj = json.loads((root / "versions" / version / f"{version}.json").read_text(encoding="utf-8"))
    server = vj["downloads"]["server"]
    item = Needed(Path("versions") / version / f"{version}-server.jar", server["sha1"], server["url"])
    progress("Сервер Minecraft для подготовки…", None)
    _fetch(root, item, paths.official_minecraft())
    return root / item.path


def java_component(version: str) -> str:
    vj = json.loads((paths.minecraft() / "versions" / version / f"{version}.json").read_text(encoding="utf-8"))
    return vj.get("javaVersion", {}).get("component", "java-runtime-epsilon")


def java_major_of(home: Path) -> int | None:
    """The major version of the Java at `home`, from its `release` file (nothing is run)."""
    try:
        text = (home / "release").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("JAVA_VERSION="):
            version = line.split("=", 1)[1].strip().strip('"')
            head = version.split(".")[0]
            if head == "1":  # 1.8.0_...
                head = version.split(".")[1]
            try:
                return int(head)
            except ValueError:
                return None
    return None


def find_java(major: int) -> Path | None:
    """A Java `major` already on this computer: settings.json's java_home, JAVA_HOME, then the installed JDKs."""
    from . import settings

    candidates = []
    for value in (settings.load().get("java_home"), os.environ.get("JAVA_HOME")):
        if value:
            candidates.append(Path(value))
    if sys.platform == "darwin":
        for root in (Path("/Library/Java/JavaVirtualMachines"), Path.home() / "Library/Java/JavaVirtualMachines"):
            if root.is_dir():
                candidates += sorted((p / "Contents" / "Home" for p in root.iterdir()), reverse=True)
    elif sys.platform == "win32":
        for env in ("ProgramFiles", "ProgramW6432"):
            base = os.environ.get(env)
            if base:
                for vendor in ("Eclipse Adoptium", "Java", "Microsoft", "Zulu", "BellSoft"):
                    root = Path(base) / vendor
                    if root.is_dir():
                        candidates += sorted(root.iterdir(), reverse=True)
    else:
        root = Path("/usr/lib/jvm")
        if root.is_dir():
            candidates += sorted(root.iterdir(), reverse=True)
    java = "java.exe" if sys.platform == "win32" else "java"
    for home in candidates:
        if (home / "bin" / java).is_file() and java_major_of(home) == major:
            return home
    return None


def java_home(component: str, progress: Progress, major: int | None = None) -> Path:
    """A Java for preparing: one of `major` already installed, else Mojang's `component`, downloaded once."""
    if major is not None:
        found = find_java(major)
        if found:
            progress(f"Java {major}: {found}", None)
            return found
    dest = paths.runtime() / component
    marker = dest / ".honoka-complete"
    if not marker.is_file():
        progress("Скачиваю Java…", None)
        index = net.get_json(JAVA_RUNTIMES)
        builds = index.get(java_platform(), {}).get(component) or []
        if not builds:
            raise RuntimeError(f"У Mojang нет Java {component} для этой системы.")
        manifest = net.get_json(builds[0]["manifest"]["url"])
        files, links = [], []
        for name, entry in manifest["files"].items():
            target = dest / name
            if entry["type"] == "directory":
                target.mkdir(parents=True, exist_ok=True)
            elif entry["type"] == "file":
                raw = entry["downloads"]["raw"]
                files.append((Needed(Path(name), raw["sha1"], raw["url"]), entry.get("executable", False)))
            elif entry["type"] == "link":
                links.append((target, entry["target"]))
        _fetch_all(dest, [f for f, _ in files], "Скачиваю Java…", progress)
        if sys.platform != "win32":
            for item, executable in files:
                if executable:
                    (dest / item.path).chmod(0o755)
            for target, link in links:
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(link, target)
        marker.write_text(builds[0]["version"]["name"])
    java = "java.exe" if sys.platform == "win32" else "java"
    for candidate in (dest, dest / "jre.bundle" / "Contents" / "Home"):
        if (candidate / "bin" / java).is_file():
            return candidate
    for found in dest.rglob(java):
        if found.parent.name == "bin":
            return found.parent.parent
    raise RuntimeError("Java скачалась не полностью: удалите папку runtime и попробуйте снова.")
