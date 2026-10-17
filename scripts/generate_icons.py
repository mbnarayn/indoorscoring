"""Generate the PWA PNG icons and iOS splash image without third-party dependencies.

Usage: python scripts/generate_icons.py
"""

import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"
BG = (11, 61, 46)
BALL = (198, 40, 40)
SEAM = (255, 255, 255)


def write_png(path: Path, width: int, height: int, pixel) -> None:
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            rows.extend(pixel(x, y))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(rows), 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def ball_pixel(cx: float, cy: float, r: float):
    seam_offset = r * 1.55
    seam_radius = r * 1.25
    seam_width = max(1.0, r * 0.035)

    def pixel(x: int, y: int):
        dx, dy = x + 0.5 - cx, y + 0.5 - cy
        if dx * dx + dy * dy > r * r:
            return BG
        for side in (-1, 1):
            d = math.hypot(dx - side * seam_offset, dy)
            if abs(d - seam_radius) < seam_width:
                return SEAM
        return BALL

    return pixel


def icon(size: int, ball_ratio: float, name: str) -> None:
    write_png(OUT / name, size, size, ball_pixel(size / 2, size / 2, size * ball_ratio))


def splash(width: int, height: int, name: str) -> None:
    write_png(OUT / name, width, height, ball_pixel(width / 2, height / 2, width * 0.18))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    icon(192, 0.36, "icon-192.png")
    icon(512, 0.36, "icon-512.png")
    icon(512, 0.30, "icon-maskable-512.png")  # stays inside the maskable safe zone
    icon(180, 0.36, "apple-touch-icon.png")
    splash(1170, 2532, "splash-1170x2532.png")
    print(f"Icons written to {OUT}")
