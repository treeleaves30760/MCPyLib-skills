#!/usr/bin/env python3
"""Shared helpers for MCPyLib minigames. Import it from a game script in this folder.

  connect(args)     client from MCPYLIB_HOST / MCPYLIB_PORT / MCPYLIB_TOKEN (or SERVER_*)
  Tracker           crash-safe JSON record of everything a game creates; cleanup()
                    removes or restores it (entities, objectives, boss bars, teams,
                    gamemodes, effects, temporary blocks)
  Ticker            fixed-rate loop that skips missed ticks instead of bursting
  Roster            participants with join/leave, world, position and health
  Objective, Bar    scoreboard objective and boss bar that only send changes
  place_blocks()    temporary blocks (walls, markers) recorded for cleanup()

Crash recovery (it force-loads the chunks of entities it cannot find):
  python game_kit.py --cleanup koth-state.json

Every MCPyLib call waits for a server tick (about 50 ms). Budget the calls you
make in each loop step.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from pathlib import Path

try:
    from mcpylib import CommandError, MCPyLibError
except ImportError:  # keeps --help usable before mcpylib is installed
    class MCPyLibError(Exception):
        pass

    class CommandError(MCPyLibError):
        pass

STATE_FORMAT = "mcpylib-game-state/1"
AIR = frozenset({"minecraft:air", "minecraft:cave_air", "minecraft:void_air"})
OTHER_DIMENSIONS = ("_nether", "_the_end")
# Blocks whose contents or text a type-only restore cannot bring back.
DATA_BLOCK_RE = re.compile(
    r"(chest|barrel|shulker_box|furnace|smoker|hopper|dispenser|dropper|_sign|_banner|"
    r"lectern|brewing_stand|spawner|beacon|_head|_skull|_bed|_door|jukebox|crafter|"
    r"decorated_pot|chiseled_bookshelf|campfire|command_block)$")


# ---------------------------------------------------------------- connection

def load_env_file(path: str = ".env") -> None:
    """Load KEY=VALUE lines from .env without overriding the environment."""
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


def add_connection_args(ap: argparse.ArgumentParser) -> None:
    g = ap.add_argument_group("connection (the token comes from MCPYLIB_TOKEN)")
    g.add_argument("--host")
    g.add_argument("--port", type=int)
    g.add_argument("--timeout", type=float, default=15.0)


def connect(args):
    from mcpylib import MCPyLib
    load_env_file()
    env = os.environ.get
    host = args.host or env("MCPYLIB_HOST") or env("SERVER_IP") or "127.0.0.1"
    port = args.port or int(env("MCPYLIB_PORT") or env("SERVER_PORT") or 65535)
    token = env("MCPYLIB_TOKEN") or env("SERVER_TOKEN") or ""
    if not token:
        sys.exit("No token: set MCPYLIB_TOKEN (run '/mcpylib token' on the server).")
    return MCPyLib(ip=host, port=port, token=token, timeout=args.timeout)


def add_game_args(ap: argparse.ArgumentParser, game_id: str) -> None:
    ap.add_argument("--at", nargs=3, type=int, metavar=("X", "Y", "Z"),
                    help="game centre: the block where players stand (feet level)")
    ap.add_argument("--player", help="centre the game on this player's current position")
    ap.add_argument("--players", help="comma-separated participants "
                                      "(default: everyone online in the main overworld)")
    ap.add_argument("--id", default=game_id,
                    help="name for the objective, boss bar and mob tag (default: %(default)s)")
    ap.add_argument("--state", help="state file for crash-safe cleanup (default: <id>-state.json)")
    add_connection_args(ap)


def player_uuid(mc, name: str) -> str | None:
    for p in mc.list().get("players", []):
        if str(p.get("name", "")).lower() == name.lower():
            return p.get("uuid")
    return None


def resolve_center(mc, args) -> tuple[int, int, int]:
    """--at X Y Z, or the block at --player's feet (refused outside the overworld)."""
    if args.at:
        return tuple(args.at)
    if not args.player:
        sys.exit("Give --at X Y Z or --player NAME.")
    uuid = player_uuid(mc, args.player)
    if uuid is None:
        sys.exit(f"Player {args.player} is not online.")
    world = str(mc.getEntityStatus(uuid).get("world", ""))
    if world.endswith(OTHER_DIMENSIONS):
        sys.exit(f"{args.player} is in {world}; MCPyLib summons mobs and particles in the "
                 "main overworld, so start the game there.")
    x, y, z = mc.getPos(args.player)
    return x, y, z


