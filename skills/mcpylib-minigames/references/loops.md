# Game loops, polling and cleanup

## Contents

- [The cost model](#the-cost-model)
- [Fixed-rate loops](#fixed-rate-loops)
- [Polling players](#polling-players)
- [Parallel reads with several connections](#parallel-reads-with-several-connections)
- [Zones](#zones)
- [Game phases as a state machine](#game-phases-as-a-state-machine)
- [Timers and countdowns](#timers-and-countdowns)
- [Detecting events by polling](#detecting-events-by-polling)
- [Shutdown and crash recovery](#shutdown-and-crash-recovery)
- [Keeping the server responsive](#keeping-the-server-responsive)

## The cost model

- The plugin runs every request on the server's main thread and answers after the
  next tick, so one connection completes about **20 calls per second** (about 50 ms
  each), whatever the call does.
- The server keeps running at 20 TPS while you wait: a cheap call costs latency, not
  server time. Big `edit`, `fill` or `getblocks` calls do cost server time.
- Budget per loop step: `calls x 0.05 s < step period`.

| Players | Calls per step (poll + HUD) | Comfortable rate |
|---|---|---|
| 1-3 | 3-6 | 2-4 steps per second |
| 4-8 | 6-12 | 1-2 steps per second |
| 9-20 | 10-25 | 1 step per second, or parallel reads |

`Ticker.overruns` counts steps that took longer than their period. If it grows, lower
the rate or make fewer calls per step.

## Fixed-rate loops

```python
import time

def run(step, hz, duration):
    period = 1.0 / hz
    start = next_t = time.monotonic()
    while (elapsed := time.monotonic() - start) < duration:
        if step(elapsed) is False:
            break
        next_t += period
        delay = next_t - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            next_t = time.monotonic()  # late: skip ahead instead of bursting
```

`game_kit.Ticker` is this loop. Two habits make it fair:
- Score with real elapsed time (`dt = elapsed - last_elapsed`), not "one point per
  step", so late steps don't cost players points.
- Use `time.monotonic()`, never `time.time()`, which jumps when the clock changes.

## Polling players

| Call | Gives | Cost |
|---|---|---|
| `mc.list()` | Names, UUIDs and gamemodes of everyone online | 1 call |
| `mc.getEntityStatus(uuid)` | Float position, `health`, `is_dead`, `world` | 1 call per player |
| `mc.getEntityPos(uuid)` | Float position plus `yaw` and `pitch` | 1 call per player |
| `mc.getPos(name)` | Integer feet block `[x, y, z]` | 1 call per player |

- Call `list()` every 2-5 s for joins, and the per-player call every step.
- A player who logs out makes `getEntityStatus` raise `CommandError`
  (`Entity not found: ...`); treat that as a leave.
- `getPos` and `getEntityStatus` report positions in the player's current world.
  Check `world` and ignore names ending in `_nether` or `_the_end`, because game
  effects only happen in the main overworld.
- `game_kit.Roster` does all of this. `refresh()` = `list()` + `poll()`, and both
  return `(joined, left)`.

## Parallel reads with several connections

One client handles one request at a time, but the plugin serves each connection on
its own worker thread, so N clients can finish N calls in the same tick. Use one
client per thread; a client is not thread-safe.

```python
import threading
from concurrent.futures import ThreadPoolExecutor
from mcpylib import CommandError, MCPyLib

local = threading.local()
clients = []

def client():
    if not hasattr(local, "mc"):
        local.mc = MCPyLib(ip=HOST, port=PORT, token=TOKEN)
        clients.append(local.mc)
    return local.mc

def status(uuid):
    try:
        return uuid, client().getEntityStatus(uuid)
    except CommandError:
        return uuid, None  # logged out

pool = ThreadPoolExecutor(max_workers=4)
statuses = dict(pool.map(status, player_uuids))  # 4 calls per tick instead of 1
# at the end: pool.shutdown(); then close every client in `clients`
```

Each open client occupies one of the plugin's `max-connections` slots (default 10).
Beyond that, new clients get `CommandError: Server busy ...` (older plugins let them
hang), so stay well below the limit and close clients when the game ends.

## Zones

```python
import math

def in_box(p, x1, y1, z1, x2, y2, z2):
    """p = (x, y, z) floats; the box covers whole blocks, both corners included."""
    x, y, z = p
    return (min(x1, x2) <= x < max(x1, x2) + 1 and min(y1, y2) <= y < max(y1, y2) + 1
            and min(z1, z2) <= z < max(z1, z2) + 1)

def in_cylinder(p, cx, cy, cz, radius, height):
    x, y, z = p
    return math.hypot(x - (cx + 0.5), z - (cz + 0.5)) <= radius and cy <= y < cy + height

inside = set()

def zone_events(positions):
    """positions: {name: (x, y, z)}. Returns (entered, exited) since the last call."""
    now = {n for n, p in positions.items() if in_cylinder(p, 0, 64, 0, 3, 3)}
    entered, exited = now - inside, inside - now
    inside.clear()
    inside.update(now)
    return entered, exited
```

React to `entered` and `exited` (edge-triggered) rather than to "is inside"
(level-triggered), or titles and sounds repeat every step.

## Game phases as a state machine

```python
phase, phase_started = "lobby", 0.0

def step(elapsed):
    global phase, phase_started
    t = elapsed - phase_started
    if phase == "lobby" and len(roster.names()) >= 2:
        phase, phase_started = "countdown", elapsed
    elif phase == "countdown" and t >= 5:
        phase, phase_started = "running", elapsed
    elif phase == "running" and (winner_found() or t >= 180):
        phase, phase_started = "ended", elapsed
    elif phase == "ended" and t >= 5:
        return False  # leave the loop; finally: cleans up
```

Do the work of each phase in its own function, and change the HUD only when the
phase changes.

## Timers and countdowns

- Show time left as a sidebar label (`board.set("Time left", seconds)`) or in the
  boss bar title and progress.
- Only send when the whole-second value changes; `Objective.set` and `Bar.update`
  skip unchanged values.
- `game_kit.countdown(mc, names, 3)` shows 3, 2, 1, Go! titles with ticks. Every
  title and sound is one call per player.

## Detecting events by polling

| Event | Approach |
|---|---|
| Death | `getEntityStatus(uuid)["is_dead"]` is true while the player is on the death screen; a quick respawn can slip between polls. A `deathCount` objective counts every death: `mc.getScore("deaths", name)` |
| Kills | `addObjective("kills", "playerKillCount")` or `"totalKillCount"`; the server counts by itself |
| Health, food, level | `health`, `food` and `level` criteria, or `getEntityStatus` for health |
| Mob killed | `getEntityStatus(mob_uuid)` raises `CommandError` once the mob is gone |
| Block changed | `getblocks` over a small box each step, compared with the previous read |
| Reached a place | Zone checks on polled positions |
| Picked up an item | `getItem(username, slot)` for a known slot (one call per slot) |
| Chat, commands, clicks | Not observable through MCPyLib |

```python
mc.addObjective("deaths", "deathCount")       # record it with tracker.objective("deaths")
seen = {name: mc.getScore("deaths", name) for name in roster.names()}
# each step (or every few seconds):
for name in roster.names():
    count = mc.getScore("deaths", name)
    if count > seen.get(name, 0):
        mc.tell(name, "§cYou died. Back to the start!")
        seen[name] = count
```

## Shutdown and crash recovery

- Wrap the game in `try: ... finally: tracker.cleanup(mc)`. Ctrl+C raises
  `KeyboardInterrupt`, so the `finally:` block still runs.
- `Tracker` writes its JSON state file after every change, atomically. If the process
  dies (crash, kill, power loss), run
  `python game_kit.py --cleanup <id>-state.json` later. It removes entities (and
  force-loads their chunks to find missing ones), boss bars, objectives and teams,
  clears effects, restores gamemodes and temporary blocks, and deletes the file when
  everything is done.
- Items it can't finish stay in the file. Players who are offline keep their
  gamemode or effect entries, which a later run applies.
- Boss bars live only in plugin memory and disappear on a restart; the rest
  (objectives, teams, mobs, blocks) survive restarts and need the cleanup.
- If the state file is gone too, remove leftovers by hand: `mc.removeObjective(name)`,
  `mc.bossbar("remove", bar_id)`, `mc.team("remove", name)`, and in game
  `/kill @e[tag=<game_id>]`.

## Keeping the server responsive

- Don't run big `edit()` or `fill()` calls during a running game. Build arenas
  before the game starts, in chunk-sized pieces.
- Keep per-step work small. Spread periodic jobs, such as re-targeting mobs or
  checking all mobs, over several steps (round robin).
- Set `logging.log-commands: false` in `plugins/MCPyLib/config.yml`, because a 2 Hz
  loop otherwise logs every call to the console.
