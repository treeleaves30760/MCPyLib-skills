"""Shared helpers for the mcpylib-building scripts (pure Python, no numpy).

Model
  A Grid holds blocks at integer *local* offsets. Generators centre the
  footprint on x = 0, z = 0, put the base at y = 0 and make the front face local
  south (+Z). place_grid() rotates the grid, moves it to an anchor in the world,
  and runs the safe pipeline in execute():

    clip to Y -64..319 -> survey existing blocks with getblocks() -> plan
    -> (dry run stops here) -> refuse to replace non-air blocks unless
    --allow-overwrite -> write an undo file -> edit() in chunk-aligned batches
    -> setblock() for deferred blocks (light sources) so lighting updates.

Cells are block ids ("stone") or dicts {"block": id, "block_state": {...}}.
block_state takes any vanilla property of the block (plugin 1.2.1). Rotation
remaps facing, rotation (names or 0-15) and axis.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

Y_MIN, Y_MAX = -64, 319
AIR = frozenset({"minecraft:air", "minecraft:cave_air", "minecraft:void_air"})
CW = ("north", "east", "south", "west")  # clockwise as seen from above
VECTORS = {"north": (0, -1), "east": (1, 0), "south": (0, 1), "west": (-1, 0)}
ROT16 = ("south", "south_south_west", "south_west", "west_south_west", "west",
         "west_north_west", "north_west", "north_north_west", "north",
         "north_north_east", "north_east", "east_north_east", "east",
         "east_south_east", "south_east", "south_south_east")
UNDO_FORMAT = "mcpylib-undo/1"


# ---------------------------------------------------------------- connection

def load_env_file(path: str = ".env") -> None:
    """Load KEY=VALUE lines without overriding variables that are already set."""
    try:
        from dotenv import load_dotenv  # installed together with mcpylib
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
    """MCPyLib client from --host/--port and MCPYLIB_* (or SERVER_*) variables."""
    from mcpylib import MCPyLib
    load_env_file()
    env = os.environ.get
    host = args.host or env("MCPYLIB_HOST") or env("SERVER_IP") or "127.0.0.1"
    port = args.port or int(env("MCPYLIB_PORT") or env("SERVER_PORT") or 65535)
    token = env("MCPYLIB_TOKEN") or env("SERVER_TOKEN") or ""
    if not token:
        sys.exit("No token: set MCPYLIB_TOKEN (run '/mcpylib token' on the server).")
    return MCPyLib(ip=host, port=port, token=token, timeout=args.timeout)


def add_common_args(ap: argparse.ArgumentParser, orientable: bool = True) -> None:
    g = ap.add_argument_group("placement and safety")
    g.add_argument("--at", type=int, nargs=3, metavar=("X", "Y", "Z"),
                   help="centre of the footprint at base level Y")
    g.add_argument("--player", help="build in front of this online player instead of --at")
    g.add_argument("--gap", type=int, default=3, help="empty blocks between player and build (default 3)")
    if orientable:
        g.add_argument("--front", choices=CW,
                       help="direction the front faces (default: toward --player, else south)")
    g.add_argument("--apply", action="store_true", help="actually build (default is a dry run)")
    g.add_argument("--allow-overwrite", action="store_true",
                   help="allow replacing existing non-air blocks")
    g.add_argument("--max-cells", type=int, default=65536, help="cells per edit()/getblocks() call")
    g.add_argument("--undo-dir", default="mcpylib-undo", help="where undo files are written")
    c = ap.add_argument_group("connection (token comes from MCPYLIB_TOKEN)")
    c.add_argument("--host")
    c.add_argument("--port", type=int)
    c.add_argument("--timeout", type=float, default=60.0)


# ---------------------------------------------------------------- cells and grids

def block_id(cell) -> str:
    """'stone' -> 'minecraft:stone'; dict cells -> their block id."""
    name = cell["block"] if isinstance(cell, dict) else cell
    name = str(name).lower()
    return name if ":" in name else "minecraft:" + name


def stair(block: str, facing: str, half: str | None = None, shape: str | None = None) -> dict:
    state = {"facing": facing}
    if half:
        state["half"] = half
    if shape:
        state["shape"] = shape
    return {"block": block, "block_state": state}


def rotate_cell(cell, turns: int):
    """Rotate facing/rotation/axis states of a dict cell by clockwise quarter turns."""
    if not isinstance(cell, dict) or turns % 4 == 0 or "block_state" not in cell:
        return cell
    state = dict(cell["block_state"])
    facing = state.get("facing")
    if facing in CW:
        state["facing"] = CW[(CW.index(facing) + turns) % 4]
    rot = state.get("rotation")
    if rot in ROT16:
        state["rotation"] = ROT16[(ROT16.index(rot) + 4 * turns) % 16]
    elif str(rot).isdigit() and int(rot) < 16:  # vanilla 0-15, 0 = south, clockwise
        state["rotation"] = str((int(rot) + 4 * turns) % 16)
    if turns % 2 and state.get("axis") in ("x", "z"):
        state["axis"] = "z" if state["axis"] == "x" else "x"
    out = dict(cell)
    out["block_state"] = state
    return out


class Grid:
    """Sparse voxel model in local coordinates (front faces local +Z)."""

    def __init__(self) -> None:
        self.cells: dict[tuple[int, int, int], object] = {}
        self.deferred: set[tuple[int, int, int]] = set()

    def set(self, x: int, y: int, z: int, cell, defer: bool = False) -> None:
        """defer=True places the cell later with setblock() (light sources, etc.)."""
        key = (int(x), int(y), int(z))
        self.cells[key] = cell
        if defer:
            self.deferred.add(key)
        else:
            self.deferred.discard(key)

    def get(self, x: int, y: int, z: int):
        return self.cells.get((x, y, z))

    def box(self, x1, y1, z1, x2, y2, z2, cell, hollow: bool = False) -> None:
        """Fill an inclusive box; hollow=True keeps only its faces."""
        xa, xb = sorted((x1, x2))
        ya, yb = sorted((y1, y2))
        za, zb = sorted((z1, z2))
        for x in range(xa, xb + 1):
            for y in range(ya, yb + 1):
                for z in range(za, zb + 1):
                    if not hollow or x in (xa, xb) or y in (ya, yb) or z in (za, zb):
                        self.set(x, y, z, cell)

    def __len__(self) -> int:
        return len(self.cells)

    def front_extent(self) -> int:
        return max((k[2] for k in self.cells), default=0)


def turns_for_front(front: str) -> int:
    """Quarter turns that rotate a local-south front to face `front`."""
    return (CW.index(front) - CW.index("south")) % 4


def rotate_xz(x: int, z: int, turns: int) -> tuple[int, int]:
    for _ in range(turns % 4):
        x, z = -z, x
    return x, z


# ---------------------------------------------------------------- anchor

def find_player_uuid(mc, name: str) -> str | None:
    for p in mc.list().get("players", []):
        if str(p.get("name", "")).lower() == name.lower():
            return p.get("uuid")
    return None


def player_facing(mc, uuid: str) -> str:
    yaw = float(mc.getEntityPos(uuid).get("yaw", 0.0)) % 360.0
    return ("south", "west", "north", "east")[int(round(yaw / 90.0)) % 4]


def resolve_placement(mc, args, grid: Grid) -> tuple[tuple[int, int, int], int]:
    """Return (anchor, turns) from --at/--front or --player/--gap."""
    front = getattr(args, "front", None)
    if args.at:
        return tuple(args.at), turns_for_front(front or "south")
    if not args.player:
        sys.exit("Give --at X Y Z or --player NAME.")
    x, y, z = mc.getPos(args.player)
    uuid = find_player_uuid(mc, args.player)
    facing = "north"
    if uuid:
        world = str(mc.getEntityStatus(uuid).get("world", ""))
        if world.endswith(("_nether", "_the_end")):
            sys.exit(f"{args.player} is in '{world}', but MCPyLib builds in the main overworld. "
                     "Use --at with overworld coordinates instead.")
        facing = player_facing(mc, uuid)
    if front is None:
        front = CW[(CW.index(facing) + 2) % 4]  # face the player
    turns = turns_for_front(front)
    fx, fz = VECTORS[facing]
    dist = args.gap + 1 + grid.front_extent()
    return (x + fx * dist, y, z + fz * dist), turns


# ---------------------------------------------------------------- world-space build

class Build:
    def __init__(self, cells: dict, deferred: set, label: str) -> None:
        self.cells = cells
        self.deferred = deferred
        self.label = label

    @classmethod
    def from_grid(cls, grid: Grid, anchor, turns: int, label: str) -> "Build":
        ax, ay, az = anchor
        cells, deferred = {}, set()
        for (x, y, z), cell in grid.cells.items():
            rx, rz = rotate_xz(x, z, turns)
            key = (ax + rx, ay + y, az + rz)
            cells[key] = rotate_cell(cell, turns)
            if (x, y, z) in grid.deferred:
                deferred.add(key)
        return cls(cells, deferred, label)

    def clip_y(self) -> int:
        bad = [k for k in self.cells if not Y_MIN <= k[1] <= Y_MAX]
        for k in bad:
            del self.cells[k]
            self.deferred.discard(k)
        return len(bad)

    def bbox(self):
        xs = [k[0] for k in self.cells]
        ys = [k[1] for k in self.cells]
        zs = [k[2] for k in self.cells]
        return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)

    def batches(self, max_cells: int) -> list[tuple[int, int, int, int, int, int]]:
        """Inclusive boxes, chunk-aligned when the build is large, each holding cells."""
        if not self.cells:
            return []
        x1, y1, z1, x2, y2, z2 = self.bbox()
        if (x2 - x1 + 1) * (y2 - y1 + 1) * (z2 - z1 + 1) <= max_cells:
            return [(x1, y1, z1, x2, y2, z2)]
        groups: dict[tuple[int, int], list] = {}
        for k in self.cells:
            groups.setdefault((k[0] >> 4, k[2] >> 4), []).append(k)
        boxes = []
        for keys in groups.values():
            gx1, gx2 = min(k[0] for k in keys), max(k[0] for k in keys)
            gz1, gz2 = min(k[2] for k in keys), max(k[2] for k in keys)
            ys = sorted({k[1] for k in keys})
            height = max(1, max_cells // ((gx2 - gx1 + 1) * (gz2 - gz1 + 1)))
            y = ys[0]
            while y <= ys[-1]:
                top = min(ys[-1], y + height - 1)
                if any(y <= v <= top for v in ys):
                    boxes.append((gx1, y, gz1, gx2, top, gz2))
                y = top + 1
        return boxes


class Plan:
    def __init__(self) -> None:
        self.existing: dict[tuple[int, int, int], str] = {}
        self.changes: dict[tuple[int, int, int], object] = {}
        self.replaced = Counter()  # non-air block types that would be replaced

    @property
    def overwrite_count(self) -> int:
        return sum(self.replaced.values())


def survey(mc, build: Build, boxes) -> Plan:
    plan = Plan()
    for box in boxes:
        bx, by, bz = box[:3]
        data = mc.getblocks(*box)
        for dx, plane in enumerate(data):
            for dy, row in enumerate(plane):
                for dz, current in enumerate(row):
                    key = (bx + dx, by + dy, bz + dz)
                    if key in build.cells:
                        plan.existing[key] = current
    for key, cell in build.cells.items():
        current = plan.existing.get(key, "minecraft:air")
        if isinstance(cell, dict) or block_id(cell) != current or key in build.deferred:
            plan.changes[key] = cell
            if current not in AIR and block_id(cell) != current:
                plan.replaced[current] += 1
    return plan


def bucket_by_box(keys, boxes) -> list[list[tuple[int, int, int]]]:
    """Assign each (x, y, z) key to the box that contains it, in one pass."""
    index: dict[tuple[int, int], list[int]] = {}
    for i, (x1, _y1, z1, x2, _y2, z2) in enumerate(boxes):
        for cx in range(x1 >> 4, (x2 >> 4) + 1):
            for cz in range(z1 >> 4, (z2 >> 4) + 1):
                index.setdefault((cx, cz), []).append(i)
    buckets: list[list[tuple[int, int, int]]] = [[] for _ in boxes]
    for k in keys:
        for i in index.get((k[0] >> 4, k[2] >> 4), ()):
            x1, y1, z1, x2, y2, z2 = boxes[i]
            if x1 <= k[0] <= x2 and y1 <= k[1] <= y2 and z1 <= k[2] <= z2:
                buckets[i].append(k)
                break
    return buckets


def write_undo(plan: Plan, build: Build, boxes, undo_dir: str) -> Path:
    folder = Path(undo_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = folder / f"undo-{build.label}-{stamp}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"format": UNDO_FORMAT, "label": build.label,
                             "created": datetime.now(timezone.utc).isoformat(),
                             "note": "records [x, y, z, previous_type, placed_type]; "
                                     "restores block types only"}) + "\n")
        for keys in bucket_by_box(plan.changes.keys(), boxes):
            rows = [[k[0], k[1], k[2], plan.existing.get(k, "minecraft:air"),
                     block_id(plan.changes[k])] for k in keys]
            if rows:
                fh.write(json.dumps({"cells": rows}) + "\n")
    return path


def place(mc, build: Build, plan: Plan, boxes) -> tuple[int, int]:
    placed = 0
    edit_keys = [k for k in plan.changes if k not in build.deferred]
    for box, keys in zip(boxes, bucket_by_box(edit_keys, boxes)):
        if not keys:
            continue
        x1, y1, z1, x2, y2, z2 = box
        sx, sy, sz = x2 - x1 + 1, y2 - y1 + 1, z2 - z1 + 1
        blocks = [[[None] * sz for _ in range(sy)] for _ in range(sx)]
        for x, y, z in keys:
            blocks[x - x1][y - y1][z - z1] = plan.changes[(x, y, z)]
        placed += mc.edit(x1, y1, z1, blocks)
    deferred = 0
    for key in sorted(build.deferred & plan.changes.keys(), key=lambda k: k[1]):
        cell = plan.changes[key]
        if isinstance(cell, dict):
            mc.setblock(*key, cell["block"], block_state=cell.get("block_state"), nbt=cell.get("nbt"))
        else:
            mc.setblock(*key, cell)
        deferred += 1
    return placed, deferred


def describe(counter: Counter, limit: int = 5) -> str:
    return ", ".join(f"{b} x{n}" for b, n in counter.most_common(limit)) or "-"


def execute(mc, build: Build, args) -> int:
    """Survey, report, and (with --apply) build. Exit code: 0 ok, 2 refused."""
    dropped = build.clip_y()
    if not build.cells:
        print("Nothing to place (all cells outside Y -64..319?).")
        return 1
    boxes = build.batches(args.max_cells)
    started = time.time()
    plan = survey(mc, build, boxes)
    x1, y1, z1, x2, y2, z2 = build.bbox()
    print(f"Plan '{build.label}': box x {x1}..{x2}, y {y1}..{y2}, z {z1}..{z2} "
          f"({x2 - x1 + 1} x {y2 - y1 + 1} x {z2 - z1 + 1})")
    print(f"  cells in model: {len(build.cells):,}; to write: {len(plan.changes):,} "
          f"(unchanged skipped: {len(build.cells) - len(plan.changes):,})")
    if dropped:
        print(f"  WARNING: {dropped:,} cells fall outside Y {Y_MIN}..{Y_MAX} and were dropped")
    print(f"  existing non-air blocks that would be replaced: {plan.overwrite_count:,}"
          + (f" ({describe(plan.replaced)})" if plan.replaced else ""))
    print(f"  edit() calls: {len(boxes)}; deferred setblock() calls: {len(build.deferred)}; "
          f"survey took {time.time() - started:.1f}s")
    if not args.apply:
        hint = " --allow-overwrite" if plan.overwrite_count else ""
        print(f"Dry run only. Re-run with --apply{hint} to build.")
        return 0
    if plan.overwrite_count and not args.allow_overwrite:
        print(f"REFUSED: {plan.overwrite_count:,} existing blocks would be replaced. "
              "Confirm with the user, then add --allow-overwrite.")
        return 2
    if not plan.changes:
        print("Nothing changes; the build is already there.")
        return 0
    undo = write_undo(plan, build, boxes, args.undo_dir)
    started = time.time()
    placed, deferred = place(mc, build, plan, boxes)
    print(f"Built: {placed:,} blocks via edit(), {deferred} via setblock() "
          f"in {time.time() - started:.1f}s.")
    print(f"Undo: python undo.py {undo} --apply")
    return 0


# ---------------------------------------------------------------- geometry helpers

def disk_cells(radius: float):
    """(dx, dz, distance) for every column within radius + 0.5 of the centre."""
    r = int(math.ceil(radius)) + 1
    lim = (radius + 0.5) ** 2
    for dx in range(-r, r + 1):
        for dz in range(-r, r + 1):
            d2 = dx * dx + dz * dz
            if d2 <= lim:
                yield dx, dz, math.sqrt(d2)
