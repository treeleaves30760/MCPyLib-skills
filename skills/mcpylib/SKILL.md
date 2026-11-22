---
name: mcpylib
description: Controls a Minecraft Paper/Spigot server from Python with the MCPyLib library and its server plugin. Covers setup checks (plugin, token, .env), connecting, coordinates and the -64..319 build height, block ids with block_state and NBT, choosing between setblock, fill, edit bulk arrays, clone and getblocks, batching for speed, error handling, and safe read-before-write editing, plus players, entities, chat, world settings and the raw TCP JSON protocol for other languages. Use when the user mentions MCPyLib or mcpylib, wants a script that places, reads or changes blocks, players, entities or settings on a Minecraft server, or hits MCPyLib connection, token or plugin errors.
license: MCPyLib Non-Commercial License with Commercial Exception. Complete terms in LICENSE.txt
compatibility: Requires Python 3.11+, the mcpylib package (1.2.1 recommended) and TCP access to a Paper/Spigot 26.1+ server (Java 25) running the MCPyLib plugin, port 65535 by default.
metadata:
  author: treeleaves30760
  version: "1.1.0"
  mcpylib-version: "1.2.1"
---

# MCPyLib core

MCPyLib = a Python client (`pip install mcpylib` or `uv add mcpylib`) plus the
`MCPyLib-Plugin-1.2.1.jar` server plugin. The plugin opens a TCP socket (default
65535). The client sends newline-delimited JSON commands with a token, and the
plugin runs each command on the server's main thread.

Everything below is checked against `client.py` and the plugin source of 1.2.1.
For the full method list read [references/api.md](references/api.md). For other
languages read [references/protocol.md](references/protocol.md). When something
fails, see [references/troubleshooting.md](references/troubleshooting.md).

## 1. Setup check (do this first)

1. **Server**: Paper or Spigot 26.1+ on Java 25, with `MCPyLib-Plugin-1.2.1.jar` in
   `plugins/`. `/plugins` lists MCPyLib, and the console prints
   `Server listening on ...` and `Authentication token: ...` at startup.
2. **Token**: run `/mcpylib token` in the console or as op (aliases `/mcpy`, `/mcp`),
   or read `security.token` in `plugins/MCPyLib/config.yml`. To replace a leaked token,
   run `/mcpylib token regenerate`. Editing the token in config.yml only takes effect
   after a restart, because `/mcpylib reload` does not refresh the active token.
3. **Client**: Python 3.11+. Install with `pip install mcpylib` or `uv add mcpylib`.
   Check the version with `importlib.metadata.version("mcpylib")`, not
   `mcpylib.__version__` (the 1.1.1 wheel reports "1.0.2"). A 1.2.x client needs a
   1.2.x plugin for `edit()`; older clients work, but use a slower `edit()` path.
   Doors and beds in `edit()` need plugin 1.2.1.
4. **Settings**: keep the token out of code. Put it in a git-ignored `.env`, using the
   same variable names as the mcpylib-mcp server:
   ```
   MCPYLIB_HOST=127.0.0.1
   MCPYLIB_PORT=65535
   MCPYLIB_TOKEN=paste-token-here
   ```
   The MCPyLib examples use `SERVER_IP` and `SERVER_TOKEN` instead; the bundled scripts
   accept both.
5. **Verify**: from this skill's directory run
   `python scripts/check_setup.py --player <name>`. It is read-only and reports Python,
   package and plugin compatibility, the TCP connection, the token, online players and
   the player's position and world.

## 2. Connect

```python
import os
from dotenv import load_dotenv  # python-dotenv is installed with mcpylib
from mcpylib import MCPyLib

load_dotenv()
with MCPyLib(
    ip=os.getenv("MCPYLIB_HOST", "127.0.0.1"),
    port=int(os.getenv("MCPYLIB_PORT", "65535")),
    token=os.environ["MCPYLIB_TOKEN"],
    timeout=30.0,  # seconds per request; raise it for big edit()/getblocks() calls
) as mc:
    print(mc.list()["players"])
```

- The constructor does not connect. The first call opens one persistent socket, and
  later calls reuse it. Use `with` or call `mc.close()`. Each open connection occupies
  one of the plugin's `max-connections` slots (default 10); beyond that, new clients
  get `CommandError: Server busy ...`. The plugin closes connections idle for
  `server.idle-timeout-seconds` (default 300), and client 1.2.0 reconnects by itself.
- One client = one socket = one request at a time. It is not thread-safe, so use one
  client per thread.
- Set `timeout` above your slowest call. With the 1.2.0 client a timeout raises
  `MCConnectionError` and is not retried, but the command may still have run. A
  1.1.x client re-sends it once, so it can run twice.

