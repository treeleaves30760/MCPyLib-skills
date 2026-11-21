---
name: mcpylib-minigames
description: Builds Minecraft minigames and live events in Python with MCPyLib. Covers fixed-rate polling loops with a per-tick call budget, join and leave detection, zones, countdowns, scoreboards and sidebars, teams, boss bars, titles, sounds and particles, summoning and controlling mobs (targets, AI, equipment, tags), and crash-safe cleanup that removes every entity, objective, boss bar and temporary block a game created. Includes ready-to-run King of the Hill and mob arena games. Use when the user wants a minigame, arena, race, parkour timer, wave survival, scoreboard, boss bar, countdown, announcement or other interactive event on a Minecraft server driven by Python, or needs to poll player positions or clean up after a game. Builds on the mcpylib skill for connection and API details.
license: MCPyLib Non-Commercial License with Commercial Exception. Complete terms in LICENSE.txt
compatibility: Requires Python 3.11+, the mcpylib package (1.2.0+ recommended) and a Paper/Spigot 26.1+ server with the MCPyLib plugin.
metadata:
  author: treeleaves30760
  version: "1.0.0"
  mcpylib-version: "1.2.0"
---

# Minigames with MCPyLib

MCPyLib has **no events**: the plugin never pushes anything to the client. A game
is a Python loop that polls the server, applies its rules, and sends HUD updates.
For connection settings, API details and general safety rules, use the **mcpylib**
skill. Settings come from `MCPYLIB_HOST`, `MCPYLIB_PORT` and `MCPYLIB_TOKEN`
(environment or `./.env`).

## Game skeleton

Start from `scripts/game_kit.py`. Save a new game next to it and keep this shape:

```python
import argparse
import game_kit as gk

ap = argparse.ArgumentParser()
gk.add_game_args(ap, "race")   # --at/--player, --players, --id, --state, connection flags
args = ap.parse_args()

with gk.connect(args) as mc:
    cx, cy, cz = gk.resolve_center(mc, args)
    tracker = gk.start_tracker(mc, args)   # first cleans up a crashed previous run
    try:
        roster = gk.Roster(mc, gk.participants(args))
        roster.refresh()
        board = gk.Objective(mc, tracker, args.id, "Race", slot="sidebar")
        bar = gk.Bar(mc, tracker, args.id, "Reach the gold block!", color="GREEN")
        bar.show(roster.names())
        gk.countdown(mc, roster.names(), 3)

        def step(elapsed):
            joined, left = roster.poll()   # one getEntityStatus() per player
            bar.forget(left)
            bar.show(joined)
            for name in roster.alive():
                x, y, z = roster.pos(name)
                if gk.horizontal_distance(x, z, cx + 20, cz) < 1.5:
                    gk.title_all(mc, roster.names(), f"{name} wins!")
                    return False           # stops the loop
            bar.update(progress=1 - elapsed / 120)

        gk.Ticker(2).run(step, duration=120)
    finally:
        tracker.cleanup(mc)                # removes everything recorded, even after Ctrl+C
```

`game_kit` provides `Tracker` (a crash-safe record of what the game created),
`Ticker` (a fixed-rate loop), `Roster` (participants, positions, deaths, joins and
leaves), `Objective` and `Bar` (send changes only), `place_blocks` (temporary blocks
restored at the end), `countdown`, `title_all` and `sound_all`.

## Rules that keep games smooth and clean

1. **Budget calls.** Each call waits for the next server tick: about 50 ms per call
   per connection. Keep `calls per step x 0.05 s` below the step period. Two steps per
   second covers about 6 players; for more, poll less often or read in parallel with
   one client per thread ([references/loops.md](references/loops.md)).
2. **Poll smartly.** `getEntityStatus(uuid)` returns position, health, `is_dead` and
   world in one call. Call `list()` only every few seconds to catch joins.
3. **Send changes only.** Don't re-send unchanged scores, titles or bar values.
4. **Record before use.** Call `tracker.entity(uuid, x, z)` right after `summon`, and
   let `Objective`, `Bar` and `place_blocks` record themselves, so a crash at any point
   can be cleaned up.
5. **Always clean up** in `finally:`. After a crash, run
   `python scripts/game_kit.py --cleanup <id>-state.json`. Players who are offline
   keep their entries until a later run.
6. **Never `kill("all")` or `kill("<type>")`** on a shared world. Remove your own
   UUIDs with `removeEntity`, and tag mobs (`addTag(uuid, game_id)`) so an operator
   can type `/kill @e[tag=<game_id>]` as a last resort.
7. **Shared state needs consent.** The main scoreboard (everyone sees the sidebar),
   difficulty, time, weather and gamemodes are server-wide. MCPyLib can't read the
   current sidebar objective or difficulty, so those can't be restored afterwards.
   Ask before changing them.
