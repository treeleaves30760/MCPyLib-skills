#!/usr/bin/env python3
"""Save, compare and restore a box of blocks with MCPyLib (read-before-write safety).

    python snapshot.py save X1 Y1 Z1 X2 Y2 Z2 [-o backup.json]
    python snapshot.py diff backup.json
    python snapshot.py restore backup.json [--apply] [--all]

Corners are inclusive and may be given in any order. Reads and writes are split
into chunk-aligned pieces of at most --max-cells cells (default 65536).

Limits (MCPyLib 1.2.0): getblocks() returns block *types* only, so a restore
puts back the right blocks but default states (stair/log orientation, door
halves) and no container contents or sign text. restore only writes cells that
differ from the snapshot unless --all is given, and is a dry run unless --apply.

Connection settings: MCPYLIB_HOST / MCPYLIB_PORT / MCPYLIB_TOKEN (or SERVER_IP /
SERVER_PORT / SERVER_TOKEN) from the environment or ./.env, or --host/--port.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

Y_MIN, Y_MAX = -64, 319
FORMAT = "mcpylib-snapshot/1"


# ---------------------------------------------------------------- connection

def load_env_file(path: str = ".env") -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None
    if load_dotenv is not None:
        load_dotenv(path, override=False)
        return
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        os.environ.setdefault(key, value)


def connect(args):
    from mcpylib import MCPyLib
    load_env_file()
    env = os.environ.get
    host = args.host or env("MCPYLIB_HOST") or env("SERVER_IP") or "127.0.0.1"
    port = args.port or int(env("MCPYLIB_PORT") or env("SERVER_PORT") or 65535)
    token = env("MCPYLIB_TOKEN") or env("SERVER_TOKEN") or ""
    if not token:
        sys.exit("No token: set MCPYLIB_TOKEN (see '/mcpylib token').")
    return MCPyLib(ip=host, port=port, token=token, timeout=args.timeout)


# ---------------------------------------------------------------- geometry

def aligned_ranges(a: int, b: int):
    """Split the inclusive range a..b at chunk borders (multiples of 16)."""
    start = a
    while start <= b:
        end = min(b, (start // 16) * 16 + 15)
        yield start, end
        start = end + 1


def sub_boxes(box, max_cells: int):
    """Yield inclusive sub-boxes (x1, y1, z1, x2, y2, z2) of at most max_cells cells."""
    x1, y1, z1, x2, y2, z2 = box
    if (x2 - x1 + 1) * (y2 - y1 + 1) * (z2 - z1 + 1) <= max_cells:
        yield box
        return
    for ax, bx in aligned_ranges(x1, x2):
        for az, bz in aligned_ranges(z1, z2):
            height = max(1, max_cells // ((bx - ax + 1) * (bz - az + 1)))
            y = y1
            while y <= y2:
                top = min(y2, y + height - 1)
                yield ax, y, az, bx, top, bz
                y = top + 1


def normalize_box(c):
    x1, y1, z1, x2, y2, z2 = c
    return (min(x1, x2), min(y1, y2), min(z1, z2), max(x1, x2), max(y1, y2), max(z1, z2))


# ---------------------------------------------------------------- snapshot I/O

class Volume:
    """Block types of an inclusive box, stored flat in x -> y -> z order."""

    def __init__(self, box):
        self.box = box
        x1, y1, z1, x2, y2, z2 = box
        self.size = (x2 - x1 + 1, y2 - y1 + 1, z2 - z1 + 1)
        self.types: list[str | None] = [None] * (self.size[0] * self.size[1] * self.size[2])

    def index(self, x, y, z) -> int:
        x1, y1, z1 = self.box[:3]
        sx, sy, sz = self.size
        return ((x - x1) * sy + (y - y1)) * sz + (z - z1)

    def read_from(self, mc, max_cells: int) -> None:
        for sb in sub_boxes(self.box, max_cells):
            data = mc.getblocks(*sb)
            for dx, plane in enumerate(data):
                for dy, row in enumerate(plane):
                    for dz, block in enumerate(row):
                        self.types[self.index(sb[0] + dx, sb[1] + dy, sb[2] + dz)] = block

    def to_json(self) -> dict:
        palette: dict[str, int] = {}
        rle: list[int] = []
        prev, run = None, 0
        for t in self.types:
            idx = palette.setdefault(t, len(palette))
            if idx == prev:
                run += 1
            else:
                if prev is not None:
                    rle += [run, prev]
                prev, run = idx, 1
        if prev is not None:
            rle += [run, prev]
        return {"format": FORMAT, "created": datetime.now(timezone.utc).isoformat(),
                "box": list(self.box), "palette": list(palette), "rle": rle,
                "note": "block types only; states, container contents and sign text are not stored"}

    @classmethod
    def from_json(cls, doc: dict) -> "Volume":
        if doc.get("format") != FORMAT:
            raise SystemExit(f"Not a {FORMAT} file.")
        vol = cls(tuple(doc["box"]))
        palette, rle, out = doc["palette"], doc["rle"], []
        for i in range(0, len(rle), 2):
            out.extend([palette[rle[i + 1]]] * rle[i])
        if len(out) != len(vol.types):
            raise SystemExit("Snapshot is corrupt (cell count mismatch).")
        vol.types = out
        return vol


# ---------------------------------------------------------------- commands

def cmd_save(mc, args) -> int:
    box = normalize_box((args.x1, args.y1, args.z1, args.x2, args.y2, args.z2))
    if box[1] < Y_MIN or box[4] > Y_MAX:
        print(f"Warning: Y outside {Y_MIN}..{Y_MAX}; those cells read as minecraft:void_air.")
    vol = Volume(box)
    started = time.time()
    vol.read_from(mc, args.max_cells)
    out = Path(args.output or f"snapshot_{box[0]}_{box[1]}_{box[2]}_{int(time.time())}.json")
    out.write_text(json.dumps(vol.to_json()), encoding="utf-8")
    counts = Counter(vol.types)
    top = ", ".join(f"{b} x{n}" for b, n in counts.most_common(5))
    print(f"Saved {len(vol.types):,} cells of box {box} to {out} in {time.time() - started:.1f}s")
    print(f"Most common: {top}")
    return 0


def changed_cells(mc, vol: Volume, max_cells: int):
    """Return {(x, y, z): (saved, current)} for cells that differ from the world."""
    current = Volume(vol.box)
    current.read_from(mc, max_cells)
    x1, y1, z1 = vol.box[:3]
    sx, sy, sz = vol.size
    diffs = {}
    for i, (saved, now) in enumerate(zip(vol.types, current.types)):
        if saved != now:
            dx, rest = divmod(i, sy * sz)
            dy, dz = divmod(rest, sz)
            diffs[(x1 + dx, y1 + dy, z1 + dz)] = (saved, now)
    return diffs


def cmd_diff(mc, args) -> int:
    vol = Volume.from_json(json.loads(Path(args.file).read_text(encoding="utf-8")))
    diffs = changed_cells(mc, vol, args.max_cells)
    print(f"{len(diffs):,} of {len(vol.types):,} cells differ from the snapshot.")
    for (saved, now), n in Counter(diffs.values()).most_common(10):
        print(f"  {saved} -> {now}: {n}")
    return 0


def cmd_restore(mc, args) -> int:
    vol = Volume.from_json(json.loads(Path(args.file).read_text(encoding="utf-8")))
    if args.all:
        targets = {}
        x1, y1, z1 = vol.box[:3]
        sx, sy, sz = vol.size
        for i, t in enumerate(vol.types):
            dx, rest = divmod(i, sy * sz)
            dy, dz = divmod(rest, sz)
            targets[(x1 + dx, y1 + dy, z1 + dz)] = t
    else:
        targets = {pos: saved for pos, (saved, _now) in changed_cells(mc, vol, args.max_cells).items()}
    print(f"Restore would write {len(targets):,} cells in box {vol.box}.")
    if not targets:
        return 0
    if not args.apply:
        print("Dry run. Re-run with --apply to write them.")
        return 0
    written = 0
    for sb in sub_boxes(vol.box, args.max_cells):
        bx1, by1, bz1, bx2, by2, bz2 = sb
        sx, sy, sz = bx2 - bx1 + 1, by2 - by1 + 1, bz2 - bz1 + 1
        blocks = [[[targets.get((bx1 + dx, by1 + dy, bz1 + dz)) for dz in range(sz)]
                   for dy in range(sy)] for dx in range(sx)]
        if any(c is not None for plane in blocks for row in plane for c in row):
            written += mc.edit(bx1, by1, bz1, blocks)
    print(f"Restored {written:,} cells (types only).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--max-cells", type=int, default=65536)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("save", help="read a box and write it to a JSON snapshot")
    for corner in ("x1", "y1", "z1", "x2", "y2", "z2"):  # separate positionals: a tuple
        s.add_argument(corner, type=int)                 # metavar breaks --help
    s.add_argument("-o", "--output")
    d = sub.add_parser("diff", help="compare a snapshot with the current world")
    d.add_argument("file")
    r = sub.add_parser("restore", help="write a snapshot back (dry run unless --apply)")
    r.add_argument("file")
    r.add_argument("--apply", action="store_true", help="actually write blocks")
    r.add_argument("--all", action="store_true", help="write every cell, not only changed ones")
    args = ap.parse_args()

    with connect(args) as mc:
        return {"save": cmd_save, "diff": cmd_diff, "restore": cmd_restore}[args.cmd](mc, args)


if __name__ == "__main__":
    sys.exit(main())
