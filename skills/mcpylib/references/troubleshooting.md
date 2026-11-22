# MCPyLib troubleshooting

Start with `python scripts/check_setup.py --player <name>`. It is read-only and tells
you which layer is failing. Each entry below lists a symptom, its cause in the
1.2.2 code, and the fix.

## Contents

- [Connection](#connection)
- [Authentication](#authentication)
- [Version mismatches](#version-mismatches)
- [Error messages from commands](#error-messages-from-commands)
- [Results look wrong](#results-look-wrong)
- [Speed and lag](#speed-and-lag)
- [Server froze](#server-froze)
- [Security](#security)

## Connection

**`ConnectionError: Failed to connect to HOST:PORT: ... refused`**
- **Cause:** the plugin isn't listening at that address.
- **Fix:**
  - Run `/plugins` and check that MCPyLib is green.
  - Look in the console for `Server listening on ...:PORT`.
  - Check `server.port` in `plugins/MCPyLib/config.yml`. A new port needs a full server
    restart; `/mcpylib reload` does not rebind the socket.
  - If startup failed with `Failed to start network server`, another process holds
    the port, or `server.host` is not an address of this machine.
  - With `server.host: '127.0.0.1'`, only clients on the server machine can connect.
    Use `0.0.0.0` (or the machine's LAN address) for remote scripts, and restart.

**Connect times out**
- **Cause:** a firewall or NAT sits in the way, or the host is wrong.
- **Fix:** open or forward the TCP port. For a remote server, use its public address.

**`CommandError: Server busy: max-connections (10) reached`**
- **Cause:** every connection slot is taken. The plugin serves at most
  `server.max-connections` sockets (default 10), and each open client (including the
  mcpylib-mcp server and forgotten scripts) holds one. Idle connections are closed
  after `server.idle-timeout-seconds` (default 300).
- **Fix:** close clients you don't need with `mc.close()` or use `with`. Raise
  `max-connections` in config.yml and restart if you need more.

**It connects, but requests hang until they time out**
- **Cause 1:** the server's main thread is frozen or very busy. See
  [Server froze](#server-froze) and [Speed and lag](#speed-and-lag).
- **Cause 2:** a plugin older than 1.2.0 queues connections beyond
  `max-connections` without answering them. Close other clients.

**`AttributeError: 'NoneType' object has no attribute 'settimeout'`**
- **Cause:** a 1.1.x client tried to reuse a connection that the server had closed
  (idle timeout or server restart). Client 1.2.0 reconnects cleanly.
- **Fix:** upgrade the client, or catch the error and create a new `MCPyLib`
  object.

## Authentication

**`AuthenticationError: Invalid token`**
- **Fix:**
  - Copy the token again from `/mcpylib token`, run in the console or as op. Check for
    stray spaces or quotes in `.env`.
  - If you edited `security.token` in config.yml, **restart** the server.
    `/mcpylib reload` re-reads the file but keeps the old token in memory.
  - `/mcpylib token regenerate` replaces the token immediately and saves it.
- **Note:** the console also prints `Authentication token: ...` at every startup.

## Version mismatches

**`edit()` fails with `Missing parameters: x, y, z, blocks`**
- **Cause:** a 1.2.x client is talking to a plugin older than 1.2.0, which only
  understands the legacy array format.
- **Fix:** install `MCPyLib-Plugin-1.2.2.jar`, or pin the client to the plugin's
  version.

**`Unknown action: <name>`**
- **Cause:** the plugin is older than the client and lacks that action.

**The plugin doesn't load**
- **Cause:** plugin 1.2.x needs Java 25 and Paper/Spigot 26.1+ (`api-version: 26.1`).
  On older setups the console shows `UnsupportedClassVersionError` or an API-version
  error.

**`mcpylib.__version__` prints `1.0.2`**
- **Cause:** that is the stale string inside the 1.1.1 PyPI wheel.
- **Fix:** check the installed version with
  `python -c "import importlib.metadata as m; print(m.version('mcpylib'))"`.

## Error messages from commands

| Message | Meaning and fix |
|---|---|
| `Player not found: X` | X is offline or misspelt. `getPos`, `teleport`, `gamemode` and `give` need the exact name (case-insensitive). Boss bar `addplayer`/`removeplayer` say just `Player not found` |
| `Invalid block type: X` | Unknown name (typo, modded `namespace:id`, or an upper-case `MINECRAFT:` prefix). Nothing was placed |
| `Invalid block type: X (this is an item, not a placeable block)` | An item id such as `brick` (the block is `bricks`) or `diamond` (`diamond_block`). Nothing was placed |
| `Invalid block type in palette[i]: X` | Unknown name or item id inside an `edit()` array. Nothing was written |
| `... Unsupported property 'K=V' for minecraft:X` | That block has no property `K`, or `V` is not a valid value for it. Check the vanilla block states (F3 debug screen or the wiki). With `setblock` the block was still placed in its default state |
| `... No enum constant org.bukkit.block.BlockFace.X` | A bad value for `facing` or `rotation`. Use vanilla values (`north`, `0`-`15`) |
| `Region too large (max 32768 blocks): N` | `clone` limit. Split the region |
| `Amount must be between 1 and 64` | `give` limit. Call it several times |
| `Value out of range: N (valid: 0-24000)` | `time("set", ...)` limit. Use `add` for relative changes |
| `Invalid display slot: X` | Use `sidebar`, `player_list` or `below_name` |
| `Invalid structure: village` | `locate` needs structure ids such as `village_plains`, not tags |
| `Objective already exists: X` / `BossBar already exists: X` / `Team already exists: X` | Left over from a crashed run. Remove it first, or use the cleanup step in mcpylib-minigames |
| `Entity not found: <uuid>` | The entity died, despawned or was removed, or its chunk is unloaded |
| `Entity is not a LivingEntity` / `... not a Mob` / `Entity does not support equipment` | AI, target, damage, equipment and attribute calls need living entities or mobs |
| `Failed to set entity equipment: ...` after the gear appeared | `drop_chances` only works on mobs; leave it out for armor stands and players |
| `Failed to spawn particle: ...` | That particle needs extra data (dust, block, item, ...). Pick a data-free particle |
| `Error executing command: ...` | Usually a wrong JSON type, or `null` sent for a key the handler requires |

## Results look wrong

**Blocks appear in the wrong place, or not at all**
- All block and summon calls act on the **main overworld**. A player in the Nether
  reports Nether coordinates.
- Y outside -64..319 is silently ignored.
- Floats are truncated toward zero, so `-10.7` becomes `-10`. Call `math.floor()`
  on entity positions before using them as block coordinates.

**The region is one block bigger than expected**
- `fill`, `getblocks` and `clone` corners are inclusive.

**Blocks are shifted or scrambled after `edit()`**
- The array was ragged. Every `blocks[x]` must have the same number of rows, and
  every row the same length.

**Sand floats, water doesn't flow, fences and panes don't connect, redstone is dead, new lights stay dark**
- **Cause:** `edit()` and `fill()` skip physics and neighbour updates, and `edit()`
  also skips the lighting update.
- **Fix:** place those blocks with `setblock()` afterwards, or use full blocks, such
  as glass instead of panes.

**Stairs, logs or doors lost their orientation after a restore**
- **Cause:** `getblocks` returns types only, so restores use default states.

**Leaves vanish over time**
- **Cause:** leaves placed as plain ids keep their default
  `distance=7, persistent=false` state and decay.
- **Fix:** place them with `{"block": "oak_leaves", "block_state": {"persistent": "true"}}`.

**Half doors or half beds**
- **Cause (`setblock`):** each call runs physics, so the half placed first breaks
  when its partner is missing.
- **Fix:** with `setblock`, place the door's `half=upper` first and then
  `half=lower`, or the bed's `part=head` first and then `part=foot`. Or use
  `edit()` on plugin 1.2.1+: give one cell (door's lower half, bed's foot, or just
  `"red_bed"`) and the other half is added.
- **Cause (`edit()`, plugin older than 1.2.1):** dict cells ran with block updates,
  so halves broke each other. Update the plugin.

**A chest named `{"text":"..."}`**
- **Cause:** `CustomName` is plain text.
- **Fix:** pass `"My Chest"`, not a JSON text component.

**Chest contents missing**
- **Cause:** the `Items` NBT key is ignored, and `clone` doesn't copy contents either.

**`KeyError` on a result dict**
- **Cause:** the server omits null fields, such as empty equipment slots,
  `custom_name`, non-living `health`, `item` of an empty slot, or the second ingredient
  `buy2`.
- **Fix:** use `.get()`.

**Sound doesn't play**
- **Cause:** unknown sound ids fail silently.
- **Fix:** check the id, for example `entity.experience_orb.pickup`.

**Title not shown**
- **Cause:** `title()` goes to one named player, and selectors like `@a` fail.
- **Fix:** loop over `list()`.

**Boss bar gone**
- **Cause:** bars live in plugin memory and are lost on a server restart
  (`/mcpylib reload` keeps them). Players who rejoin must be re-added with
  `addplayer`.

## Speed and lag

**The script is slow**
- **Cause:** each call costs about one server tick (~50 ms).
- **Fix:** replace `setblock` loops with one `edit()` or `fill()`.

**Server lags or freezes during a big job**
- **Cause:** one request runs on the main thread until it finishes.
- **Fix:**
  - Keep `edit`, `fill` and `getblocks` calls to about 65,536 cells each.
  - Avoid distant unloaded chunks, which cause generation.
  - Avoid `locate` on large worlds.

**`Timed out after ...s waiting for '<action>'`, or an operation ran twice**
- **Cause:** the reply took longer than the client's `timeout`. A 1.2.x client
  raises `MCConnectionError` and doesn't retry, but the command may still have run
  on the server. A 1.1.x client re-sends it once (so it can run twice) and raises
  `TimeoutError`.
- **Fix:** raise `MCPyLib(timeout=...)` above your slowest call, keep calls small,
  and check the world before repeating a non-idempotent call.

**Console flooded with `Executing command: ...`**
- **Fix:** set `logging.log-commands: false` in config.yml, then run
  `/mcpylib reload`. The logging flags are read live.

## Server froze

**The server stopped ticking after `exec`, `tellraw`, `fillbiome`, `placeFeature`, `placeStructure`, `placeJigsaw`, `placeTemplate` or `spreadplayers`**
- **Cause:** plugins older than 1.2.0 wait for a second main-thread task while
  already running on the main thread, which is a deadlock. The watchdog then
  reports the server as unresponsive.
- **Fix:** restart the server and update the plugin to 1.2.2 (1.2.0 fixed this).
  Until then, use the dedicated methods instead (see
  [api.md](api.md#console-command-wrappers)).

## Security

**The port is reachable from other machines**
- **Cause:** `server.host` is `0.0.0.0` (the default: every interface). Plugin
  1.1.x binds every interface whatever `server.host` says.
- **Fix:** set `server.host: '127.0.0.1'` and restart when only local scripts
  connect, and block the port in a firewall when remote clients don't need it.

**`security.require-token: false`**
- **Cause:** anyone who can reach the port controls the server.
- **Fix:** use it only on isolated test machines.

**Token leaked**
- **Fix:** run `/mcpylib token regenerate`, then update `.env` and any MCP client
  configs.