8. **Main overworld only.** `summon` and `particle` act there. `Roster` ignores
   players in the Nether or End.
9. **Console commands are the last resort.** The dedicated methods have no action
   bar and no clickable chat. On plugin 1.2.0, `exec` (for example
   `title <name> actionbar ...`) and `tellraw` fill that gap, but they report
   success even when the command fails, freeze older plugins, and must never carry
   untrusted text. Prefer titles, the sidebar and boss bars.

## What you can show

| Want | Call | Notes |
|---|---|---|
| Big centred text | `title(username, title, subtitle, fade_in, stay, fade_out)` | One player per call; times in ticks; `§` colour codes |
| Live ranking or info lines | `addObjective`, `setDisplaySlot("sidebar", name)`, `setScore` | Score holders can be labels such as `"Time left"` |
| Progress or timer bar | `bossbar("add" / "set" / "addplayer" / "remove", ...)` | Plugin memory only; re-add players who rejoin |
| Chat | `say(message)` (everyone, `[Server]` prefix) or `tell(username, message)` | `§` codes work |
| Sound | `playsound(username, sound, volume=1.0, pitch=1.0)` | Unknown keys play nothing and raise no error |
| Particles | `particle(particle_type, x, y, z, count, dx, dy, dz, speed)` | Types that need data (`dust`, `block`, `item`) fail |
| Name colours, no friendly fire | `team("add" / "join" / "modify", ...)` | Remove the team at the end |
| Action bar, clickable chat | `exec("title <name> actionbar ...")`, `tellraw(username, json_text)` | Plugin 1.2.0+ only; see hud.md |

Details, valid ids and patterns are in [references/hud.md](references/hud.md).

## Detecting what happened

| Event | How to see it |
|---|---|
| Join, leave, dimension change | `Roster.refresh()` and `Roster.poll()` return `(joined, left)` |
| Player death | `status["is_dead"]` while on the death screen, or a `deathCount` objective |
| Kills | `playerKillCount` / `totalKillCount` objectives count by themselves |
| Entering an area | Position check each step (cylinder, box or sphere test) |
| Mob died | `getEntityStatus` raises `Entity not found`, or `is_dead` |
| Block broken or placed | `getblocks` over a small box, compared with the last read |
| Chat, commands, item use | Not observable through MCPyLib |

## Mobs and other entities

- `summon(entity_type, x, y, z)` returns a UUID. Add `0.5` to centre on a block.
- `setEntityEquipment(uuid, {"helmet": "leather_helmet"}, drop_chances={"helmet": 0.0})`
  stops zombies and skeletons from burning in daylight, without drops.
- `setEntityTarget(uuid, player_uuid)` sends a mob after a player.
  `setEntityAI(uuid, False)` freezes a statue or NPC. `teleportEntity` leashes mobs
  that wander off.
- On **peaceful** difficulty hostile mobs vanish at once; `mob_arena.py` detects that.
  Summoned mobs can despawn far from players, and entities in unloaded chunks report
  `Entity not found`.

See [references/entities.md](references/entities.md) for equipment, attributes,
villagers, velocity and riding.

## Bundled scripts

Run these from this skill's `scripts/` directory. Every game removes what it created
at the end and accepts `--players a,b` to limit participants.

| Script | What it does | Example |
|---|---|---|
| `scripts/game_kit.py` | Helpers above; `--cleanup STATE` removes a crashed game's leftovers (it force-loads chunks to find missing mobs) | `python game_kit.py --cleanup koth-state.json` |
| `scripts/king_of_the_hill.py` | Score while alone on the hill; sidebar, boss bar, particle ring, optional `--marker` ring in the floor | `python king_of_the_hill.py --player Steve --radius 3 --target 60` |
| `scripts/mob_arena.py` | Waves of mobs with helmets, targets and a leash; optional temporary `--wall` and `--adventure` mode | `python mob_arena.py --player Steve --radius 10 --waves 3 --wall glass` |

Before running a game, tell the user what it changes: the sidebar, a boss bar,
summoned mobs, gamemodes with `--adventure`, and blocks with `--marker` or `--wall`.
`--marker` and `--wall` refuse to replace non-air blocks without `--allow-overwrite`,
and never replace containers, signs or beds.

## References

- [references/loops.md](references/loops.md): call budgets, fixed-rate loops,
  parallel polling, zones, state machines, timers, detecting events, shutdown.
- [references/hud.md](references/hud.md): colour codes, titles, chat, scoreboards,
  teams, boss bars, sound keys and particle ids.
- [references/entities.md](references/entities.md): summoning, tracking, AI,
  targets, equipment, attributes, villagers, despawning and cleanup.
