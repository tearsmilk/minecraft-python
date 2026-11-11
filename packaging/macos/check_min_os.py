"""Fails when any Mach-O file in an app needs a macOS newer than the floor (default 11.0).

    python check_min_os.py Honoka.app [11.0]
"""

import struct
import sys
from pathlib import Path

FAT = (0xCAFEBABE, 0xCAFEBABF)
MH64 = 0xFEEDFACF
LC_BUILD_VERSION = 0x32
LC_VERSION_MIN_MACOSX = 0x24


def versions(data: bytes):
    """The minimum macOS of each architecture in a Mach-O (thin or fat)."""
    magic = struct.unpack(">I", data[:4])[0]
    if magic in FAT:
        count = struct.unpack(">I", data[4:8])[0]
        wide = magic == 0xCAFEBABF
        size = 32 if wide else 20
        for i in range(count):
            entry = data[8 + i * size: 8 + (i + 1) * size]
            offset = struct.unpack(">Q", entry[8:16])[0] if wide else struct.unpack(">I", entry[8:12])[0]
            yield from versions(data[offset:])
        return
    if struct.unpack("<I", data[:4])[0] != MH64:
        return
    ncmds = struct.unpack("<I", data[16:20])[0]
    off = 32
    for _ in range(ncmds):
        cmd, size = struct.unpack("<II", data[off:off + 8])
        if cmd == LC_BUILD_VERSION:
            yield struct.unpack("<I", data[off + 12:off + 16])[0]
        elif cmd == LC_VERSION_MIN_MACOSX:
            yield struct.unpack("<I", data[off + 8:off + 12])[0]
        off += size


def main() -> int:
    app = Path(sys.argv[1])
    major, minor = (int(p) for p in (sys.argv[2] if len(sys.argv) > 2 else "11.0").split("."))
    floor = (major << 16) | (minor << 8)
    checked, bad = 0, []
    for f in app.rglob("*"):
        if not f.is_file() or f.is_symlink():
            continue
        with open(f, "rb") as h:
            head = h.read(4)
        if len(head) < 4 or (struct.unpack(">I", head)[0] not in FAT and struct.unpack("<I", head)[0] != MH64):
            continue
        for v in versions(f.read_bytes()):
            checked += 1
            if v > floor:
                bad.append(f"{f.relative_to(app)} needs macOS {v >> 16}.{(v >> 8) & 255}")
    print(f"{checked} Mach-O slices checked")
    for b in bad:
        print("::error::" + b)
    return 1 if bad or not checked else 0


if __name__ == "__main__":
    sys.exit(main())
