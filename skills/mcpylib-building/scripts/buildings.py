#!/usr/bin/env python3
"""Generate a house or a round tower and place it with MCPyLib (dry run unless --apply).

  python buildings.py house --width 9 --depth 7 --wall-height 4 --player Steve
  python buildings.py house --walls spruce_planks --roof-stairs dark_oak_stairs --at 100 64 200 --front east --apply
  python buildings.py tower --radius 4 --height 14 --top cone --player Steve --apply

The front (doorway) faces the player when --player is used, otherwise --front
(default south). Windows are full glass blocks, because panes placed by edit()
don't connect. The doorway is left open, because doors need block states that
MCPyLib 1.2.0 can't set. Torches are placed last with setblock() so their light
updates. The interior is cleared to air unless --no-clear is given.
"""
from __future__ import annotations

import argparse
import sys

import buildkit as bk


def house(w: int, d: int, h: int, mats: dict, clear: bool) -> bk.Grid:
    if w < 5 or d < 5 or h < 3:
        sys.exit("house needs --width >= 5, --depth >= 5, --wall-height >= 3")
    g = bk.Grid()
    x0, z0 = -(w // 2), -(d // 2)
    x1, z1 = x0 + w - 1, z0 + d - 1  # z1 is the front wall
    door_x = max(x0 + 1, min(x1 - 1, 0))
    g.box(x0, 0, z0, x1, 0, z1, mats["floor"])
    for y in range(1, h + 1):
        for x in range(x0, x1 + 1):
            for z in range(z0, z1 + 1):
                on_x, on_z = x in (x0, x1), z in (z0, z1)
                if on_x and on_z:
                    g.set(x, y, z, mats["corners"])
                elif on_x or on_z:
                    g.set(x, y, z, mats["walls"])
                elif clear:
                    g.set(x, y, z, "air")
    for y in (1, 2):
        g.set(door_x, y, z1, "air")
    for y in [2] + ([3] if h >= 4 else []):
        for z in range(z0 + 2, z1 - 1, 3):
            g.set(x0, y, z, mats["windows"])
            g.set(x1, y, z, mats["windows"])
        for x in range(x0 + 2, x1 - 1, 3):
            g.set(x, y, z0, mats["windows"])
            if abs(x - door_x) > 1:
                g.set(x, y, z1, mats["windows"])
    # Gable roof, ridge along X, one block of overhang. Layer i sits at y = h + i.
    front, back, level = z1 + 1, z0 - 1, 0
    while front > back:
        y = h + level
        for x in range(x0 - 1, x1 + 2):
            g.set(x, y, front, bk.stair(mats["roof_stairs"], "north"))  # rises toward the ridge
            g.set(x, y, back, bk.stair(mats["roof_stairs"], "south"))
        if level > 0:
            for z in range(back + 1, front):
                g.set(x0, y, z, mats["walls"])  # gable ends
                g.set(x1, y, z, mats["walls"])
                if clear:
                    for x in range(x0 + 1, x1):
                        g.set(x, y, z, "air")
        front, back, level = front - 1, back + 1, level + 1
    if front == back:
        for x in range(x0 - 1, x1 + 2):
            g.set(x, h + level, front, mats["roof_block"])
    for x, z in ((x0 + 1, z0 + 1), (x1 - 1, z0 + 1), (x0 + 1, z1 - 1), (x1 - 1, z1 - 1)):
        if (x, z) != (door_x, z1 - 1):
            g.set(x, 1, z, "torch", defer=True)
    return g


def tower(r: int, h: int, mats: dict, top: str, clear: bool) -> bk.Grid:
    if r < 2 or h < 4:
        sys.exit("tower needs --radius >= 2 and --height >= 4")
    g = bk.Grid()
    ring = set()
    for dx, dz, dist in bk.disk_cells(r):
        g.set(dx, 0, dz, mats["floor"])
        g.set(dx, h + 1, dz, mats["floor"])  # top platform
        if dist > r - 0.5:
            ring.add((dx, dz))
            for y in range(1, h + 1):
                g.set(dx, y, dz, mats["walls"])
        elif clear:
            for y in range(1, h + 1):
                g.set(dx, y, dz, "air")
    for y in (1, 2):
        g.set(0, y, r, "air")  # doorway in the front (+Z) wall
    for y in range(3, h, 4):
        for x, z in ((r, 0), (-r, 0), (0, -r)) + (((0, r),) if y >= 5 else ()):
            if (x, z) in ring:
                g.set(x, y, z, mats["windows"])
    for y in range(1, h + 2):  # ladder on the back wall, through the platform
        g.set(0, y, -(r - 1), {"block": "ladder", "block_state": {"facing": "south"}})
    if top == "battlements":
        for dx, dz in ring:
            if (dx + dz) % 2 == 0:
                g.set(dx, h + 2, dz, mats["walls"])
    else:
        rc = r + 1
        hc = max(3, round(rc * 1.5))
        for k in range(hc):
            ry = rc * (1 - k / hc)
            for dx, dz, dist in bk.disk_cells(ry):
                if dist > ry - 0.75:
                    g.set(dx, h + 2 + k, dz, mats["roof_block"])
    if r >= 3:
        g.set(r - 1, 1, 0, "torch", defer=True)
        g.set(-(r - 1), 1, 0, "torch", defer=True)
    return g


def main() -> int:
    ap = argparse.ArgumentParser(description="Place a house or tower with MCPyLib.")
    sub = ap.add_subparsers(dest="kind", required=True)

    p = sub.add_parser("house", help="rectangular house with a gable roof")
    p.add_argument("--width", type=int, default=9)
    p.add_argument("--depth", type=int, default=7)
    p.add_argument("--wall-height", type=int, default=4)
    p.add_argument("--floor", default="oak_planks")
    p.add_argument("--walls", default="oak_planks")
    p.add_argument("--corners", default="oak_log")
    p.add_argument("--windows", default="glass")
    p.add_argument("--roof-stairs", default="spruce_stairs")
    p.add_argument("--roof-block", default="spruce_planks")
    p.add_argument("--no-clear", action="store_true", help="don't clear the interior to air")
    bk.add_common_args(p)

    t = sub.add_parser("tower", help="round tower with battlements or a cone roof")
    t.add_argument("--radius", type=int, default=4)
    t.add_argument("--height", type=int, default=12)
    t.add_argument("--floor", default="spruce_planks")
    t.add_argument("--walls", default="stone_bricks")
    t.add_argument("--windows", default="glass")
    t.add_argument("--roof-block", default="dark_oak_planks")
    t.add_argument("--top", choices=("battlements", "cone"), default="battlements")
    t.add_argument("--no-clear", action="store_true")
    bk.add_common_args(t)
    args = ap.parse_args()

    mats = {k: getattr(args, k) for k in
            ("floor", "walls", "windows", "roof_block", "corners", "roof_stairs") if hasattr(args, k)}
    if args.kind == "house":
        grid = house(args.width, args.depth, args.wall_height, mats, not args.no_clear)
    else:
        grid = tower(args.radius, args.height, mats, args.top, not args.no_clear)

    with bk.connect(args) as mc:
        anchor, turns = bk.resolve_placement(mc, args, grid)
        build = bk.Build.from_grid(grid, anchor, turns, label=args.kind)
        return bk.execute(mc, build, args)


if __name__ == "__main__":
    sys.exit(main())