def participants(args) -> list[str] | None:
    return [n.strip() for n in args.players.split(",") if n.strip()] if args.players else None


def start_tracker(mc, args) -> Tracker:
    """Open the state file and clean up whatever a previous crashed run left."""
    tracker = Tracker(args.state or f"{args.id}-state.json")
    if tracker.has_leftovers:
        print(f"Cleaning up a previous run first ({tracker.summary()}) ...")
        if not tracker.cleanup(mc, force_load=True):
            sys.exit("The previous run could not be cleaned up completely; fix that first.")
    return tracker


# ---------------------------------------------------------------- resource tracking

class Tracker:
    """Crash-safe record of what a game created. Saved after every change."""

    LISTS = ("objectives", "bossbars", "teams", "effects", "blocks")

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.state: dict = {"format": STATE_FORMAT, "entities": {}, "gamemodes": {},
                            **{k: [] for k in self.LISTS}}
        if self.path.exists():
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if loaded.get("format") != STATE_FORMAT:
                sys.exit(f"{self.path} is not an {STATE_FORMAT} file.")
            self.state.update(loaded)

    @property
    def has_leftovers(self) -> bool:
        s = self.state
        return bool(s["entities"] or s["gamemodes"] or any(s[k] for k in self.LISTS))

    def summary(self) -> str:
        s = self.state
        parts = [f"{k}={len(s[k])}" for k in ("entities", "gamemodes", *self.LISTS) if s[k]]
        return ", ".join(parts) or "nothing"

    def save(self) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.state, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)  # atomic: a crash never leaves half a file

    def _add(self, key: str, value) -> None:
        if value not in self.state[key]:
            self.state[key].append(value)
            self.save()

    def entity(self, uuid: str, x: float | None = None, z: float | None = None) -> str:
        """Record a summoned entity; x, z let a later cleanup force-load its chunk."""
        pos = [math.floor(x), math.floor(z)] if x is not None and z is not None else None
        self.state["entities"][uuid] = pos
        self.save()
        return uuid

    def forget_entity(self, uuid: str) -> None:
        """Stop tracking an entity that died or that you removed yourself."""
        if uuid in self.state["entities"]:
            del self.state["entities"][uuid]
            self.save()

    def objective(self, name: str) -> None:
        self._add("objectives", name)

    def bossbar(self, bar_id: str) -> None:
        self._add("bossbars", bar_id)

    def team(self, name: str) -> None:
        self._add("teams", name)

    def effect(self, player: str, effect: str) -> None:
        self._add("effects", [player, effect])

    def gamemode(self, player: str, original: str) -> None:
        """Call before changing a player's gamemode; the first recorded mode wins."""
        self.state["gamemodes"].setdefault(player, original.lower())
        self.save()

    def blocks(self, rows: list) -> None:
        """rows: [[x, y, z, previous_type, placed_type], ...]"""
        self.state["blocks"].extend(rows)
        self.save()

    # ------------------------------------------------------------ cleanup

    def cleanup(self, mc, force_load: bool = False) -> bool:
        """Remove or restore everything recorded. Returns True when nothing is left.

        Items that fail because a player is offline or the connection broke stay
        in the state file. force_load=True (used by --cleanup) force-loads the
        chunks of entities that were not found, then retries them.
        """
        s = self.state

        def done(label: str, fn) -> bool:
            try:
                fn()
                return True
            except CommandError as exc:
                if str(exc).lower().startswith("player not found"):
                    print(f"  {label}: player offline, kept for a later cleanup")
                    return False
                print(f"  {label}: {exc} (skipped)")  # already gone, or can never work
                return True
            except (MCPyLibError, OSError) as exc:
                print(f"  {label}: {exc}")
                return False

        self._cleanup_entities(mc, force_load)
        s["bossbars"] = [b for b in s["bossbars"]
                         if not done(f"boss bar {b}", lambda b=b: mc.bossbar("remove", b))]
        s["objectives"] = [o for o in s["objectives"]
                           if not done(f"objective {o}", lambda o=o: mc.removeObjective(o))]
        s["teams"] = [t for t in s["teams"]
                      if not done(f"team {t}", lambda t=t: mc.team("remove", t))]
        s["effects"] = [e for e in s["effects"]
                        if not done(f"effect {e[1]} on {e[0]}", lambda e=e: mc.clearEffect(e[0], e[1]))]
        s["gamemodes"] = {p: m for p, m in s["gamemodes"].items()
                          if not done(f"gamemode of {p}", lambda p=p, m=m: mc.gamemode(p, m))}
        if s["blocks"] and done("temporary blocks", lambda: restore_blocks(mc, s["blocks"])):
            s["blocks"] = []
        if self.has_leftovers:
            self.save()
            print(f"Cleanup incomplete ({self.summary()} left). Re-run later with:\n"
                  f"  python game_kit.py --cleanup {self.path}")
            return False
        self.path.unlink(missing_ok=True)
        return True

    def _cleanup_entities(self, mc, force_load: bool) -> None:
        ents = self.state["entities"]
        missing: dict = {}
        for uuid, pos in list(ents.items()):
            try:
                mc.removeEntity(uuid)
            except CommandError as exc:
                if "not found" in str(exc).lower():
                    missing[uuid] = pos  # dead, despawned, or in an unloaded chunk
                else:
                    print(f"  entity {uuid}: {exc} (skipped)")
            except (MCPyLibError, OSError) as exc:
                print(f"  entity {uuid}: {exc}")
                continue  # keep it for the next attempt
            del ents[uuid]
        self.save()
        if missing and force_load:
            self._retry_unloaded(mc, missing)

    @staticmethod
    def _retry_unloaded(mc, missing: dict) -> None:
        chunks = set()
        for pos in missing.values():
            if pos:
                cx, cz = pos[0] >> 4, pos[1] >> 4
                chunks.update((cx + dx, cz + dz) for dx in (-1, 0, 1) for dz in (-1, 0, 1))
        added = []
        try:
            for cx, cz in sorted(chunks):
                if not mc.forceload("query", cx * 16, cz * 16):
                    mc.forceload("add", cx * 16, cz * 16)
                    added.append((cx, cz))
            if not added:
                return  # their chunks were loaded already, so those entities are gone
            print(f"  {len(missing)} entities not found; force-loading {len(added)} chunks to retry")
            time.sleep(3.0)  # entities load shortly after their chunk
            removed = 0
            for uuid in missing:
                try:
                    mc.removeEntity(uuid)
                    removed += 1
                except CommandError:
                    pass  # really gone (killed or despawned)
            print(f"  removed {removed} of them; the rest were already gone")
        finally:
            for cx, cz in added:
                try:
                    mc.forceload("remove", cx * 16, cz * 16)
                except (MCPyLibError, OSError) as exc:
                    print(f"  could not un-force-load chunk {cx},{cz}: {exc}")


