#!/usr/bin/env python3
"""Turn an image into Minecraft pixel art with MCPyLib (dry run unless --apply).

  python pixel_art.py logo.png --width 64 --player Steve
  python pixel_art.py photo.png --width 96 --palette full --dither --plane wall --at 0 70 0 --apply
  python pixel_art.py map.png --width 128 --plane floor --palette concrete --player Steve

PNG files are read with the built-in decoder (pure Python). Other formats need
Pillow (pip install pillow), which is used whenever it is installed.

--plane wall  stands upright, facing the player or --front; image left
              appears on the viewer's left.
--plane floor lies flat at base level, with the image top farthest from the viewer.
Pixels with alpha < 128 are skipped (left unchanged) unless --background is set.
Block colours are approximate texture averages; check the result in game.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter

import buildkit as bk

# Approximate average texture colours (RGB) of solid, opaque blocks.
CONCRETE = {
    "white_concrete": (207, 213, 214), "orange_concrete": (224, 97, 1),
    "magenta_concrete": (169, 48, 159), "light_blue_concrete": (36, 137, 199),
    "yellow_concrete": (241, 175, 21), "lime_concrete": (94, 169, 24),
    "pink_concrete": (214, 101, 143), "gray_concrete": (55, 58, 62),
    "light_gray_concrete": (125, 125, 115), "cyan_concrete": (21, 119, 136),
    "purple_concrete": (100, 32, 156), "blue_concrete": (45, 47, 143),
    "brown_concrete": (96, 60, 32), "green_concrete": (73, 91, 36),
    "red_concrete": (142, 33, 33), "black_concrete": (8, 10, 15),
}
WOOL = {
    "white_wool": (234, 236, 237), "orange_wool": (241, 118, 20),
    "magenta_wool": (190, 69, 180), "light_blue_wool": (58, 175, 217),
    "yellow_wool": (249, 198, 40), "lime_wool": (112, 185, 26),
    "pink_wool": (238, 141, 172), "gray_wool": (63, 68, 72),
    "light_gray_wool": (142, 142, 135), "cyan_wool": (21, 138, 145),
    "purple_wool": (122, 42, 173), "blue_wool": (53, 57, 157),
    "brown_wool": (114, 72, 41), "green_wool": (85, 110, 28),
    "red_wool": (161, 39, 35), "black_wool": (21, 21, 26),
}
TERRACOTTA = {
    "terracotta": (152, 94, 68), "white_terracotta": (210, 178, 161),
    "orange_terracotta": (162, 84, 38), "magenta_terracotta": (150, 88, 109),
    "light_blue_terracotta": (113, 109, 138), "yellow_terracotta": (186, 133, 35),
    "lime_terracotta": (104, 118, 53), "pink_terracotta": (162, 78, 79),
    "gray_terracotta": (58, 42, 36), "light_gray_terracotta": (135, 107, 98),
    "cyan_terracotta": (87, 91, 91), "purple_terracotta": (118, 70, 86),
    "blue_terracotta": (74, 60, 91), "brown_terracotta": (77, 51, 36),
    "green_terracotta": (76, 83, 42), "red_terracotta": (143, 61, 47),
    "black_terracotta": (37, 23, 16),
}
PALETTES = {
    "concrete": CONCRETE, "wool": WOOL, "terracotta": TERRACOTTA,
    "full": {**CONCRETE, **WOOL, **TERRACOTTA},
}


def load_rgba(path: str):
    """Return (w, h, rows) with rows[y][x] = (r, g, b, a)."""
    try:
        from PIL import Image  # optional
    except ImportError:
        Image = None
    if Image is not None:
        img = Image.open(path).convert("RGBA")
        w, h = img.size
        px = img.load()
        return w, h, [[px[x, y] for x in range(w)] for y in range(h)]
    if not path.lower().endswith(".png"):
        sys.exit("Only PNG works without Pillow. Install it (pip install pillow) or convert to PNG.")
    from pngdecode import read_png
    return read_png(path)


def resize(w: int, h: int, rows, nw: int, nh: int):
    """Box-filter downscale (or nearest-neighbour upscale) in pure Python."""
    out = []
    for ty in range(nh):
        y0, y1 = ty * h // nh, max(ty * h // nh + 1, (ty + 1) * h // nh)
        row = []
        for tx in range(nw):
            x0, x1 = tx * w // nw, max(tx * w // nw + 1, (tx + 1) * w // nw)
            acc = [0, 0, 0, 0]
            n = 0
            for yy in range(y0, y1):
                for px in rows[yy][x0:x1]:
                    a = px[3]
                    acc[0] += px[0] * a
                    acc[1] += px[1] * a
                    acc[2] += px[2] * a
                    acc[3] += a
                    n += 1
            alpha = acc[3] / n if n else 0
            if acc[3]:
                row.append((acc[0] / acc[3], acc[1] / acc[3], acc[2] / acc[3], alpha))
            else:
                row.append((0.0, 0.0, 0.0, 0.0))
        out.append(row)
    return out


def redmean(c1, c2) -> float:
    rm = (c1[0] + c2[0]) / 2
    dr, dg, db = c1[0] - c2[0], c1[1] - c2[1], c1[2] - c2[2]
    return (2 + rm / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rm) / 256) * db * db


class Matcher:
    def __init__(self, palette: dict) -> None:
        self.items = list(palette.items())
        self.cache: dict[tuple[int, int, int], tuple[str, tuple]] = {}

    def nearest(self, rgb) -> tuple[str, tuple]:
        key = (int(rgb[0]) >> 2, int(rgb[1]) >> 2, int(rgb[2]) >> 2)
        hit = self.cache.get(key)
        if hit is None:
            hit = min(self.items, key=lambda kv: redmean(rgb, kv[1]))
            self.cache[key] = hit
        return hit


def to_blocks(pixels, matcher: Matcher, dither: bool, background: str | None):
    h, w = len(pixels), len(pixels[0])
    work = [[list(p) for p in row] for row in pixels]
    out = [[None] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            r, g, b, a = work[y][x]
            if a < 128:
                out[y][x] = background
                continue
            rgb = (min(255, max(0, r)), min(255, max(0, g)), min(255, max(0, b)))
            name, col = matcher.nearest(rgb)
            out[y][x] = name
            if dither:
                err = (rgb[0] - col[0], rgb[1] - col[1], rgb[2] - col[2])
                for dx, dy, f in ((1, 0, 7 / 16), (-1, 1, 3 / 16), (0, 1, 5 / 16), (1, 1, 1 / 16)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and ny < h and work[ny][nx][3] >= 128:
                        for c in range(3):
                            work[ny][nx][c] += err[c] * f
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Image to Minecraft pixel art with MCPyLib.")
    ap.add_argument("image")
    ap.add_argument("--width", type=int, default=64, help="width in blocks (height keeps aspect)")
    ap.add_argument("--height", type=int, help="override height in blocks")
    ap.add_argument("--palette", choices=sorted(PALETTES), default="concrete")
    ap.add_argument("--dither", action="store_true", help="Floyd-Steinberg dithering")
    ap.add_argument("--plane", choices=("wall", "floor"), default="wall")
    ap.add_argument("--background", help="block for transparent pixels (default: skip them)")
    bk.add_common_args(ap)
    args = ap.parse_args()

    w, h, rows = load_rgba(args.image)
    nw = max(1, args.width)
    nh = max(1, args.height or round(h * nw / w))
    pixels = resize(w, h, rows, nw, nh)
    blocks = to_blocks(pixels, Matcher(PALETTES[args.palette]), args.dither, args.background)

    grid = bk.Grid()
    for v, row in enumerate(blocks):
        for u, name in enumerate(row):
            if name is None:
                continue
            x = u - nw // 2
            if args.plane == "wall":
                grid.set(x, nh - 1 - v, 0, name)
            else:
                grid.set(x, 0, v - nh // 2, name)
    counts = Counter(n for row in blocks for n in row if n)
    print(f"Image {w}x{h} -> {nw}x{nh} blocks, {len(counts)} block types: "
          + ", ".join(f"{b} x{n}" for b, n in counts.most_common(6)))
    if not grid.cells:
        print("Image is fully transparent; nothing to place.")
        return 1

    with bk.connect(args) as mc:
        anchor, turns = bk.resolve_placement(mc, args, grid)
        build = bk.Build.from_grid(grid, anchor, turns, label="pixel-art")
        return bk.execute(mc, build, args)


if __name__ == "__main__":
    sys.exit(main())
