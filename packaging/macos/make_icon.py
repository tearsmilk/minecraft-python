"""Draws Honoka's icon (a white H on a coral rounded square) as PNGs for iconutil, with no dependencies.

    python make_icon.py OUT.iconset
    iconutil -c icns OUT.iconset -o Honoka.icns
"""

import struct
import sys
import zlib
from pathlib import Path

CORAL = (240, 121, 90)
DARK = (22, 22, 29)
WHITE = (255, 255, 255)


def pixel(x: float, y: float) -> tuple:
    """The colour at (x, y) in a 0..1 square, RGBA."""
    margin, radius = 0.08, 0.2
    # Rounded square.
    cx = min(max(x, margin + radius), 1 - margin - radius)
    cy = min(max(y, margin + radius), 1 - margin - radius)
    if (x - cx) ** 2 + (y - cy) ** 2 > radius**2:
        return (0, 0, 0, 0)
    # A soft vertical gradient from coral to a darker coral.
    t = (y - margin) / (1 - 2 * margin)
    base = tuple(int(c * (1 - 0.25 * t) + d * 0.25 * t) for c, d in zip(CORAL, DARK))
    # The H: two posts and a bar.
    left = 0.30 <= x <= 0.42
    right = 0.58 <= x <= 0.70
    bar = 0.45 <= y <= 0.55 and 0.30 <= x <= 0.70
    if (0.26 <= y <= 0.74 and (left or right)) or bar:
        return (*WHITE, 255)
    return (*base, 255)


def png(size: int) -> bytes:
    rows = []
    for j in range(size):
        row = bytearray([0])
        for i in range(size):
            # 2x2 supersampling for smooth edges.
            samples = [pixel((i + dx) / size, (j + dy) / size) for dx in (0.25, 0.75) for dy in (0.25, 0.75)]
            row += bytes(sum(s[k] for s in samples) // 4 for k in range(4))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        (out / f"icon_{size}x{size}.png").write_bytes(png(size))
        (out / f"icon_{size}x{size}@2x.png").write_bytes(png(size * 2))


if __name__ == "__main__":
    main()