# ---------------------------------------------------------------- temporary blocks

def _by_chunk(items, key=lambda item: item):
    groups: dict = {}
    for item in items:
        x, _y, z = key(item)[:3]
        groups.setdefault((x >> 4, z >> 4), []).append(item)
    return list(groups.values())


def _empty_box(x1, y1, z1, x2, y2, z2):
    return [[[None] * (z2 - z1 + 1) for _ in range(y2 - y1 + 1)] for _ in range(x2 - x1 + 1)]


def _bbox(points):
    xs, ys, zs = zip(*points)
    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def place_blocks(mc, tracker: Tracker, cells: dict, allow_overwrite: bool = False) -> int:
    """Place {(x, y, z): "block_id"} temporarily; cleanup() puts the old blocks back.

    Only changed cells are written. Refuses to replace non-air blocks unless
    allow_overwrite, and always refuses containers, signs, beds and other blocks
    whose data a type-only restore would lose. Undo rows are saved before writing.
    """
    plan = []
    for group in _by_chunk(list(cells)):
        x1, y1, z1, x2, y2, z2 = _bbox(group)
        current = mc.getblocks(x1, y1, z1, x2, y2, z2)
        rows = []
        for x, y, z in group:
            now = current[x - x1][y - y1][z - z1]
            block = cells[(x, y, z)].lower()
            placed = block if ":" in block else "minecraft:" + block
            if now != placed:
                rows.append([x, y, z, now, placed])
        if rows:
            plan.append(((x1, y1, z1, x2, y2, z2), rows))
    rows_all = [r for _box, rows in plan for r in rows]
    precious = [r for r in rows_all if DATA_BLOCK_RE.search(r[3])]
    if precious:
        x, y, z, prev, _ = precious[0]
        raise SystemExit(f"Refusing to replace {len(precious)} block(s) that hold data, e.g. {prev} "
                         f"at {x} {y} {z}. Move the game or its walls.")
    replaced = sum(1 for r in rows_all if r[3] not in AIR)
    if replaced and not allow_overwrite:
        raise SystemExit(f"Would replace {replaced} existing non-air blocks (restored at the end, "
                         "block types only). Confirm with the user, then pass --allow-overwrite.")
    if not rows_all:
        return 0
    tracker.blocks(rows_all)  # recorded first, so a crash mid-write is still undoable
    written = 0
    for (x1, y1, z1, x2, y2, z2), rows in plan:
        blocks = _empty_box(x1, y1, z1, x2, y2, z2)
        for x, y, z, _prev, placed in rows:
            blocks[x - x1][y - y1][z - z1] = placed
        written += mc.edit(x1, y1, z1, blocks)
    return written


