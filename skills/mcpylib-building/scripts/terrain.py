#!/usr/bin/env python3
"""Generate terrain from value noise or a grayscale heightmap with MCPyLib.

  python terrain.py --at 1000 -500 --size 96 96 --base-y 64 --amplitude 14 --seed 7
  python terrain.py --at 1000 -500 --size 96 96 --heightmap hills.png --survey
  python terrain.py ... --apply --allow-overwrite

--at X Z is the north-west (minimum) corner. Surface heights span
base-y +/- amplitude. With --edge-blend (default 8), heights fade to base-y at
the border so the area meets flat ground, and lakes (below --water-level,
default base-y - 4) stay away from the edges.

This is a landscaping tool: it rewrites whole columns from the soil floor up
to the surface, and sets cells above the surface (up to --clear-above blocks)
to air to remove old hills. So --apply also needs --allow-overwrite. It streams
chunk-aligned tiles, writing an undo file as it goes (restore with undo.py).
Water is placed as still water: if a block update reaches the area border,
water there can start to flow.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import buildkit as bk


def _hash01(ix: int, iz: int, seed: int) -> float:
    h = (ix * 374761393 + iz * 668265263 + seed * 2246822519) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return (h ^ (h >> 16)) / 0xFFFFFFFF


def value_noise(x: float, z: float, seed: int) -> float:
    ix, iz = math.floor(x), math.floor(z)
    fx, fz = x - ix, z - iz
    sx, sz = fx * fx * (3 - 2 * fx), fz * fz * (3 - 2 * fz)
    a = _hash01(ix, iz, seed) + (_hash01(ix + 1, iz, seed) - _hash01(ix, iz, seed)) * sx
    b = _hash01(ix, iz + 1, seed) + (_hash01(ix + 1, iz + 1, seed) - _hash01(ix, iz + 1, seed)) * sx
    return a + (b - a) * sz


def fbm(x: float, z: float, seed: int, octaves: int) -> float:
    total, amp, freq, norm = 0.0, 1.0, 1.0, 0.0
    for o in range(octaves):
        total += amp * value_noise(x * freq, z * freq, seed + o * 1013)
        norm += amp
        amp *= 0.5
        freq *= 2.0
    return total / norm  # 0..1


def normalized_heights(args, w: int, d: int) -> list[list[float]]:
    """n[x][z] in 0..1 from a heightmap or noise."""
    if args.heightmap:
        from pixel_art import load_rgba, resize
        iw, ih, rows = load_rgba(args.heightmap)
        px = resize(iw, ih, rows, w, d)  # px[z][x]
        return [[(0.299 * px[z][x][0] + 0.587 * px[z][x][1] + 0.114 * px[z][x][2]) / 255
                 for z in range(d)] for x in range(w)]
    return [[fbm(x / args.scale, z / args.scale, args.seed, args.octaves)
             for z in range(d)] for x in range(w)]


def surface_heights(args, w: int, d: int) -> list[list[int]]:
    n = normalized_heights(args, w, d)
    out = []
    for x in range(w):
        col = []
        for z in range(d):
            v = n[x][z]
            if args.edge_blend > 0:
                t = min(1.0, min(x, z, w - 1 - x, d - 1 - z) / args.edge_blend)
                t = t * t * (3 - 2 * t)
                v = 0.5 + (v - 0.5) * t
            col.append(args.base_y + round((v - 0.5) * 2 * args.amplitude))
        out.append(col)
    return out


def column_block(y: int, h: int, slope: int, args, water: int | None):
    if y < h - 3:
        return args.stone
    shore = water is not None and h <= water + 1
    if y < h:
        return args.beach if shore else args.soil
    if y == h:
        if water is not None and h < water:
            return args.underwater
        if shore:
            return args.beach
        if slope >= 4:
            return args.stone
        return args.snow if h >= args.snow_line else args.top
    if water is not None and y <= water:
        return "water"
    return None if args.keep_above else "air"


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate terrain with MCPyLib.")
    ap.add_argument("--at", type=int, nargs=2, required=True, metavar=("X", "Z"),
                    help="minimum (north-west) corner")
    ap.add_argument("--size", type=int, nargs=2, default=(64, 64), metavar=("W", "D"))
    ap.add_argument("--base-y", type=int, default=64, help="mid level and edge level")
    ap.add_argument("--amplitude", type=int, default=12, help="surface spans base-y +/- this")
    ap.add_argument("--heightmap", help="grayscale PNG (black = lowest, white = highest)")
    ap.add_argument("--scale", type=float, default=40.0, help="noise feature size in blocks")
    ap.add_argument("--octaves", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--edge-blend", type=int, default=8, help="blocks over which edges fade to base-y")
    ap.add_argument("--water-level", type=int, help="default base-y - 4; use --no-water to disable")
    ap.add_argument("--no-water", action="store_true")
    ap.add_argument("--snow-line", type=int, help="default base-y + 0.75 * amplitude")
    ap.add_argument("--depth", type=int, default=4, help="layers written below the lowest surface")
    ap.add_argument("--clear-above", type=int, default=8, help="air layers written above the surface")
    ap.add_argument("--keep-above", action="store_true", help="don't write air above the surface")
    ap.add_argument("--top", default="grass_block")
    ap.add_argument("--soil", default="dirt")
    ap.add_argument("--stone", default="stone")
    ap.add_argument("--beach", default="sand")
    ap.add_argument("--underwater", default="gravel")
    ap.add_argument("--snow", default="snow_block")
    ap.add_argument("--survey", action="store_true", help="dry run: also read the world and count changes")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--allow-overwrite", action="store_true")
    ap.add_argument("--max-cells", type=int, default=65536)
    ap.add_argument("--undo-dir", default="mcpylib-undo")
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    w, d = args.size
    x0, z0 = args.at
    water = None if args.no_water else (args.water_level if args.water_level is not None
                                        else args.base_y - 4)
    if args.snow_line is None:
        args.snow_line = args.base_y + round(0.75 * args.amplitude)
    heights = surface_heights(args, w, d)

    def slope(x: int, z: int) -> int:
        h = heights[x][z]
        return max(abs(h - heights[nx][nz]) for nx, nz in
                   ((x - 1, z), (x + 1, z), (x, z - 1), (x, z + 1)) if 0 <= nx < w and 0 <= nz < d)

    lo = min(min(c) for c in heights)
    hi = max(max(c) for c in heights)
    top_world = max(hi, water if water is not None else hi) + (0 if args.keep_above else args.clear_above)
    floor_world = lo - args.depth
    if floor_world < bk.Y_MIN or top_world > bk.Y_MAX:
        sys.exit(f"Columns span Y {floor_world}..{top_world}, outside {bk.Y_MIN}..{bk.Y_MAX}; "
                 "adjust --base-y/--amplitude/--clear-above.")
    if water is not None and (args.edge_blend <= 0 or water >= args.base_y):
        print("WARNING: water can reach the area border (edges sit at base-y unless --edge-blend 0); "
              "it may flow out when a block update happens there.")

    tiles = []
    for ax, bx in bk_aligned(x0, x0 + w - 1):
        for az, bz in bk_aligned(z0, z0 + d - 1):
            hs = [heights[x - x0][z - z0] for x in range(ax, bx + 1) for z in range(az, bz + 1)]
            t_floor = min(hs) - args.depth
            t_top = max(max(hs), water if water is not None else -10**9) + \
                (0 if args.keep_above else args.clear_above)
            height = max(1, args.max_cells // ((bx - ax + 1) * (bz - az + 1)))
            y = t_floor
            while y <= t_top:
                top = min(t_top, y + height - 1)
                tiles.append((ax, y, az, bx, top, bz))
                y = top + 1
    cells = sum((b[3] - b[0] + 1) * (b[4] - b[1] + 1) * (b[5] - b[2] + 1) for b in tiles)
    print(f"Terrain {w}x{d} at x {x0}..{x0 + w - 1}, z {z0}..{z0 + d - 1}: surface Y {lo}..{hi}, "
          f"water {water if water is not None else 'none'}, columns Y {floor_world}..{top_world}")
    print(f"  {len(tiles)} edit() batches, up to {cells:,} cells; estimated "
          f"{len(tiles) * 0.15 + cells / 150000:.0f}s to apply")

    if not args.apply and not args.survey:
        print("Dry run (no world access). Add --survey to count what would change, "
              "or --apply --allow-overwrite to build.")
        return 0
    if args.apply and not args.allow_overwrite:
        print("REFUSED: terrain rewrites whole columns. Confirm the area with the user, "
              "then add --allow-overwrite.")
        return 2

    replaced, changed, placed = Counter(), 0, 0
    undo_fh = None
    with bk.connect(args) as mc:
        if args.apply:
            folder = Path(args.undo_dir)
            folder.mkdir(parents=True, exist_ok=True)
            undo_path = folder / f"undo-terrain-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
            undo_fh = undo_path.open("w", encoding="utf-8")
            undo_fh.write(json.dumps({"format": bk.UNDO_FORMAT, "label": "terrain",
                                      "created": datetime.now(timezone.utc).isoformat(),
                                      "note": "records [x, y, z, previous_type, placed_type]"}) + "\n")
        started = time.time()
        try:
            for n, (ax, ay, az, bx, by, bz) in enumerate(tiles, 1):
                current = mc.getblocks(ax, ay, az, bx, by, bz)
                sx, sy, sz = bx - ax + 1, by - ay + 1, bz - az + 1
                blocks = [[[None] * sz for _ in range(sy)] for _ in range(sx)]
                rows = []
                for dx in range(sx):
                    for dz in range(sz):
                        lx, lz = ax + dx - x0, az + dz - z0
                        h, sl = heights[lx][lz], slope(lx, lz)
                        for dy in range(sy):
                            new = column_block(ay + dy, h, sl, args, water)
                            if new is None:
                                continue
                            now = current[dx][dy][dz]
                            if bk.block_id(new) == now:
                                continue
                            changed += 1
                            if now not in bk.AIR:
                                replaced[now] += 1
                            blocks[dx][dy][dz] = new
                            rows.append([ax + dx, ay + dy, az + dz, now, bk.block_id(new)])
                if args.apply and rows:
                    undo_fh.write(json.dumps({"cells": rows}) + "\n")
                    placed += mc.edit(ax, ay, az, blocks)
                if n % 25 == 0 or n == len(tiles):
                    print(f"  {n}/{len(tiles)} batches, {changed:,} changes, {time.time() - started:.0f}s")
        finally:
            if undo_fh:
                undo_fh.close()
    print(f"{'Placed' if args.apply else 'Would change'} {placed if args.apply else changed:,} cells; "
          f"existing non-air replaced: {sum(replaced.values()):,} "
          f"({bk.describe(replaced)})")
    if args.apply:
        print(f"Undo: python undo.py {undo_path} --apply")
    return 0


def bk_aligned(a: int, b: int):
    """Split a..b (inclusive) at chunk borders."""
    start = a
    while start <= b:
        end = min(b, (start // 16) * 16 + 15)
        yield start, end
        start = end + 1


if __name__ == "__main__":
    sys.exit(main())
