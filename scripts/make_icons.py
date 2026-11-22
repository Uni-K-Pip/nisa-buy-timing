from pathlib import Path
import struct
import zlib

OUT = Path(__file__).resolve().parents[1] / "site/icons"


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def pixel(x, y):
    background = (15, 37, 57)
    line = (106, 233, 199)
    grid = (56, 91, 111)
    points = [(0.24, 0.40), (0.40, 0.59), (0.55, 0.51), (0.68, 0.64), (0.78, 0.35)]
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        dx, dy = x2 - x1, y2 - y1
        t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
        if (x - x1 - t * dx) ** 2 + (y - y1 - t * dy) ** 2 <= 0.022 ** 2:
            return line
    if 0.23 <= x <= 0.79 and any(abs(y - k) < 0.005 for k in (0.36, 0.52, 0.68)):
        return grid
    return background


def png(size):
    rows = bytearray()
    for row in range(size):
        rows.append(0)
        for column in range(size):
            rows.extend(pixel((column + 0.5) / size, (row + 0.5) / size))
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return bytes.fromhex("89504e470d0a1a0a") + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size in (("icon-192.png", 192), ("icon-512.png", 512), ("apple-touch-icon.png", 180)):
        (OUT / name).write_bytes(png(size))


if __name__ == "__main__":
    main()