def restore_blocks(mc, rows: list) -> int:
    """Put previous types back where the game's block is still in place."""
    restored = 0
    for group in _by_chunk(rows):
        x1, y1, z1, x2, y2, z2 = _bbox([r[:3] for r in group])
        current = mc.getblocks(x1, y1, z1, x2, y2, z2)
        blocks = _empty_box(x1, y1, z1, x2, y2, z2)
        count = 0
        for x, y, z, previous, placed in group:
            if current[x - x1][y - y1][z - z1] == placed:
                blocks[x - x1][y - y1][z - z1] = previous
                count += 1
        if count:
            restored += mc.edit(x1, y1, z1, blocks)
    return restored


# ---------------------------------------------------------------- loop and players

class Ticker:
    """Call step(elapsed_seconds) at `hz` until it returns False or `duration` passes."""

    def __init__(self, hz: float) -> None:
        self.period = 1.0 / hz
        self.overruns = 0

    def run(self, step, duration: float | None = None) -> None:
        start = time.monotonic()
        next_t = start
        while True:
            elapsed = time.monotonic() - start
            if duration is not None and elapsed >= duration:
                return
            if step(elapsed) is False:
                return
            next_t += self.period
            delay = next_t - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:  # the step made more calls than fit in one period
                self.overruns += 1
                next_t = time.monotonic()  # skip ahead instead of bursting to catch up


class Roster:
    """Participants in the main overworld.

    refresh() = list() + poll(); poll() = one getEntityStatus() per known player.
    Both return (joined, left) relative to the previous poll. Players who log out
    or change dimension count as left, and as joined when they come back.
    """

    def __init__(self, mc, only: list[str] | None = None) -> None:
        self.mc = mc
        self.only = {n.lower() for n in only} if only else None
        self.uuids: dict[str, str] = {}  # name -> uuid, from list()
        self.modes: dict[str, str] = {}  # name -> gamemode, lower case
        self.status: dict[str, dict] = {}  # name -> last getEntityStatus() result

    def refresh(self) -> tuple[list[str], list[str]]:
        self.uuids = {}
        for p in self.mc.list().get("players", []):
            name = str(p.get("name", ""))
            if self.only is None or name.lower() in self.only:
                self.uuids[name] = p.get("uuid")
                self.modes[name] = str(p.get("gamemode", "survival")).lower()
        return self.poll()

    def poll(self) -> tuple[list[str], list[str]]:
        before = set(self.status)
        status = {}
        for name, uuid in list(self.uuids.items()):
            try:
                st = self.mc.getEntityStatus(uuid)
            except CommandError:  # logged out since the last list()
                del self.uuids[name]
                continue
            if not str(st.get("world", "")).endswith(OTHER_DIMENSIONS):
                status[name] = st
        self.status = status
        now = set(status)
        return sorted(now - before), sorted(before - now)

    def names(self) -> list[str]:
        return sorted(self.status)

    def pos(self, name: str) -> tuple[float, float, float]:
        p = self.status[name]["position"]
        return p["x"], p["y"], p["z"]

    def alive(self) -> list[str]:
        return [n for n, st in sorted(self.status.items()) if not st.get("is_dead")]


# ---------------------------------------------------------------- HUD helpers

def title_all(mc, names, title: str, subtitle: str = "", stay: int = 40) -> None:
    for n in names:
        try:
            mc.title(n, title, subtitle, fade_in=5, stay=stay, fade_out=10)
        except CommandError:
            pass  # left the game


def sound_all(mc, names, sound: str, pitch: float = 1.0, volume: float = 1.0) -> None:
    for n in names:
        try:
            mc.playsound(n, sound, source="master", volume=volume, pitch=pitch)
        except CommandError:
            pass


def countdown(mc, names, seconds: int, subtitle: str = "") -> None:
    """Titles 3, 2, 1, Go! with ticks (seconds=0 goes straight to Go!)."""
    for i in range(seconds, 0, -1):
        title_all(mc, names, f"§e{i}", subtitle, stay=20)
        sound_all(mc, names, "block.note_block.hat")
        time.sleep(1.0)
    title_all(mc, names, "§aGo!", subtitle, stay=30)
    sound_all(mc, names, "block.note_block.pling", pitch=2.0)


