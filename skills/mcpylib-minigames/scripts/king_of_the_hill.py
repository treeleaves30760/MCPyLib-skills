#!/usr/bin/env python3
"""King of the Hill: stand alone on the hill to score; first to --target points wins.

  python king_of_the_hill.py --player Steve --radius 3 --target 60
  python king_of_the_hill.py --at 100 70 -20 --marker gold_block --allow-overwrite

A participant alone on the hill (within --radius blocks of the centre, feet
within 2 blocks of its height) earns one point per second. Two or more players
on the hill contest it and nobody scores. When --duration runs out, the highest
score wins. The game shows a sidebar, a boss bar, titles, sounds and a rotating
particle ring, and it removes everything it created at the end, also after
Ctrl+C. After a crash run:  python game_kit.py --cleanup koth-state.json
"""
from __future__ import annotations

import argparse
import sys
import time

import game_kit as gk


def main() -> int:
    ap = argparse.ArgumentParser(description="King of the Hill minigame for MCPyLib.")
    gk.add_game_args(ap, "koth")
    ap.add_argument("--radius", type=float, default=3.0, help="hill radius in blocks (default 3)")
    ap.add_argument("--target", type=int, default=60, help="points to win (default 60)")
    ap.add_argument("--duration", type=float, default=300.0, help="time limit in seconds (default 300)")
    ap.add_argument("--countdown", type=int, default=3, help="seconds of countdown titles")
    ap.add_argument("--hz", type=float, default=2.0, help="position checks per second (default 2)")
    ap.add_argument("--marker", help="temporary ring of this block in the floor around the hill")
    ap.add_argument("--allow-overwrite", action="store_true", help="let --marker replace floor blocks")
    ap.add_argument("--linger", type=float, default=5.0, help="seconds to show the result before cleanup")
    args = ap.parse_args()

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


def play(mc, args, tracker: gk.Tracker, center) -> int:
    cx, cy, cz = center
    if args.marker:
        ring = {(x, cy - 1, z): args.marker for x, z in gk.ring_cells(cx, cz, args.radius)}
        gk.place_blocks(mc, tracker, ring, args.allow_overwrite)

    roster = gk.Roster(mc, gk.participants(args))
    roster.refresh()
    if not roster.names():
        print("No participants online in the main overworld.")
        return 1
    board = gk.Objective(mc, tracker, args.id, "§6King of the Hill", slot="sidebar")
    bar = gk.Bar(mc, tracker, args.id, f"Hold the hill for {args.target} points", color="YELLOW")
    score = {}
    for name in roster.names():
        score[name] = 0.0
        board.set(name, 0)
    bar.show(roster.names())
    print(f"Hill at {cx} {cy} {cz}, radius {args.radius:g}; players: {', '.join(roster.names())}")
    gk.countdown(mc, roster.names(), args.countdown, "Stand alone on the hill to score")

    points = list(gk.ring_points(cx + 0.5, cz + 0.5, args.radius, 12))
    game = {"last": 0.0, "refreshed": 0.0, "holder": None, "contested": False,
            "winner": None, "spark": 0}

    def on_hill(name: str) -> bool:
        x, y, z = roster.pos(name)
        return gk.horizontal_distance(x, z, cx, cz) <= args.radius + 0.5 and abs(y - cy) <= 2

    def step(elapsed: float):
        dt, game["last"] = elapsed - game["last"], elapsed
        if elapsed - game["refreshed"] >= 3.0:  # list() every 3 s catches joins
            joined, left = roster.refresh()
            game["refreshed"] = elapsed
        else:
            joined, left = roster.poll()
        bar.forget(left)
        for name in joined:
            if name not in score:
                score[name] = 0.0
                board.set(name, 0)
        gk.title_all(mc, joined, "§6King of the Hill", "Stand alone on the hill to score")
        bar.show(joined)

        hill = [n for n in roster.alive() if on_hill(n)]
        contested = len(hill) > 1
        if len(hill) == 1:
            holder = hill[0]
            before = int(score[holder])
            score[holder] += dt
            now = int(score[holder])
            if holder != game["holder"]:
                gk.sound_all(mc, [holder], "block.note_block.pling", pitch=1.5)
            if now != before:
                board.set(holder, now)
                if now % 10 == 0:
                    gk.sound_all(mc, [holder], "entity.experience_orb.pickup")
            bar.update(title=f"§e{holder}§r holds the hill: {now}/{args.target}", color="YELLOW",
                       progress=now / args.target)
            if now >= args.target:
                game["winner"] = holder
                return False
        elif contested:
            if not game["contested"]:
                gk.sound_all(mc, hill, "block.note_block.bass", pitch=0.7)
            bar.update(title="§cContested: " + ", ".join(hill), color="RED")
        else:
            bar.update(title="The hill is free", color="WHITE")
        game["holder"] = hill[0] if len(hill) == 1 else None
        game["contested"] = contested
        board.set("Time left", max(0, int(args.duration - elapsed)))

        x, z = points[game["spark"] % len(points)]  # one ring point per step: a spinning ring
        game["spark"] += 1
        mc.particle("angry_villager" if contested else "end_rod", x, cy + 0.3, z, count=3, dy=0.2)

    ticker = gk.Ticker(args.hz)
    ticker.run(step, duration=args.duration)
    if ticker.overruns:
        print(f"Note: {ticker.overruns} steps ran late; use a lower --hz with many players.")

    winner = game["winner"]
    if winner is None and score:
        best = max(int(s) for s in score.values())
        leaders = [n for n, s in score.items() if int(s) == best]
        winner = leaders[0] if best > 0 and len(leaders) == 1 else None
    names = roster.names()
    if winner:
        print(f"{winner} wins with {int(score[winner])} points.")
        gk.title_all(mc, names, f"§6{winner} wins!", f"{int(score[winner])} points", stay=80)
        gk.sound_all(mc, names, "ui.toast.challenge_complete")
        mc.particle("totem_of_undying", cx + 0.5, cy + 1.0, cz + 0.5, count=60, dx=1, dy=1, dz=1, speed=0.3)
    else:
        print("Draw: nobody won.")
        gk.title_all(mc, names, "§7Draw", "Nobody held the hill long enough", stay=80)
    ranking = sorted(score.items(), key=lambda kv: -kv[1])
    print("Final scores: " + ", ".join(f"{n} {int(s)}" for n, s in ranking))
    time.sleep(args.linger)
    return 0


if __name__ == "__main__":
    sys.exit(main())
