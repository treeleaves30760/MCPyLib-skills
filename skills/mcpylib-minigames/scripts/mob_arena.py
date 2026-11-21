#!/usr/bin/env python3
"""Mob arena: survive waves of mobs summoned around the arena centre.

  python mob_arena.py --player Steve --radius 10 --waves 3
  python mob_arena.py --at 100 64 200 --wall glass --adventure --mobs zombie,husk,skeleton

Wave N summons --base-count + (N - 1) * --step mobs on open floor near the edge.
Every mob gets a leather helmet (so zombies and skeletons don't burn in daylight),
the tag <id>, and a participant as its target. Kill them all within --wave-time
seconds to reach the next wave. The sidebar shows kills (criteria totalKillCount,
which counts any entity a player kills) and the boss bar the mobs left. The game
is lost when time runs out or every participant is dead at the same moment.

Everything it creates (mobs, wall, objective, boss bar, changed gamemodes) is
removed at the end, also after Ctrl+C. After a crash run
  python game_kit.py --cleanup arena-state.json
An operator can also remove stray mobs in game with /kill @e[tag=arena].
"""
from __future__ import annotations

import argparse
import math
import random
import sys
import time
from contextlib import suppress

import game_kit as gk

LIQUIDS = {"minecraft:water", "minecraft:lava"}
PASSABLE = gk.AIR | {"minecraft:short_grass", "minecraft:tall_grass", "minecraft:fern",
                     "minecraft:large_fern", "minecraft:dandelion", "minecraft:poppy",
                     "minecraft:snow"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Mob arena minigame for MCPyLib.")
    gk.add_game_args(ap, "arena")
    ap.add_argument("--radius", type=float, default=10.0, help="arena radius, 3-32 (default 10)")
    ap.add_argument("--waves", type=int, default=3)
    ap.add_argument("--mobs", default="zombie,skeleton,spider",
                    help="comma-separated entity ids (avoid creeper: it blows up the arena)")
    ap.add_argument("--base-count", type=int, default=4, help="mobs in wave 1 (default 4)")
    ap.add_argument("--step", type=int, default=2, help="extra mobs per wave (default 2)")
    ap.add_argument("--wave-time", type=float, default=120.0, help="seconds per wave (default 120)")
    ap.add_argument("--break", dest="break_time", type=float, default=8.0,
                    help="seconds between waves (default 8)")
    ap.add_argument("--countdown", type=int, default=3)
    ap.add_argument("--hz", type=float, default=2.0, help="loop steps per second (default 2)")
    ap.add_argument("--wall", help="temporary 3-high ring wall of this block around the arena")
    ap.add_argument("--allow-overwrite", action="store_true", help="let --wall replace existing blocks")
    ap.add_argument("--adventure", action="store_true",
                    help="put participants in adventure mode during the game (restored afterwards)")
    ap.add_argument("--difficulty", choices=("easy", "normal", "hard"),
                    help="set the server difficulty first (world-wide, not restored)")
    ap.add_argument("--linger", type=float, default=5.0, help="seconds to show the result before cleanup")
    args = ap.parse_args()
    if not 3 <= args.radius <= 32:
        ap.error("--radius must be between 3 and 32")

    with gk.connect(args) as mc:
        center = gk.resolve_center(mc, args)
        tracker = gk.start_tracker(mc, args)
        try:
            return play(mc, args, tracker, center)
        except KeyboardInterrupt:
            print("Stopped by user.")
            return 130
        finally:
            print("Cleaning up ...")
            tracker.cleanup(mc)


def find_spawns(mc, center, radius: float) -> list[tuple[int, int]]:
    """Open floor cells between 0.6 and 1.0 radius: solid floor, two passable blocks above."""
    cx, cy, cz = center
    r = int(radius)
    grid = mc.getblocks(cx - r, cy - 1, cz - r, cx + r, cy + 1, cz + r)  # one call, [x][y][z]
    spots = []
    for dx in range(2 * r + 1):
        for dz in range(2 * r + 1):
            if not 0.6 * radius <= math.hypot(dx - r, dz - r) <= radius:
                continue
            floor, feet, head = grid[dx][0][dz], grid[dx][1][dz], grid[dx][2][dz]
            if floor not in PASSABLE and floor not in LIQUIDS and feet in PASSABLE and head in PASSABLE:
                spots.append((cx - r + dx, cz - r + dz))
    return spots


def spawn_wave(mc, args, tracker, center, spots, count: int, targets: list[str]) -> list[str]:
    cx, cy, cz = center
    kinds = [m.strip() for m in args.mobs.split(",") if m.strip()]
    uuids = []
    for i in range(count):
        x, z = random.choice(spots)
        kind = kinds[i % len(kinds)]
        try:
            uid = mc.summon(kind, x + 0.5, cy, z + 0.5)
        except gk.CommandError as exc:
            raise SystemExit(f"Cannot summon '{kind}': {exc}")
        tracker.entity(uid, x, z)  # record first: cleanup must find it even if we crash now
        uuids.append(uid)
        with suppress(gk.CommandError):  # helmet: no burning in daylight; never dropped
            mc.setEntityEquipment(uid, {"helmet": "leather_helmet"}, drop_chances={"helmet": 0.0})
        with suppress(gk.CommandError):  # lets an operator run /kill @e[tag=<id>]
            mc.addTag(uid, args.id)
        if targets:
            with suppress(gk.CommandError):
                mc.setEntityTarget(uid, targets[i % len(targets)])
    mc.particle("large_smoke", cx + 0.5, cy + 1.0, cz + 0.5, count=80,
                dx=args.radius / 2, dy=0.5, dz=args.radius / 2, speed=0.02)
    return uuids


def nearest(roster: gk.Roster, x: float, z: float) -> str | None:
    best, best_d = None, None
    for name in roster.alive():
        px, _py, pz = roster.pos(name)
        d = (px - x) ** 2 + (pz - z) ** 2
        if best_d is None or d < best_d:
            best, best_d = name, d
    return roster.uuids.get(best) if best else None


def fight(mc, args, tracker, roster, bar, center, spots, alive: list[str], wave: int) -> str:
    """Run one wave. Returns 'cleared', 'time', 'everyone died' or 'no players left'."""
    cx, cy, cz = center
    total = len(alive)
    leash = args.radius + 4
    game = {"i": 0, "outcome": None, "refreshed": 0.0, "targeted": {}}

    def step(elapsed: float):
        if elapsed - game["refreshed"] >= 3.0:
            joined, left = roster.refresh()
            game["refreshed"] = elapsed
        else:
            joined, left = roster.poll()
        bar.forget(left)
        bar.show(joined)
        if args.adventure:
            for name in joined:
                tracker.gamemode(name, roster.modes.get(name, "survival"))
                with suppress(gk.CommandError):
                    mc.gamemode(name, "adventure")
        if not roster.names():
            game["outcome"] = "no players left"
            return False
        if not roster.alive():
            game["outcome"] = "everyone died"
            return False

        budget = max(2, 6 - len(roster.names()))  # keep each step to about 6 calls
        for _ in range(min(budget, len(alive))):
            uid = alive[game["i"] % len(alive)]
            game["i"] += 1
            try:
                st = mc.getEntityStatus(uid)
            except gk.CommandError:  # "Entity not found": killed
                st = None
            if st is None or st.get("is_dead"):
                alive.remove(uid)
                tracker.forget_entity(uid)
                if not alive:
                    break
                continue
            pos = st["position"]
            if gk.horizontal_distance(pos["x"], pos["z"], cx, cz) > leash:  # wandered off
                x, z = random.choice(spots)
                with suppress(gk.CommandError):
                    mc.teleportEntity(uid, x + 0.5, cy, z + 0.5)
            elif elapsed - game["targeted"].get(uid, 0.0) >= 10.0:  # mobs lose interest
                target = nearest(roster, pos["x"], pos["z"])
                if target:
                    with suppress(gk.CommandError):
                        mc.setEntityTarget(uid, target)
                game["targeted"][uid] = elapsed

        left_s = max(0, int(args.wave_time - elapsed))
        bar.update(title=f"Wave {wave}/{args.waves}: {len(alive)} mobs left, {left_s} s",
                   progress=len(alive) / total if total else 0.0)
        if not alive:
            game["outcome"] = "cleared"
            return False

    gk.Ticker(args.hz).run(step, duration=args.wave_time)
    return game["outcome"] or "time"


def play(mc, args, tracker: gk.Tracker, center) -> int:
    cx, cy, cz = center
    spots = find_spawns(mc, center, args.radius)
    if len(spots) < 4:
        print(f"Only {len(spots)} open floor cells near the arena edge; pick a flatter, open area.")
        return 1
    if args.wall:
        r = args.radius + 2
        wall = {(x, y, z): args.wall for x, z in gk.ring_cells(cx, cz, r) for y in range(cy, cy + 3)}
        gk.place_blocks(mc, tracker, wall, args.allow_overwrite)
    if args.difficulty:
        mc.difficulty(args.difficulty)
        print(f"Difficulty set to {args.difficulty} for the whole server (MCPyLib cannot read "
              "the old value, so it is not restored).")

    roster = gk.Roster(mc, gk.participants(args))
    roster.refresh()
    if not roster.names():
        print("No participants online in the main overworld.")
        return 1
    odd = [n for n in roster.names() if roster.modes.get(n) in ("creative", "spectator")]
    if odd:
        print(f"Note: mobs ignore players in creative or spectator mode: {', '.join(odd)}")
    if args.adventure:
        for name in roster.names():
            tracker.gamemode(name, roster.modes.get(name, "survival"))
            mc.gamemode(name, "adventure")
    kills = gk.Objective(mc, tracker, args.id, "§cArena kills", criteria="totalKillCount", slot="sidebar")
    bar = gk.Bar(mc, tracker, args.id, "Get ready", color="RED", style="SEGMENTED_10")
    bar.show(roster.names())
    print(f"Arena at {cx} {cy} {cz}, radius {args.radius:g}, {len(spots)} spawn cells; "
          f"players: {', '.join(roster.names())}")
    gk.countdown(mc, roster.names(), args.countdown, "Survive the waves!")

    outcome = "cleared"
    for wave in range(1, args.waves + 1):
        count = args.base_count + (wave - 1) * args.step
        gk.title_all(mc, roster.names(), f"§cWave {wave}", f"{count} mobs", stay=30)
        gk.sound_all(mc, roster.names(), "event.raid.horn")
        targets = [roster.uuids[n] for n in roster.alive() if n in roster.uuids]
        alive = spawn_wave(mc, args, tracker, center, spots, count, targets)
        if wave == 1:  # hostile mobs vanish at once on peaceful
            present = 0
            for uid in alive:
                with suppress(gk.CommandError):
                    present += not mc.getEntityStatus(uid).get("is_dead")
            if present == 0:
                raise SystemExit(f"All {len(alive)} mobs vanished right after spawning. The server "
                                 "difficulty is probably peaceful: ask the user, then re-run with "
                                 "--difficulty easy, normal or hard.")
        outcome = fight(mc, args, tracker, roster, bar, center, spots, alive, wave)
        if outcome != "cleared":
            break
        print(f"Wave {wave} cleared.")
        if wave < args.waves:
            names = roster.names()
            bar.update(title=f"Wave {wave} cleared! Next wave in {args.break_time:g} s",
                       color="GREEN", progress=1.0)
            gk.title_all(mc, names, "§aWave cleared!", f"Next wave in {args.break_time:g} s")
            gk.sound_all(mc, names, "entity.player.levelup")
            for name in roster.alive():
                with suppress(gk.CommandError):
                    mc.effect(name, "regeneration", duration=5, amplifier=1)
            time.sleep(args.break_time)
            bar.update(color="RED")

    names = roster.names()
    if outcome == "cleared":
        print(f"Victory! All {args.waves} waves cleared.")
        gk.title_all(mc, names, "§6Victory!", f"All {args.waves} waves cleared", stay=80)
        gk.sound_all(mc, names, "ui.toast.challenge_complete")
        mc.particle("totem_of_undying", cx + 0.5, cy + 1.0, cz + 0.5, count=80, dx=2, dy=1, dz=2, speed=0.4)
    else:
        reason = {"time": "time ran out"}.get(outcome, outcome)
        print(f"Defeat: {reason}.")
        gk.title_all(mc, names, "§4Defeat", reason.capitalize(), stay=80)
        gk.sound_all(mc, names, "entity.wither.death", volume=0.6)
    print("Kills: " + ", ".join(f"{n} {kills.get(n)}" for n in names))
    time.sleep(args.linger)
    return 0


if __name__ == "__main__":
    sys.exit(main())