class Objective:
    """Scoreboard objective, optionally shown in a display slot; set() sends changes only."""

    def __init__(self, mc, tracker: Tracker, name: str, display: str,
                 criteria: str = "dummy", slot: str | None = None) -> None:
        self.mc, self.name, self.scores = mc, name, {}
        try:
            mc.addObjective(name, criteria, display)
        except CommandError as exc:
            if "already exists" in str(exc):
                raise SystemExit(f"Scoreboard objective '{name}' already exists and is not in this "
                                 "game's state file, so it may belong to something else. Use another "
                                 "--id, or remove it yourself if you are sure it is a leftover.")
            raise
        tracker.objective(name)
        if slot:
            mc.setDisplaySlot(slot, name)

    def set(self, holder: str, score: int) -> None:
        if self.scores.get(holder) != score:
            self.mc.setScore(self.name, holder, score)
            self.scores[holder] = score

    def get(self, holder: str) -> int:
        return self.mc.getScore(self.name, holder)


class Bar:
    """Boss bar shown to participants; update() sends changed fields only."""

    def __init__(self, mc, tracker: Tracker, bar_id: str, title: str,
                 color: str = "WHITE", style: str = "SOLID") -> None:
        self.mc, self.id, self.shown = mc, bar_id, set()
        self.last = {"title": title, "color": color, "progress": 1.0}
        try:
            mc.bossbar("add", bar_id, title=title, color=color, style=style, progress=1.0)
        except CommandError as exc:
            if "already exists" in str(exc):
                raise SystemExit(f"Boss bar '{bar_id}' already exists (another script is using it). "
                                 "Use another --id.")
            raise
        tracker.bossbar(bar_id)

    def show(self, names) -> None:
        for n in names:
            if n not in self.shown:
                try:
                    self.mc.bossbar("addplayer", self.id, username=n)
                    self.shown.add(n)
                except CommandError:
                    pass

    def forget(self, names) -> None:
        """Call with players who left, so show() re-adds them when they return."""
        self.shown.difference_update(names)

    def update(self, title: str | None = None, color: str | None = None,
               progress: float | None = None) -> None:
        delta = {}
        if title is not None and title != self.last["title"]:
            delta["title"] = title
        if color is not None and color != self.last["color"]:
            delta["color"] = color
        if progress is not None:
            progress = round(max(0.0, min(1.0, progress)), 3)
            if progress != self.last["progress"]:
                delta["progress"] = progress
        if delta:
            self.mc.bossbar("set", self.id, title=delta.get("title"), color=delta.get("color"),
                            progress=delta.get("progress"))
            self.last.update(delta)


# ---------------------------------------------------------------- geometry

def ring_cells(cx: int, cz: int, radius: float):
    """(x, z) cells on a one-block-wide ring of the given radius around a block."""
    r = int(math.ceil(radius)) + 1
    for dx in range(-r, r + 1):
        for dz in range(-r, r + 1):
            if radius - 0.5 < math.hypot(dx, dz) <= radius + 0.5:
                yield cx + dx, cz + dz


def ring_points(cx: float, cz: float, radius: float, count: int):
    for i in range(count):
        a = 2 * math.pi * i / count
        yield cx + radius * math.cos(a), cz + radius * math.sin(a)


def horizontal_distance(px: float, pz: float, cx: int, cz: int) -> float:
    """Distance from a position to the centre of block (cx, cz)."""
    return math.hypot(px - (cx + 0.5), pz - (cz + 0.5))


# ---------------------------------------------------------------- crash cleanup CLI

def main() -> int:
    ap = argparse.ArgumentParser(description="Clean up what a crashed MCPyLib game left behind.")
    ap.add_argument("--cleanup", metavar="STATE_FILE", required=True)
    add_connection_args(ap)
    args = ap.parse_args()
    if not Path(args.cleanup).exists():
        print(f"{args.cleanup} does not exist: nothing to clean up.")
        return 0
    tracker = Tracker(args.cleanup)
    if not tracker.has_leftovers:
        print("Nothing to clean up.")
        tracker.path.unlink(missing_ok=True)
        return 0
    print(f"Leftovers: {tracker.summary()}")
    with connect(args) as mc:
        ok = tracker.cleanup(mc, force_load=True)
    print("Clean." if ok else "Some items remain (see above).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