## 3. World model

- Axes: +X east, -X west, +Z south, -Z north, +Y up. One chunk is 16x16 columns, with
  chunk coordinates `x >> 4`, `z >> 4`.
- Default overworld build height is **Y -64 to 319**. The plugin does not validate
  coordinates. Out-of-range writes silently do nothing (`setblock` still returns 1),
  and reads return `minecraft:void_air`.
- **All block, entity-summon, particle and world calls act on the main overworld**
  (the first world loaded). A player in the Nether still reports Nether coordinates
  from `getPos`, so building there lands in the overworld. Check
  `mc.getEntityStatus(player_uuid)["world"]`: names ending in `_nether` or `_the_end`
  are other dimensions.
- `getPos(name)` returns the integer block containing the player's feet. The block
  they stand on is `y - 1`. Use floats with `+ 0.5` to centre teleports and summons.
- Yaw: 0 = south (+Z), 90 = west, 180 = north, 270 = east. Facing vector:
  `dx = -sin(yaw)`, `dz = cos(yaw)`. Pass yaw and pitch **together**, or neither is
  sent; `teleport` without them turns the player to face south.
- `fill`, `getblocks` and `clone` corners are **inclusive** and can be given in any
  order, so `fill(0, 64, 0, 10, 64, 10, ...)` covers 11x1x11 blocks.

## 4. Block names, states and NBT

- Ids such as `"minecraft:oak_planks"` or `"oak_planks"`. The prefix is optional (keep
  it lower case) and the id is case-insensitive. They must be block ids: `"brick"` is
  the item and `"bricks"` the block. `setblock`, `fill` and `edit()` reject item ids
  (`Invalid block type: brick (this is an item, not a placeable block)`). Reads
  always return `"minecraft:<id>"` types only, never states.
  Treat `air`, `cave_air` and `void_air` as empty.
- `block_state` takes any vanilla property of the block, with vanilla values as
  strings (numbers and booleans are converted): stairs `facing`/`half`/`shape`, slab
  `type` (`top`, `double`), door `half` (`lower`/`upper`) and `hinge`, bed `part`,
  `lit`, leaves `persistent`, snow `layers`, crop `age`, lantern `hanging`, chest
  `type` (`left`/`right`), sign `rotation` (`0`-`15`), and so on. Bukkit enum names
  still work for `facing`, `rotation` (`north`, `south_south_west`), `axis`, `half`
  (`top`/`bottom`), `shape`, `waterlogged`, `open` and `powered`. A key that is not
  a property of that block raises `Unsupported property '<key>=<value>' for
  minecraft:<id>`; the exception is those eight alias names, which are ignored on
  blocks that lack them.
- `nbt` supports `CustomName` (containers, plain text; JSON text shows up literally)
  and `Text1`..`Text4` (sign front lines). Everything else, including chest `Items`,
  is silently ignored.

## 5. Pick the right call

| Need | Call | Notes |
|---|---|---|
| 1-20 blocks with physics/updates | `setblock(x, y, z, block, block_state=None, nbt=None)` | One round trip each |
| One material, cuboid | `fill(x1, y1, z1, x2, y2, z2, block)` | No physics, no states, **no size limit**: split it yourself |
| Mixed blocks, any shape | `edit(x, y, z, blocks)` | Fastest; `blocks[dx][dy][dz]` from the min corner |
| Copy a region with states | `clone(x1, y1, z1, x2, y2, z2, dx, dy, dz)` | Max 32,768 blocks; chest contents not copied |
| Read one / many | `getblock(x, y, z)` / `getblocks(x1, y1, z1, x2, y2, z2)` | Types only, `[x][y][z]` from the min corner |

`edit()` arrays must be **rectangular**: every `blocks[x]` has the same number of
rows, and every `blocks[x][y]` the same length. Cells are a block id `str`, `None`
(leave unchanged), or `{"block": id, "block_state": {...}, "nbt": {...}}`.
Build them with comprehensions; `[[[None]*sz]*sy]*sx` aliases its rows:

```python
blocks = [[[None for _ in range(sz)] for _ in range(sy)] for _ in range(sx)]
blocks[0][0][0] = "stone"
blocks[1][0][0] = {"block": "oak_stairs", "block_state": {"facing": "north"}}
placed = mc.edit(x0, y0, z0, blocks)  # returns how many non-None cells were written
```

`edit()` writes every cell without block updates, dict cells included: no physics
and no neighbour updates, and string cells also skip the lighting recalculation.
Sand floats, water stays still, fences, panes and walls don't connect, and new light
sources may stay dark. Place torches, lanterns, redstone and other update-dependent
blocks with `setblock()` afterwards. Dict cells with `block_state` or `nbt`, and
block-entity blocks such as `"chest"` or signs, go through a slower Bukkit pass, so
they get proper block entities.

