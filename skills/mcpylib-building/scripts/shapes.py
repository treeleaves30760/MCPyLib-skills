#!/usr/bin/env python3
"""Generate and place geometric shapes with MCPyLib (dry run unless --apply).

Shapes: sphere, dome, cylinder, cone, pyramid, torus, box. Each sits on the base
level: --at X Y Z is the centre of the footprint at height Y, or use
--player NAME to build in front of a player.

Examples
  python shapes.py sphere --radius 8 --block glass --hollow --player Steve
  python shapes.py dome --radius 12 --block white_concrete --hollow --at 100 64 200 --apply
  python shapes.py cylinder --radius 5 --height 12 --block stone_bricks --hollow --capped --player Steve
  python shapes.py pyramid --base 21 --block sandstone --stairs sandstone_stairs --at 0 70 0
  python shapes.py torus --major 10 --minor 3 --block purple_concrete --player Steve

Safety: the script first reads the target area. It refuses to replace
existing non-air blocks unless --allow-overwrite is given, and writes an undo
file before building (restore with undo.py).
"""
from __future__ import annotations

import argparse
import math
import sys

import buildkit as bk


def sphere(r: int, block: str, hollow: bool, t: int) -> bk.Grid:
    g = bk.Grid()
    outer, inner = (r + 0.5) ** 2, (r - t + 0.5) ** 2
    for x in range(-r, r + 1):
        for y in range(-r, r + 1):
            for z in range(-r, r + 1):
                d2 = x * x + y * y + z * z
                if d2 <= outer and not (hollow and d2 <= inner):
                    g.set(x, y + r, z, block)
    return g


def dome(r: int, block: str, hollow: bool, t: int) -> bk.Grid:
    g = bk.Grid()
    outer, inner = (r + 0.5) ** 2, (r - t + 0.5) ** 2
    for x in range(-r, r + 1):
        for y in range(0, r + 1):
            for z in range(-r, r + 1):
                d2 = x * x + y * y + z * z
                if d2 <= outer and not (hollow and d2 <= inner):
                    g.set(x, y, z, block)
    return g


def cylinder(r: int, h: int, block: str, hollow: bool, t: int, capped: bool) -> bk.Grid:
    g = bk.Grid()
    for dx, dz, d in bk.disk_cells(r):
        shell = d > r - t + 0.5
        for y in range(h):
            if not hollow or shell or (capped and y in (0, h - 1)):
                g.set(dx, y, dz, block)
    return g


def cone(r: int, h: int, block: str, hollow: bool, t: int) -> bk.Grid:
    g = bk.Grid()
    for y in range(h):
        ry = r * (1 - y / h)
        for dx, dz, d in bk.disk_cells(ry):
            if not hollow or d > ry - t + 0.5 or y == 0:
                g.set(dx, y, dz, block)
    return g


def pyramid(base: int, block: str, hollow: bool, stairs: str | None) -> bk.Grid:
    g = bk.Grid()
    half = (base - 1) // 2
    for level in range(half + 1):
        s = half - level
        for x in range(-s, s + 1):
            for z in range(-s, s + 1):
                edge = abs(x) == s or abs(z) == s
                if hollow and not edge and level > 0:
                    continue
                cell = block
                corner = abs(x) == s and abs(z) == s
                if stairs and edge and not corner and s > 0:
                    # The stair's full side faces the centre, so the steps climb inward.
                    facing = ("west" if x == s else "east" if x == -s
                              else "north" if z == s else "south")
                    cell = bk.stair(stairs, facing)
                g.set(x, level, z, cell)
    return g


def torus(major: int, minor: int, block: str) -> bk.Grid:
    g = bk.Grid()
    lim = (minor + 0.5) ** 2
    reach = major + minor + 1
    for x in range(-reach, reach + 1):
        for z in range(-reach, reach + 1):
            ring = math.hypot(x, z) - major
            for y in range(-minor, minor + 1):
                if ring * ring + y * y <= lim:
                    g.set(x, y + minor, z, block)
    return g


def box(sx: int, sy: int, sz: int, block: str, hollow: bool) -> bk.Grid:
    g = bk.Grid()
    x0, z0 = -(sx // 2), -(sz // 2)
    g.box(x0, 0, z0, x0 + sx - 1, sy - 1, z0 + sz - 1, block, hollow=hollow)
    return g


def main() -> int:
    ap = argparse.ArgumentParser(description="Place geometric shapes with MCPyLib.")
    sub = ap.add_subparsers(dest="shape", required=True)

    def new(name, help_text):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--block", default="stone", help="block id (default stone)")
        bk.add_common_args(p, orientable=False)
        return p

    p = new("sphere", "ball resting on the base level")
    p.add_argument("--radius", type=int, required=True)
    p.add_argument("--hollow", action="store_true")
    p.add_argument("--thickness", type=int, default=1)
    p = new("dome", "upper half sphere")
    p.add_argument("--radius", type=int, required=True)
    p.add_argument("--hollow", action="store_true")
    p.add_argument("--thickness", type=int, default=1)
    p = new("cylinder", "vertical cylinder")
    p.add_argument("--radius", type=int, required=True)
    p.add_argument("--height", type=int, required=True)
    p.add_argument("--hollow", action="store_true")
    p.add_argument("--thickness", type=int, default=1)
    p.add_argument("--capped", action="store_true", help="with --hollow: add floor and roof")
    p = new("cone", "cone narrowing upwards")
    p.add_argument("--radius", type=int, required=True)
    p.add_argument("--height", type=int, required=True)
    p.add_argument("--hollow", action="store_true")
    p.add_argument("--thickness", type=int, default=1)
    p = new("pyramid", "square stepped pyramid")
    p.add_argument("--base", type=int, required=True, help="side length (odd works best)")
    p.add_argument("--hollow", action="store_true")
    p.add_argument("--stairs", help="stairs block for smooth sides, e.g. sandstone_stairs")
    p = new("torus", "ring lying flat")
    p.add_argument("--major", type=int, required=True, help="ring radius")
    p.add_argument("--minor", type=int, required=True, help="tube radius")
    p = new("box", "cuboid, optionally hollow")
    p.add_argument("--size", type=int, nargs=3, required=True, metavar=("SX", "SY", "SZ"))
    p.add_argument("--hollow", action="store_true")
    args = ap.parse_args()

    if args.shape == "sphere":
        grid = sphere(args.radius, args.block, args.hollow, args.thickness)
    elif args.shape == "dome":
        grid = dome(args.radius, args.block, args.hollow, args.thickness)
    elif args.shape == "cylinder":
        grid = cylinder(args.radius, args.height, args.block, args.hollow, args.thickness, args.capped)
    elif args.shape == "cone":
        grid = cone(args.radius, args.height, args.block, args.hollow, args.thickness)
    elif args.shape == "pyramid":
        grid = pyramid(args.base, args.block, args.hollow, args.stairs)
    elif args.shape == "torus":
        grid = torus(args.major, args.minor, args.block)
    else:
        grid = box(*args.size, args.block, args.hollow)

    with bk.connect(args) as mc:
        anchor, turns = bk.resolve_placement(mc, args, grid)
        build = bk.Build.from_grid(grid, anchor, turns, label=args.shape)
        return bk.execute(mc, build, args)


if __name__ == "__main__":
    sys.exit(main())
