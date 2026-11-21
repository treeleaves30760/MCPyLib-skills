#!/usr/bin/env python3
"""End-to-end smoke tests: run every bundled script against tools/mock_server.py.

Each test starts a fresh mock world, runs a script as a subprocess (with
MCPYLIB_HOST / MCPYLIB_PORT / MCPYLIB_TOKEN pointing at the mock) in a temporary
directory, and checks the exit code, the output and the mock world afterwards.

Usage:  python tools/smoke_test.py [-k SUBSTRING] [-v]
Needs:  the mcpylib package (pip install mcpylib). Pillow is optional: when it is
        installed, the PNG decoder is also cross-checked against it.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from mock_server import MockServer, World  # noqa: E402

CORE = ROOT / "skills" / "mcpylib" / "scripts"
BUILD = ROOT / "skills" / "mcpylib-building" / "scripts"
GAMES = ROOT / "skills" / "mcpylib-minigames" / "scripts"
TOKEN = "smoke-test-token"
TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


class Env:
    """A mock server with a fresh world, plus a temporary working directory."""

    def __init__(self, **world_kw):
        self.world = World(**world_kw)
        self.world.add_player("Steve", 0.5, 65.0, 0.5, yaw=0.0)
        self.server = MockServer(self.world, TOKEN).start()
        self.tmp = Path(tempfile.mkdtemp(prefix="mcpylib-smoke-"))

    def run(self, script: Path, *args, token: str = TOKEN, timeout: float = 180):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("MCPYLIB_", "SERVER_"))}
        env.update(MCPYLIB_HOST="127.0.0.1", MCPYLIB_PORT=str(self.server.port),
                   MCPYLIB_TOKEN=token, PYTHONIOENCODING="utf-8")
        return subprocess.run([sys.executable, str(script), *map(str, args)], cwd=self.tmp,
                              env=env, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)

    def actions(self, name: str) -> list:
        return [p for a, p in self.world.log if a == name]

    def close(self):
        self.server.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


def check(cond, msg, proc=None):
    if cond:
        return
    if proc is not None:
        msg += (f"\n--- exit code {proc.returncode}\n--- stdout (tail)\n{proc.stdout[-2500:]}"
                f"\n--- stderr (tail)\n{proc.stderr[-2500:]}")
    raise AssertionError(msg)


def ok(proc, *needles, code=0):
    check(proc.returncode == code, f"expected exit code {code}", proc)
    for needle in needles:
        check(needle in proc.stdout, f"expected {needle!r} in stdout", proc)


def bulk_edit_blocks(params: dict) -> set:
    """Block ids in a bulkEdit request, compressed (client 1.2.0) or legacy (1.1.x)."""
    if "palette" in params:
        cells = params["palette"]
    else:
        cells = [c for plane in params.get("blocks", []) for row in plane for c in row]
    return {c if isinstance(c, str) else c.get("block") for c in cells if c is not None}


def undo_path(proc) -> str:
    m = re.search(r"Undo: python undo\.py (\S+) --apply", proc.stdout)
    check(m is not None, "no undo command printed", proc)
    return m.group(1)


# ---------------------------------------------------------------- PNG helpers

def png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def filter_row(ftype: int, row: bytes, prev: bytes, bpp: int) -> bytes:
    out = bytearray()
    for i, x in enumerate(row):
        a = row[i - bpp] if i >= bpp else 0
        b = prev[i]
        c = prev[i - bpp] if i >= bpp else 0
        pred = (0, a, b, (a + b) // 2, paeth(a, b, c))[ftype]
        out.append((x - pred) & 0xFF)
    return bytes([ftype]) + bytes(out)


def make_png(width, height, color_type, depth, rows, plte=None, trns=None, filters=(0,)):
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    bpp = max(1, channels * depth // 8)
    raw, prev = b"", bytes(len(rows[0]))
    for i, row in enumerate(rows):
        raw += filter_row(filters[i % len(filters)], row, prev, bpp)
        prev = row
    out = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth,
                                                                  color_type, 0, 0, 0))
    if plte:
        out += png_chunk(b"PLTE", plte)
    if trns:
        out += png_chunk(b"tRNS", trns)
    return out + png_chunk(b"IDAT", zlib.compress(raw)) + png_chunk(b"IEND", b"")


# ---------------------------------------------------------------- general

@test
def help_for_every_script():
    env = Env()
    try:
        commands = [
            (CORE / "check_setup.py",), (CORE / "snapshot.py",), (CORE / "snapshot.py", "save"),
            (CORE / "snapshot.py", "diff"), (CORE / "snapshot.py", "restore"),
            (BUILD / "pixel_art.py",), (BUILD / "terrain.py",), (BUILD / "undo.py",),
            (BUILD / "buildings.py", "house"), (BUILD / "buildings.py", "tower"),
            (GAMES / "game_kit.py",), (GAMES / "king_of_the_hill.py",), (GAMES / "mob_arena.py",),
        ] + [(BUILD / "shapes.py", s) for s in ("sphere", "dome", "cylinder", "cone", "pyramid", "torus", "box")]
        for cmd in commands:
            proc = env.run(*cmd, "--help")
            check(proc.returncode == 0 and "usage:" in proc.stdout,
                  f"--help failed for {' '.join(str(c) for c in cmd)}", proc)
    finally:
        env.close()


# ---------------------------------------------------------------- core skill

@test
def check_setup_ready_and_bad_token():
    env = Env()
    try:
        ok(env.run(CORE / "check_setup.py", "--player", "Steve"), "READY")
        proc = env.run(CORE / "check_setup.py", token="wrong-token")
        ok(proc, "NOT READY", code=1)
    finally:
        env.close()


@test
def snapshot_save_diff_restore():
    env = Env()
    try:
        ok(env.run(CORE / "snapshot.py", "save", 0, 63, 0, 3, 66, 3, "-o", "snap.json"), "Saved 64 cells")
        env.world.put(1, 64, 1, "minecraft:diamond_block")
        env.world.put(2, 65, 2, "minecraft:glass")
        ok(env.run(CORE / "snapshot.py", "diff", "snap.json"), "2 of 64 cells differ")
        ok(env.run(CORE / "snapshot.py", "restore", "snap.json"), "Restore would write 2 cells", "Dry run")
        check(env.world.get(1, 64, 1) == "minecraft:diamond_block", "dry run must not write")
        ok(env.run(CORE / "snapshot.py", "restore", "snap.json", "--apply"), "Restored 2 cells")
        check(env.world.get(1, 64, 1) == "minecraft:grass_block", "grass not restored")
        check(env.world.get(2, 65, 2) == "minecraft:air", "air not restored")
    finally:
        env.close()


# ---------------------------------------------------------------- building skill

@test
def shapes_dry_run_apply_undo():
    env = Env()
    try:
        ok(env.run(BUILD / "shapes.py", "sphere", "--radius", 2, "--block", "glass",
                   "--at", 100, 70, 100), "Dry run only")
        check(not env.actions("bulkEdit") and not env.world.blocks, "dry run wrote blocks")
        proc = env.run(BUILD / "shapes.py", "sphere", "--radius", 2, "--block", "glass",
                       "--at", 100, 70, 100, "--apply")
        ok(proc, "Built:")
        glass = [k for k, v in env.world.blocks.items() if v == "minecraft:glass"]
        check(len(glass) > 20, f"expected a glass sphere, got {len(glass)} cells", proc)
        ok(env.run(BUILD / "undo.py", undo_path(proc)), "Dry run")
        ok(env.run(BUILD / "undo.py", undo_path(proc), "--apply"), "Restored")
        check(all(env.world.get(*k) == "minecraft:air" for k in glass), "undo left glass behind")
    finally:
        env.close()


@test
def shapes_refuse_overwrite_without_flag():
    env = Env()
    try:
        args = ("box", "--size", 3, 1, 3, "--block", "stone_bricks", "--at", 0, 64, 0, "--apply")
        ok(env.run(BUILD / "shapes.py", *args), "REFUSED", code=2)
        check(env.world.get(0, 64, 0) == "minecraft:grass_block", "refused build still wrote")
        ok(env.run(BUILD / "shapes.py", *args, "--allow-overwrite"), "Built:")
        check(env.world.get(0, 64, 0) == "minecraft:stone_bricks", "box not built")
    finally:
        env.close()


@test
def other_shapes_apply():
    env = Env()
    try:
        cases = {"dome": ("--radius", 3), "cylinder": ("--radius", 3, "--height", 4),
                 "cone": ("--radius", 3, "--height", 4),
                 "pyramid": ("--base", 5, "--stairs", "sandstone_stairs"),
                 "torus": ("--major", 4, "--minor", 1)}
        for i, (shape, size) in enumerate(cases.items()):
            proc = env.run(BUILD / "shapes.py", shape, *size, "--block", "sandstone",
                           "--at", 40 * i, 80, 300, "--apply")
            ok(proc, "Built:")
        facings = {s.get("facing") for s in env.world.states.values()}
        check({"north", "south", "east", "west"} <= facings, f"pyramid stairs facings: {facings}")
    finally:
        env.close()


@test
def house_and_tower():
    env = Env()
    try:
        proc = env.run(BUILD / "buildings.py", "house", "--width", 7, "--depth", 7,
                       "--player", "Steve", "--apply")
        ok(proc, "Built:")
        facings = {s.get("facing") for s in env.world.states.values()}
        check({"north", "south"} <= facings, f"roof stairs missing, facings={facings}", proc)
        check(env.actions("setblock"), "torches should be placed with setblock()", proc)
        houses = [k for k in env.world.blocks if k[2] > 3]
        check(houses, "house should be south of Steve (yaw 0 faces south)", proc)
        proc = env.run(BUILD / "buildings.py", "tower", "--radius", 3, "--height", 6,
                       "--at", 60, 65, 60, "--apply")
        ok(proc, "Built:")
        check(any(v == "minecraft:ladder" for v in env.world.blocks.values()), "tower has no ladder", proc)
    finally:
        env.close()


@test
def pixel_art_from_png():
    env = Env()
    try:
        colors = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255),
                  (255, 255, 255, 255), (0, 0, 0, 255), (0, 0, 0, 0)]
        rows = [bytes(v for c in (colors[(x + y) % 6] for x in range(6)) for v in c) for y in range(4)]
        (env.tmp / "art.png").write_bytes(make_png(6, 4, 6, 8, rows, filters=(1, 2, 3, 4)))
        proc = env.run(BUILD / "pixel_art.py", "art.png", "--width", 6, "--at", 0, 70, 20, "--apply")
        ok(proc, "Built:")
        placed = [v for v in env.world.blocks.values()]
        check(len(placed) == 20, f"expected 20 opaque pixels placed, got {len(placed)}", proc)
        check(all(v.endswith("_concrete") for v in placed), f"unexpected blocks {set(placed)}", proc)
        # Pure #FF0000 legitimately lands on orange_concrete (red_concrete is dark), so
        # only check colours with an obvious match, and that all five stay distinct.
        check({"minecraft:white_concrete", "minecraft:black_concrete", "minecraft:blue_concrete"}
              <= set(placed) and len(set(placed)) == 5, f"colour matching looks wrong: {set(placed)}", proc)
    finally:
        env.close()


@test
def png_decoder_formats():
    sys.path.insert(0, str(BUILD))
    import pngdecode
    tmp = Path(tempfile.mkdtemp(prefix="mcpylib-png-"))
    try:
        cases = {
            "rgba8": (make_png(2, 2, 6, 8, [bytes([255, 0, 0, 255, 0, 255, 0, 128]),
                                            bytes([0, 0, 255, 255, 10, 20, 30, 0])], filters=(4, 3)),
                      [[(255, 0, 0, 255), (0, 255, 0, 128)], [(0, 0, 255, 255), (10, 20, 30, 0)]]),
            "gray8": (make_png(2, 1, 0, 8, [bytes([0, 255])]),
                      [[(0, 0, 0, 255), (255, 255, 255, 255)]]),
            "gray1": (make_png(8, 1, 0, 1, [bytes([0b10100000])]),
                      [[(255, 255, 255, 255), (0, 0, 0, 255), (255, 255, 255, 255)] + [(0, 0, 0, 255)] * 5]),
            "palette2_trns": (make_png(4, 1, 3, 2, [bytes([0b00011011])],
                                       plte=bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 9, 9, 9]),
                                       trns=bytes([0, 128])),
                              [[(255, 0, 0, 0), (0, 255, 0, 128), (0, 0, 255, 255), (9, 9, 9, 255)]]),
            "rgb16_trns": (make_png(2, 1, 2, 16, [bytes([255, 255, 0, 0, 0, 0, 1, 0, 2, 0, 3, 0])],
                                    trns=bytes([1, 0, 2, 0, 3, 0])),
                           [[(255, 0, 0, 255), (1, 2, 3, 0)]]),
            "graya8": (make_png(1, 2, 4, 8, [bytes([100, 50]), bytes([200, 255])], filters=(2,)),
                       [[(100, 100, 100, 50)], [(200, 200, 200, 255)]]),
        }
        for name, (data, expected) in cases.items():
            path = tmp / f"{name}.png"
            path.write_bytes(data)
            w, h, rows = pngdecode.read_png(str(path))
            got = [[tuple(px) for px in row] for row in rows]
            check((w, h) == (len(expected[0]), len(expected)), f"{name}: size {w}x{h}")
            check(got == expected, f"{name}: decoded {got}, expected {expected}")
        try:
            from PIL import Image
        except ImportError:
            print("    (Pillow not installed: cross-check skipped)")
            return
        for mode in ("1", "L", "LA", "P", "RGB", "RGBA"):
            img = Image.new("RGBA", (13, 7))
            img.putdata([((x * 37) % 256, (y * 53) % 256, ((x + y) * 29) % 256, (x * y * 17) % 256)
                         for y in range(7) for x in range(13)])
            path = tmp / f"pil_{mode}.png"
            img.convert(mode).save(path)
            w, h, rows = pngdecode.read_png(str(path))
            ref = Image.open(path).convert("RGBA")
            want = [[ref.getpixel((x, y)) for x in range(w)] for y in range(h)]
            got = [[tuple(px) for px in row] for row in rows]
            check(got == want, f"Pillow mode {mode}: pngdecode differs from Pillow")
        # 16-bit grayscale: Pillow's own I;16 -> RGBA conversion clips instead of
        # scaling, so compare with the PNG rule (keep the high byte) directly.
        values = [(x * 4099 + y * 7919) % 65536 for y in range(7) for x in range(13)]
        img16 = Image.new("I;16", (13, 7))
        img16.putdata(values)
        img16.save(tmp / "pil_I16.png")
        w, h, rows = pngdecode.read_png(str(tmp / "pil_I16.png"))
        got = [px for row in rows for px in row]
        want = [(v >> 8, v >> 8, v >> 8, 255) for v in values]
        check(got == want, "16-bit grayscale from Pillow decoded wrongly")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def terrain_survey_refuse_apply_undo():
    env = Env()
    try:
        base = ("--at", 200, 200, "--size", 20, 20, "--seed", 3, "--amplitude", 5)
        ok(env.run(BUILD / "terrain.py", *base), "Dry run")
        ok(env.run(BUILD / "terrain.py", *base, "--survey"), "Would change")
        ok(env.run(BUILD / "terrain.py", *base, "--apply"), "REFUSED", code=2)
        proc = env.run(BUILD / "terrain.py", *base, "--apply", "--allow-overwrite")
        ok(proc, "Placed")
        check(len(env.world.blocks) > 400, "terrain wrote too little", proc)
        ok(env.run(BUILD / "undo.py", undo_path(proc), "--apply"), "Restored")
        changed = [k for k, v in env.world.blocks.items() if v != env.world.base_block(*k)]
        check(not changed, f"undo left {len(changed)} terrain cells", proc)
    finally:
        env.close()


# ---------------------------------------------------------------- minigames skill

@test
def koth_winner_and_cleanup():
    env = Env()
    try:
        env.world.add_player("Alex", 8.5, 65.0, 8.5)
        proc = env.run(GAMES / "king_of_the_hill.py", "--at", 0, 65, 0, "--radius", 2,
                       "--duration", 20, "--target", 2, "--countdown", 0, "--hz", 5, "--linger", 0)
        ok(proc, "Steve wins")
        check(not env.world.objectives and not env.world.bossbars, "objective or boss bar left behind", proc)
        check(not (env.tmp / "koth-state.json").exists(), "state file left behind", proc)
        check(env.world.players["Steve"]["titles"], "no titles shown", proc)
        check(env.actions("particle"), "no hill particles", proc)
        check(any(p.get("slot") == "sidebar" for p in env.actions("setDisplaySlot")), "no sidebar", proc)
    finally:
        env.close()


@test
def koth_marker_needs_overwrite_and_is_restored():
    env = Env()
    try:
        args = ("--at", 0, 65, 0, "--radius", 2, "--duration", 20, "--target", 1, "--countdown", 0,
                "--hz", 5, "--linger", 0, "--marker", "gold_block")
        proc = env.run(GAMES / "king_of_the_hill.py", *args)
        check(proc.returncode != 0 and "--allow-overwrite" in proc.stdout + proc.stderr,
              "marker over grass must need --allow-overwrite", proc)
        check(not env.world.objectives and not env.world.blocks, "refused game left changes", proc)
        proc = env.run(GAMES / "king_of_the_hill.py", *args, "--allow-overwrite")
        ok(proc, "Steve wins")
        check(any("minecraft:gold_block" in bulk_edit_blocks(p) for p in env.actions("bulkEdit")),
              "marker was never placed", proc)
        check(all(v == "minecraft:grass_block" for (x, y, z), v in env.world.blocks.items() if y == 64),
              "marker not restored", proc)
    finally:
        env.close()


@test
def arena_victory_and_cleanup():
    env = Env(mob_lifetime=0.6)
    try:
        proc = env.run(GAMES / "mob_arena.py", "--at", 0, 65, 0, "--radius", 6, "--waves", 2,
                       "--base-count", 2, "--step", 1, "--break", 1, "--countdown", 0, "--hz", 4,
                       "--wall", "glass", "--linger", 0)
        ok(proc, "Victory")
        check(len(env.actions("summon")) == 5, f"expected 2 + 3 mobs, got {len(env.actions('summon'))}", proc)
        check(env.actions("setEntityEquipment") and env.actions("addTag") and env.actions("setEntityTarget"),
              "mobs should get helmets, the game tag and a target", proc)
        check(not env.world.entities, "mobs left behind", proc)
        check(all(v == "minecraft:air" for v in env.world.blocks.values()), "wall not removed", proc)
        check(not env.world.objectives and not env.world.bossbars, "objective or boss bar left behind", proc)
        check(not (env.tmp / "arena-state.json").exists(), "state file left behind", proc)
    finally:
        env.close()


@test
def arena_time_up_removes_mobs():
    env = Env()  # mobs never die
    try:
        proc = env.run(GAMES / "mob_arena.py", "--at", 0, 65, 0, "--radius", 6, "--waves", 1,
                       "--base-count", 3, "--wave-time", 2, "--countdown", 0, "--hz", 4, "--linger", 0)
        ok(proc, "Defeat")
        check(not env.world.entities, "mobs left behind after time-up", proc)
    finally:
        env.close()


@test
def arena_detects_peaceful():
    env = Env()
    env.world.difficulty = "peaceful"
    try:
        proc = env.run(GAMES / "mob_arena.py", "--at", 0, 65, 0, "--radius", 6, "--waves", 1,
                       "--base-count", 2, "--countdown", 0, "--linger", 0)
        check(proc.returncode != 0 and "peaceful" in (proc.stdout + proc.stderr).lower(),
              "peaceful difficulty should be reported", proc)
        check(not env.world.objectives and not env.world.bossbars, "leftovers after abort", proc)
    finally:
        env.close()


@test
def crash_cleanup_cli():
    env = Env()
    try:
        w = env.world
        loaded = w.do_summon("zombie", 3.5, 65, 3.5)
        far = w.do_summon("skeleton", 100.5, 65, 100.5)
        w.entities[far]["unloaded"] = True  # only found once its chunk is force-loaded
        w.do_addObjective("crashobj", "dummy")
        w.do_bossbar("add", "crashbar")
        w.do_team("add", "crashteam")
        w.players["Steve"]["gamemode"] = "ADVENTURE"
        w.put(5, 65, 5, "minecraft:glass")
        state = {"format": "mcpylib-game-state/1",
                 "entities": {loaded: [3, 3], far: [100, 100]},
                 "objectives": ["crashobj"], "bossbars": ["crashbar"], "teams": ["crashteam"],
                 "gamemodes": {"Steve": "survival"}, "effects": [["Steve", "speed"]],
                 "blocks": [[5, 65, 5, "minecraft:air", "minecraft:glass"]]}
        (env.tmp / "crash.json").write_text(json.dumps(state), encoding="utf-8")
        proc = env.run(GAMES / "game_kit.py", "--cleanup", "crash.json")
        ok(proc, "Clean.")
        check(not w.entities, f"entities left: {list(w.entities)}", proc)
        check(not w.objectives and not w.bossbars and not w.teams, "scoreboard leftovers", proc)
        check(w.players["Steve"]["gamemode"] == "SURVIVAL", "gamemode not restored", proc)
        check(w.get(5, 65, 5) == "minecraft:air", "temporary block not restored", proc)
        check(not w.forced, f"force-loaded chunks left: {w.forced}", proc)
        check(not (env.tmp / "crash.json").exists(), "state file should be deleted", proc)
    finally:
        env.close()


@test
def crash_cleanup_keeps_offline_player():
    env = Env()
    try:
        state = {"format": "mcpylib-game-state/1", "entities": {}, "objectives": [],
                 "bossbars": [], "teams": [], "gamemodes": {"Ghost": "survival"},
                 "effects": [], "blocks": []}
        (env.tmp / "s.json").write_text(json.dumps(state), encoding="utf-8")
        proc = env.run(GAMES / "game_kit.py", "--cleanup", "s.json")
        ok(proc, "player offline", code=1)
        kept = json.loads((env.tmp / "s.json").read_text(encoding="utf-8"))
        check(kept["gamemodes"] == {"Ghost": "survival"}, "offline player's gamemode must be kept", proc)
    finally:
        env.close()


# ---------------------------------------------------------------- packaging

@test
def package_zips_have_folder_at_root():
    out = Path(tempfile.mkdtemp(prefix="mcpylib-dist-"))
    try:
        proc = subprocess.run([sys.executable, str(ROOT / "tools" / "package_skills.py"), "--out", str(out)],
                              capture_output=True, text=True)
        ok(proc)
        skills = sorted(p.name for p in (ROOT / "skills").iterdir() if (p / "SKILL.md").exists())
        for skill in skills:
            zpath = out / f"{skill}.zip"
            check(zpath.exists(), f"{zpath.name} missing", proc)
            names = zipfile.ZipFile(zpath).namelist()
            check(f"{skill}/SKILL.md" in names, f"{zpath.name} lacks {skill}/SKILL.md")
            check(all(n.startswith(skill + "/") for n in names), f"{zpath.name} has files outside {skill}/")
            check(not any("__pycache__" in n or n.endswith(".pyc") for n in names), f"{zpath.name} has caches")
    finally:
        shutil.rmtree(out, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-k", help="only run tests whose name contains this")
    ap.add_argument("-v", action="store_true", help="print tracebacks")
    args = ap.parse_args()
    selected = [t for t in TESTS if not args.k or args.k in t.__name__]
    failed = []
    for fn in selected:
        started = time.time()
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - report every failure
            failed.append(fn.__name__)
            print(f"FAIL  {fn.__name__} ({time.time() - started:.1f}s)\n      "
                  + str(exc).replace("\n", "\n      "))
            if args.v:
                traceback.print_exc()
        else:
            print(f"PASS  {fn.__name__} ({time.time() - started:.1f}s)")
    print(f"\n{len(selected) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