Doors, beds and tall plants work in `edit()` (plugin 1.2.1). Give one cell (the
door's lower half, the bed's foot, or just `"red_bed"`) and the plugin adds the
other half (door: one block up; bed: the head, one block toward `facing`), replacing
whatever is there, unless the array sets that position itself. With both halves in
the array, any order works. Added halves are not counted in the return value.
`setblock()` runs physics, so place a door's upper half first and a bed's head
first, then the other half.

## 6. Performance rules

1. Every call waits for the next tick of the server's main thread: up to **one tick
   (~50 ms)** per round trip, so about 20 sequential calls per second. 1,000
   `setblock` calls take about 50 s; one 1,000-block `edit()` takes about 0.05 s.
2. Batch everything: use `edit()` for mixed blocks and `fill()` for a single material.
   Never loop `setblock` over large areas.
3. Keep each `edit`/`fill`/`getblocks` call to about **65,536 cells** (for example
   16x256x16). The server freezes while a call runs: a 50,000-block fill took 0.76 s
   in the repository's pre-1.2.0 benchmark, and the 1.2.0 changelog reports about
   60 ms for a 16,384-block `edit()` on Paper 26.3. Split along chunk boundaries
   (x and z multiples of 16).
4. Reuse one client for the whole script, and never create a client per call.
5. Work near loaded chunks. Far coordinates force chunk loading or generation on the
   main thread.
6. For polling loops, budget calls (each about 50 ms) and set
   `logging.log-commands: false` in the plugin config to stop console spam.

## 7. Safety rules (follow these unless the user explicitly overrides them)

1. **Read before write.** Before any write that can replace blocks, `getblocks` the
   target box, count the non-air cells that would change, and report that count and
   the box. `python scripts/snapshot.py save ...` stores those blocks for undo.
2. **Confirm destructive or large operations** with the user first: replacing non-air
   blocks, clearing to air, anything over about 10,000 blocks, `kill()`, `clear()`,
   changing other players' gamemode or position, and world-wide settings (time,
   weather, difficulty, gamerule, worldborder).
3. **Only write cells that change.** Put `None` in every cell you don't intend to
   change. Never push an unchanged `getblocks` result back through `edit()`: reads
   carry no states, so stairs, logs and doors reset and container contents are lost.
4. **Never call `kill("all")` or `kill("<type>")` on a shared world.** They remove
   every loaded item frame, armor stand, painting, pet, villager and dropped item in
   the overworld (up to 1,000 per call). Track the UUIDs you summon and remove those
   with `removeEntity`.
5. **Prefer dedicated methods to console commands.** `exec`, `tellraw`,
   `fillbiome`, `placeFeature`, `placeStructure`, `placeJigsaw`, `placeTemplate` and
   `spreadplayers` dispatch console commands. They return `True` even when the
   command fails, the console can run anything (never build commands from untrusted
   text), and plugins older than 1.2.0 freeze the server on them.
6. **Protect the token.** Never print it, commit it, or pass it on a shared command
   line. The token gives full control of the server, and the default
   `server.host: '0.0.0.0'` listens on every interface, so use `127.0.0.1` for
   local-only access or firewall the port. (Plugin 1.1.x ignores `server.host`.)

## 8. Errors

```python
from mcpylib import AuthenticationError, CommandError, MCPyLibError
from mcpylib import ConnectionError as MCConnectionError  # don't shadow the builtin

try:
    mc.setblock(0, 64, 0, "minecraft:stone")
except AuthenticationError:   # server said "Invalid token"
    ...
except MCConnectionError:     # can't connect; with client 1.2.0 also timeouts and broken sockets
    ...
except CommandError as exc:   # any other server error text, e.g. "Player not found: Steve"
    ...
except OSError:               # 1.1.x clients raise raw socket errors and timeouts instead
    ...
```

`mcpylib.ConnectionError` is not the builtin `ConnectionError`. All three mcpylib
exceptions subclass `MCPyLibError`.

The server drops `null` values from responses. Dict results therefore **omit** absent
fields (for example empty equipment slots, `custom_name`, non-living `health`, or
`item` of an empty slot), so read them with `.get()`.

## 9. Bundled scripts (run from this skill's directory)

- `scripts/check_setup.py`: read-only environment and connection check (section 1).
- `scripts/snapshot.py`: `save` a box to JSON, `diff` it against the world, and
  `restore` it (block types only, chunked, dry run unless `--apply`).

For building and minigames, see the sibling skills **mcpylib-building** and
**mcpylib-minigames**. To drive the server through MCP tools instead of scripts, see
**mcpylib-mcp**.
