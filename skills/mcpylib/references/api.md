# MCPyLib API reference (client and plugin 1.2.1)

Every signature line below matches `mcpylib/client.py` (checked by
`tools/validate.py`). The behaviour notes come from the plugin's
`CommandHandler.java`, which is more accurate than the older docs. There are 72
API methods, plus `close()`.

## Contents

- [Conventions](#conventions)
- [Connection](#connection): close
- [Blocks](#blocks): setblock, getblock, getblocks, fill, edit, clone
- [Players](#players): getPos, teleport, gamemode, give, effect, clearEffect, clear,
  experience, enchant, getItem, setItem, spawnpoint, advancement, list
- [Entities](#entities): summon, kill, getEntityPos, getEntityStatus, teleportEntity,
  setEntityVelocity, setEntityRotation, setEntityAI, setEntityTarget, removeEntity,
  getEntityEquipment, setEntityEquipment, damage, ride, attribute, addTag, removeTag,
  getTags
- [Villagers](#villagers): getVillagerData, setVillagerProfession, setVillagerTrades
- [World](#world): time, weather, difficulty, gamerule, defaultgamemode,
  setworldspawn, worldborder, forceload, locate, loot
- [Chat, sound, particles](#chat-sound-particles): say, tell, title, playsound,
  stopsound, particle
- [Scoreboard and teams](#scoreboard-and-teams): addObjective, removeObjective,
  setScore, getScore, setDisplaySlot, team
- [Boss bars](#boss-bars): bossbar
- [Console-command wrappers](#console-command-wrappers): exec, tellraw, fillbiome,
  placeFeature, placeStructure, placeJigsaw, placeTemplate, spreadplayers
- [Exceptions](#exceptions)

## Conventions

- Each method sends a JSON action of the same name (`edit` sends `bulkEdit`).
- Failures raise `CommandError` carrying the server's message. Error strings quoted
  here are what the plugin returns.
- **Main world**: block, summon, particle, loot, locate, forceload, worldborder, time,
  weather, difficulty and gamerule calls act on the first loaded world (the
  overworld). Player teleport and spawnpoint use the player's current world.
- **Names**: `getPos`, `teleport`, `gamemode`, `give` and `kill("player:...")` need the
  exact player name (case-insensitive). The other player methods also accept a
  prefix; when several online names match, the closest one in length wins silently.
  Always pass exact names.
- **Missing keys**: the server omits `null` values, so optional dict fields are absent
  rather than `None`. Read them with `.get()`.
- **Inclusive boxes**: `fill`, `getblocks` and `clone` include both corners. Corner
  order does not matter.
- Nothing checks coordinates against the world height (-64..319). Writes outside it
  are silently ignored.

## Connection

### close
`mc.close()`

Closes the persistent socket. `MCPyLib` is also a context manager
(`with MCPyLib(...) as mc:`). The constructor is
`MCPyLib(ip="127.0.0.1", port=65535, token="", timeout=10.0)` and does not
connect; the first request does.

Retries differ by client version:
- **1.2.x**: a timeout raises `MCConnectionError` (`Timed out after <t>s waiting for
  '<action>' (the command may still have run on the server)`) and is never retried.
  Only a reused connection that turns out to be dead before any reply byte arrives
  is reopened and the request sent once more.
- **1.1.x** (PyPI 1.1.1): any socket error, including a timeout, is retried once and
  the raw `OSError` re-raised, so a timed-out non-idempotent call can run twice.

## Blocks

`block_state` accepts every vanilla property of the block, with vanilla values:
`type` (`top`, `double`; chests `left`/`right`), `half` (`lower`/`upper` for doors),
`hinge`, `part`, `lit`, `persistent`, `layers`, `age`, `hanging`, `rotation`
(`0`-`15`), `power` and so on. Values are sent as strings; numbers and booleans are
converted. Bukkit enum aliases still work for `facing`, `rotation` (`north`,
`south_south_west`), `axis`, `half` (`top`/`bottom`), `shape`, `waterlogged`, `open`
and `powered`. Any other key that the block doesn't have fails with
`Unsupported property '<key>=<value>' for minecraft:<id>`; those eight alias names
are ignored on blocks that lack them. NBT keys that work: `CustomName` (containers,
plain text) and `Text1`..`Text4` (sign front lines). Other NBT keys are ignored.

### setblock
`mc.setblock(x, y, z, block_name, block_state=None, nbt=None) -> int`

Places one block **with physics**, so falling blocks fall, unsupported blocks pop off
and fluids flow. Then it applies `block_state` and `nbt`. Returns `1`, even for an
out-of-range Y where nothing happened.

Two-block blocks need both halves, in this order: a door's `half=upper` first, then
`half=lower`; a bed's `part=head` first, then `part=foot`. In the other order the
block update breaks the half placed first. `edit()` has no such ordering problem.

Errors:
- `Invalid block type: <name>`: nothing is placed (unknown name, or a `minecraft:`
  prefix not in lower case). Item ids get the suffix
  `(this is an item, not a placeable block)` (`brick`, `diamond`).
- `Failed to set block state: Unsupported property ...` or
  `Failed to set NBT data: ...`: the block was already placed with its default state.

### getblock
`mc.getblock(x, y, z) -> str`

Returns the block type, such as `"minecraft:stone"`, with no state. Air can be `air`,
`cave_air` or `void_air`; out-of-range Y gives `void_air`. An unloaded chunk is loaded,
or generated, to answer.

### getblocks
`mc.getblocks(x1, y1, z1, x2, y2, z2) -> List[List[List[str]]]`

Reads the inclusive box as `result[dx][dy][dz]`, starting at the minimum corner.
This is the same layout `edit()` takes. Types only. The server has no size limit, so
keep each request to about 65,536 cells, which returns about 1.3 MB of JSON.

### fill
`mc.fill(x1, y1, z1, x2, y2, z2, block_name) -> int`

Sets every cell of the inclusive box to one block type in its default state. There
are no physics and no neighbour updates, but lighting is updated. Returns the number
of cells processed, including any outside the world. **No size limit**: the server is
blocked for the whole call (50,000 cells took about 0.8 s in the repository's
pre-1.2.0 benchmark), so split large fills. Use `"air"` to clear. Item ids such as
`brick` fail with `Invalid block type: brick (this is an item, not a placeable block)`.

### edit
`mc.edit(x, y, z, blocks) -> int`

Bulk-writes `blocks[dx][dy][dz]` with the minimum corner at `(x, y, z)`. A cell is a
block id `str`, `None` (leave unchanged), or
`{"block": id, "block_state": {...}, "nbt": {...}}`. Returns the number of non-None
cells written (on the fast path, cells outside the world are neither written nor
counted; halves added for doors and beds are not counted).

- The array must be rectangular, because the sizes come from `len(blocks)`,
  `len(blocks[0])` and `len(blocks[0][0])`.
- 1.2.x clients send a compressed palette/RLE payload, which needs plugin 1.2.x;
  older plugins answer `Missing parameters: x, y, z, blocks`. 1.1.x clients send the
  legacy nested array, which works but goes through the slower Bukkit path.
- On the fast path (used whenever the plugin's NMS access works), string cells are
  written straight into chunk sections: no physics, no neighbour updates, no
  lighting recalculation, and cells outside the world are skipped. If NMS access
  fails, every cell goes through Bukkit `setType` without physics instead, which
  does update lighting.
- Dict cells **with `block_state` or `nbt`**, and blocks with block entities
  (chests, signs, ...) or two halves (doors, beds, tall plants), get a second pass
  through the Bukkit API. It applies states and creates block entities, still
  without block updates. `{"block": "stone"}` alone behaves like a string cell.
- Doors, beds and tall plants can be given as one cell (the lower half, the bed's
  foot, or just `"red_bed"`): the other half is added (door: one block up; bed: the
  head, one block toward `facing`), replacing whatever is there, unless the array
  sets that position itself. With both halves given, any order works.
- `Invalid block type in palette[i]: <name>` aborts before anything is written.
  This includes item ids (`brick`, `diamond`).
- An unsupported `block_state` key aborts with
  `Failed to bulk edit (compressed): Unsupported property '<key>=<value>' for
  minecraft:<id>`. On the fast path
  every string cell was already written; on the Bukkit path only the cells before
  the failing one (in x, y, z order).

### clone
`mc.clone(x1, y1, z1, x2, y2, z2, dest_x, dest_y, dest_z) -> int`

Copies the inclusive source box so that its minimum corner lands on `dest`. It copies
block states but not block-entity data (chest items, sign text), and applies physics.
Returns the cell count.

- Maximum 32,768 cells. Larger boxes fail with
  `Region too large (max 32768 blocks): <n>`.
- An overlapping source and destination is copied in ascending x, y, z order and can
  smear.

## Players

### getPos
`mc.getPos(username) -> List[int]`

Returns `[x, y, z]`, the integer block containing the player's feet, in **whatever
world the player is in**. Fails with `Player not found: <name>` if the player is
offline.

### teleport
`mc.teleport(username, x, y, z, yaw=None, pitch=None) -> bool`

Teleports within the player's current world. Floats are allowed; add `0.5` to centre
on a block. Yaw and pitch only apply when both are given; **without them the player
ends up facing south and level (yaw 0, pitch 0)**, unlike `teleportEntity`, which
keeps the rotation. To keep the view, read `yaw` and `pitch` with `getEntityPos` and
pass them back. Returns `True`, or raises `Teleport failed`.

### gamemode
`mc.gamemode(username, mode) -> bool`

Modes: `survival`, `creative`, `adventure`, `spectator` (case-insensitive).

### give
`mc.give(username, item, amount=1) -> bool`

Adds one plain stack, with no enchantments or NBT.

- `amount` must be 1-64, otherwise `Amount must be between 1 and 64`.
- Items that don't fit a full inventory are silently lost.
- `air` is rejected.

### effect
`mc.effect(username, effect_type, duration=30, amplifier=0, hide_particles=False) -> bool`

- `duration` is in seconds. `amplifier` 0 means level I.
- Effect names are registry ids such as `speed`, `jump_boost` or
  `minecraft:night_vision`. Legacy Bukkit names such as `INCREASE_DAMAGE` also work.
- Returns the server's success flag.

### clearEffect
`mc.clearEffect(username, effect_type=None) -> bool`

Removes one effect, or all of them when `effect_type` is `None`.

### clear
`mc.clear(username, item=None, max_count=-1) -> int`

Removes items and returns how many were removed. It scans all 41 slots **including
armor and off-hand**. `item=None` matches everything, and `max_count=-1` means no
limit. This cannot be undone.

### experience
`mc.experience(username, action, amount=0, target="points") -> dict`

- `action`: `add`, `set` or `query`. `target`: `points` or `levels`.
- `set` with `points` sets the progress bar to `amount / points-to-next-level`,
  clamped to 0..1, within the current level. It does not set the total.
- Returns `{"level": int, "points": int, "progress": float}`. `points` is the total
  XP computed from `level` and `progress` (vanilla formula), so it is correct after
  `set` and after adding levels.

### enchant
`mc.enchant(username, enchantment, level=1) -> bool`

Enchants the item in the main hand. Levels above the vanilla maximum are allowed.
Errors are `Player is not holding an item` and `Invalid enchantment: <name>`.

### getItem
`mc.getItem(username, slot) -> dict`

Slots 0-40:

| Slot | Meaning |
|---|---|
| 0-8 | hotbar |
| 9-35 | inventory |
| 36 | boots |
| 37 | leggings |
| 38 | chestplate |
| 39 | helmet |
| 40 | off-hand |

Returns `{"item": "minecraft:diamond_sword", "amount": 1, "enchantments": {"sharpness": 5}}`.
`enchantments` appears only when present. An empty slot returns `{"amount": 0}`, with
no `item` key.

### setItem
`mc.setItem(username, slot, item, amount=1) -> bool`

Replaces the slot (same numbering as `getItem`) with a plain stack; whatever was in
the slot is lost. Keep `amount` within the item's stack size.

### spawnpoint
`mc.spawnpoint(username, x=None, y=None, z=None) -> bool`

Sets a forced respawn point in the player's current world. If x, y and z are not all
given, the player's current position is used.

### advancement
`mc.advancement(username, action, advancement_key) -> bool`

- `action`: `grant` (all criteria), `revoke` (all criteria), or `query` (returns
  whether the advancement is done).
- Keys look like `story/mine_stone`, which assumes the `minecraft` namespace, or
  `namespace:path`.

### list
`mc.list() -> dict`

Returns
`{"online_count": n, "max_players": n, "players": [{"name": str, "uuid": str, "gamemode": "SURVIVAL"}]}`.
A player is an entity, so the `uuid` works with the entity methods.

## Entities

Entity methods take UUID strings. Entities in unloaded chunks are not found, and give
`Entity not found: <uuid>`.

### summon
`mc.summon(entity_type, x, y, z) -> str`

Spawns the entity **in the main overworld** and returns its UUID. Types are entity
ids such as `zombie` or `minecraft:armor_stand`. Players and non-spawnable types fail
with `Cannot summon entity type: <type>`.

### kill
`mc.kill(selector) -> int`

Returns how many entities were affected, at most 1,000 per call. Selectors:

- `"all"`: every loaded non-player entity in the main overworld, including item
  frames, paintings, armor stands, boats, minecarts, pets, villagers and dropped
  items.
- `"<type>"`: every loaded entity of that type there.
- `"player:<name>"`: sets that player's health to 0.

Prefer `removeEntity` on UUIDs you created.

### getEntityPos
`mc.getEntityPos(entity_uuid) -> dict`

Returns `{"x", "y", "z", "yaw", "pitch"}` as floats. Works for players too; get the
UUID from `list()`.

### getEntityStatus
`mc.getEntityStatus(entity_uuid) -> dict`

Keys always present:
- `uuid`
- `type`, such as `"minecraft:zombie"`
- `is_valid`, `is_dead`
- `world` (the world name)
- `position` `{x, y, z}` and `velocity` `{x, y, z}`

Keys present only sometimes:
- `custom_name`: only when the entity has one.
- `health`, `max_health`, `has_ai`: only for living entities.

### teleportEntity
`mc.teleportEntity(entity_uuid, x, y, z, yaw=None, pitch=None) -> bool`

Moves the entity within its own world. Unless both yaw and pitch are given, the
current rotation is kept. An entity that rides something is dismounted first. Returns
`False`, without raising, when the server refuses, for example for an entity that
carries passengers.

### setEntityVelocity
`mc.setEntityVelocity(entity_uuid, vx, vy, vz) -> bool`

Velocity in blocks per tick. Each component is clamped to +/-10.

### setEntityRotation
`mc.setEntityRotation(entity_uuid, yaw, pitch) -> bool`

Non-player entities are rotated in place, including mounted entities and entities
carrying passengers. Players are rotated by a teleport and stay on their vehicle. If
a player's teleport is cancelled (by another plugin, for example), it raises
`CommandError: Could not rotate player <name>: the teleport was cancelled ...`.

- Yaw: 0 = south, 90 = west, 180 = north, 270 = east.
- Pitch: -90 = up, 90 = down.
- To face a point: `yaw = degrees(atan2(-dx, dz))`.

### setEntityAI
`mc.setEntityAI(entity_uuid, enabled) -> bool`

Living entities only (`Entity is not a LivingEntity`). `False` freezes all behaviour,
which is useful for statues and NPCs.

### setEntityTarget
`mc.setEntityTarget(entity_uuid, target_uuid=None) -> bool`

Mobs only. The target must be a living entity; players are allowed. `None` clears the
target.

### removeEntity
`mc.removeEntity(entity_uuid) -> bool`

Removes one entity, with no drops. It refuses players.

### getEntityEquipment
`mc.getEntityEquipment(entity_uuid) -> dict`

Keys: `helmet`, `chestplate`, `leggings`, `boots`, `main_hand`, `off_hand`. A key is
present only when its slot is filled; values look like `"minecraft:iron_sword"`.

### setEntityEquipment
`mc.setEntityEquipment(entity_uuid, equipment, drop_chances=None) -> bool`

- `equipment` maps the slot names above to item ids (plain single items). Unknown
  slot names are silently ignored.
- `drop_chances` maps the same names to 0.0-1.0 and works on **mobs only**. On
  armor stands and players leave it out: it raises
  `Failed to set entity equipment: ...` after the equipment was already applied.
- `equipment` works on any living entity, including armor stands and players;
  other entities fail with `Entity does not support equipment: <uuid>`.
- A helmet stops zombies and skeletons from burning in daylight.

### damage
`mc.damage(entity_uuid, amount, source_uuid=None) -> bool`

Living entities only. If `source_uuid` is given and found, the damage is attributed
to that entity.

### ride
`mc.ride(passenger_uuid, vehicle_uuid=None) -> bool`

Mounts the passenger on the vehicle, or dismounts it when `vehicle_uuid` is `None`.
Returns the server's success flag.

### attribute
`mc.attribute(entity_uuid, attribute_name, action="get", value=None) -> dict`

- Names are registry ids such as `max_health`, `movement_speed`, `attack_damage` or
  `scale`. Legacy forms such as `GENERIC_MAX_HEALTH` are accepted.
- `get`, or `set`, which changes the base value and requires `value`.
- Returns `{"base_value": float, "value": float}`.
- Raising `max_health` does not heal the entity.

### addTag
`mc.addTag(entity_uuid, tag) -> bool`

Returns `True` if the tag was added, or `False` if the entity already had it.

### removeTag
`mc.removeTag(entity_uuid, tag) -> bool`

Returns `True` if the tag was removed, or `False` if the entity didn't have it.

### getTags
`mc.getTags(entity_uuid) -> List[str]`

Returns the entity's scoreboard tags. There is no find-by-tag call, so keep the UUIDs
you create.

## Villagers

### getVillagerData
`mc.getVillagerData(villager_uuid) -> dict`

Returns:
```
{"profession": "LIBRARIAN", "level": 1-5,
 "trades": [{"buy1": {"item", "amount"}, "buy2": {...}, "sell": {...}, "uses", "max_uses"}]}
```
`buy2` is present only when the trade has a second ingredient.

### setVillagerProfession
`mc.setVillagerProfession(villager_uuid, profession) -> bool`

Professions (case-insensitive): armorer, butcher, cartographer, cleric, farmer,
fisherman, fletcher, leatherworker, librarian, mason, nitwit, none, shepherd,
toolsmith, weaponsmith. For a real job on a villager with 0 XP, the plugin also
sets 1 XP, so vanilla AI doesn't reset the profession.

### setVillagerTrades
`mc.setVillagerTrades(villager_uuid, trades) -> bool`

Replaces every trade. Each trade dict has:
- `buy1`: `{"item": id, "amount": n}`, required.
- `buy2`: optional second ingredient.
- `sell`: required.
- `max_uses`: default 10.
- `experience_reward`: default `True`.

Items are plain, with no NBT. Set the profession first, then the trades: changing
the profession afterwards gives the villager that profession's trades.

## World

### time
`mc.time(action, value=None) -> int`

- `set`: 0-24000 ticks. 0 = sunrise, 6000 = noon, 13000 = night, 18000 = midnight.
- `add`: any integer.
- `query`: read only.

Values must be numbers; `"day"` fails. Returns the main world's time of day.

### weather
`mc.weather(condition, duration=None) -> bool`

Conditions: `clear`, `rain`, `thunder`. `duration` is in seconds.

### difficulty
`mc.difficulty(level) -> bool`

Levels: `peaceful`, `easy`, `normal`, `hard`. Applies to the main world.

### gamerule
`mc.gamerule(rule, value=None) -> str`

- Use the server version's rule ids; 26.x uses snake_case such as `keep_inventory`
  or `mob_griefing`. Legacy camelCase names are tried as a fallback.
- Only boolean and integer rules can be set. Pass the value as a string, such as
  `"true"` or `"3"`.
- Returns the current value as a string.

### defaultgamemode
`mc.defaultgamemode(mode) -> bool`

Same modes as `gamemode`.

### setworldspawn
`mc.setworldspawn(x, y, z) -> bool`

Sets the main world's spawn. Returns the server's success flag.

### worldborder
`mc.worldborder(action, value=None, time=None, x=None, z=None) -> dict`

Acts on the main world:

| Action | Arguments | Returns |
|---|---|---|
| `get` | none | `{"size", "center_x", "center_z", "damage_amount", "damage_buffer", "warning_distance", "warning_time"}` |
| `set` | `value` = size, `time` = transition in seconds | `{"size"}` |
| `add` | `value` = change in size, `time` = transition in seconds | `{"size"}`, the new target size |
| `center` | `x`, `z` | `{"center_x", "center_z"}` |
| `damage` | `value` = damage per block | `{"damage_amount"}` |
| `warning` | `value` = distance (int), `time` = seconds | `{"warning_distance", "warning_time"}` |

### forceload
`mc.forceload(action, x, z) -> bool`

Takes **block** coordinates and acts on the chunk that contains them (`x >> 4`,
`z >> 4`) in the main world. `add` and `remove` return `True`. `query` returns
whether that chunk is force-loaded.

### locate
`mc.locate(structure, x=None, z=None) -> dict`

- Takes structure ids, not tags. Examples: `village_plains`, `village_desert`,
  `village_savanna`, `village_snowy`, `village_taiga`, `stronghold`, `mansion`,
  `monument`, `ancient_city`, `trial_chambers`, `desert_pyramid`, `jungle_pyramid`,
  `pillager_outpost`. `"village"` is a tag and fails with `Invalid structure`.
- Searches up to 100 chunks from (`x`, `z`) (both needed) or from the world spawn.
- Returns `{"found": False}`, or `{"found": True, "x", "y", "z"}`.
- Slow searches block the server.

### loot
`mc.loot(loot_table, x, y, z) -> int`

Rolls a loot table, such as `chests/simple_dungeon`, and drops the items at the
position in the main world. Returns the number of item stacks dropped. It does not
fill containers.

## Chat, sound, particles

### say
`mc.say(message) -> bool`

Broadcasts `[Server] <message>` to everyone. Legacy `§` colour codes work.

### tell
`mc.tell(username, message) -> bool`

Sends the plain message to one player, with no sender prefix.

### title
`mc.title(username, title="", subtitle="", fade_in=10, stay=70, fade_out=20) -> bool`

Shows a title to one player. Selectors such as `@a` don't work. Times are in ticks
(20 = 1 s), and text is legacy text with `§` codes. There is no action-bar variant.

### playsound
`mc.playsound(username, sound, source="master", x=None, y=None, z=None, volume=1.0, pitch=1.0) -> bool`

Plays a sound to one player, at their position unless x, y and z are all given.

- Sound keys look like `entity.experience_orb.pickup`, `block.note_block.pling`,
  `entity.player.levelup` or `ui.toast.challenge_complete`; `minecraft:` is optional.
- Unknown names fail silently: nothing plays and no error is raised.
- An invalid `source` falls back to `master`.
- `pitch` ranges from 0.5 to 2.0. A `volume` above 1 only widens the hearing range.

### stopsound
`mc.stopsound(username, sound=None, source=None) -> bool`

With `sound`, stops that sound, limited to `source` if given. Without `sound`, stops
**all** sounds and ignores `source`.

### particle
`mc.particle(particle_type, x, y, z, count=1, dx=0, dy=0, dz=0, speed=0) -> bool`

Spawns particles in the main overworld, visible to nearby players.

- Ids that work include `flame`, `soul_fire_flame`, `heart`, `happy_villager`,
  `angry_villager`, `end_rod`, `totem_of_undying`, `firework`, `cloud`, `crit`,
  `enchanted_hit`, `smoke`, `large_smoke`, `explosion`, `portal`, `note`, `snowflake`
  and `witch`.
- Particles that need extra data (`dust`, `block`, `item`, `falling_dust`,
  `entity_effect`, `vibration`, ...) fail.
- `dx`, `dy` and `dz` set the spread; `speed` sets the extra speed.

## Scoreboard and teams

All of these use the server's main scoreboard, which every player sees.

### addObjective
`mc.addObjective(name, criteria, display_name=None) -> bool`

- Criteria: `dummy` (set only by scripts), `deathCount`, `playerKillCount`,
  `totalKillCount`, `health`, `level`, `food`, `air`, `armor`, `xp`, `trigger`.
- Fails with `Objective already exists: <name>`.
- `display_name` defaults to `name`.

### removeObjective
`mc.removeObjective(name) -> bool`

Fails with `Objective not found: <name>`.

### setScore
`mc.setScore(objective, player, score) -> bool`

`player` is any score holder: a player name, or a label such as `"Time left"`, which
shows as a sidebar line.

### getScore
`mc.getScore(objective, player) -> int`

Returns `0` when no score is set.

### setDisplaySlot
`mc.setDisplaySlot(slot, objective=None) -> bool`

Slots: `sidebar`, `player_list`, `below_name`, plus per-team sidebars named after
the server's own enum: `sidebar_team_<color>` on Paper, `sidebar_<color>` on Spigot
(for example `sidebar_team_red`). `objective=None` clears the slot.

### team
`mc.team(action, name=None, members=None, option=None, value=None, display_name=None) -> dict`

| Action | Arguments | Returns |
|---|---|---|
| `add` | `name`, `display_name` (optional); fails if the team exists | `{"name"}` |
| `remove` | `name` | `{"removed": True}` |
| `join` | `name`, `members` (list of player names or entity UUID strings) | `{"added": n}` |
| `leave` | `name`, `members` | `{"removed_count": n}` |
| `modify` | `name`, `option`, `value` (strings) | `{"modified": True}` |
| `list` | none | `{"teams": [{"name", "display_name", "members", "size"}]}` |

`modify` options:
- `displayname`
- `color`: chat colour names such as `RED`, `BLUE`, `GOLD` or `DARK_AQUA`.
- `friendlyfire`, `seefriendlyinvisibles`: `"true"` or `"false"`.
- `prefix`, `suffix`

## Boss bars

### bossbar
`mc.bossbar(action, bar_id, title=None, color=None, style=None, progress=None, visible=None, username=None) -> dict`

Bars exist only in the plugin's memory. They are invisible to vanilla `/bossbar`,
vanish on a server restart (`/mcpylib reload` keeps them), and stay on screen if
your script crashes, so remove them in a `finally:` block. A full plugin reload
(with a plugin manager) loses track of them while they stay on players' screens
until those players rejoin.

| Action | Arguments | Returns |
|---|---|---|
| `add` | `title` (defaults to `bar_id`), `color`, `style`, `progress` (0.0-1.0, clamped), `visible` | `{"id"}` |
| `set` | any of `title`, `color`, `style`, `progress`, `visible` | `{"updated": True}` |
| `addplayer` | one `username` per call | `{"added": True}` |
| `removeplayer` | one `username` per call | `{"removed": True}` |
| `get` | none | `{"id", "title", "color", "style", "progress", "visible", "players"}` |
| `list` | none (`bar_id` is still required; pass any string) | `{"bars": [ids]}` |
| `remove` | none | `{"removed": True}` |

- Colors: `WHITE` (default), `PINK`, `BLUE`, `RED`, `GREEN`, `YELLOW`, `PURPLE`.
- Styles: `SOLID` (default), `SEGMENTED_6`, `SEGMENTED_10`, `SEGMENTED_12`,
  `SEGMENTED_20`.
- `add` silently replaces an invalid color or style with the default; `set` raises.
- A new bar has no players.
- Re-add players who rejoin.

## Console-command wrappers

These methods build a vanilla command and run it as the server console with
`Bukkit.dispatchCommand`, so coordinates refer to the main overworld.

- They return the dispatch result: `False` for an unknown command name, otherwise
  `True`, **even if the command itself failed** (bad syntax, unknown id, out of
  range). The reason only shows in the server console, so check the effect another
  way, for example with `getblock`.
- **Plugins older than 1.2.0 freeze the server** in these handlers: they waited on
  the main thread from the main thread, until the watchdog killed the server. Plugin
  1.2.0 fixed this. Confirm the plugin version first: with a 1.2.x client, the core
  skill's `check_setup.py` warns when the plugin is older than 1.2.0.
- The console can run any command. Never build a command from untrusted text, such
  as chat input or names with spaces or quotes.

### exec
`mc.exec(command) -> bool`

Runs a console command; a leading `/` is stripped. Prefer the dedicated methods. Use
it for things MCPyLib has no method for, such as an action-bar message
(`title Steve actionbar "Hello"`) or removing tagged entities
(`kill @e[tag=my_game]`).

### tellraw
`mc.tellraw(username, json_text) -> bool`

Runs `tellraw <username> <json_text>`. Build `json_text` with `json.dumps`, for
example `json.dumps({"text": "Hello", "color": "gold"})`. Servers on 26.x use the
1.21.5+ text component format, where click and hover events are written
`click_event` and `hover_event`.

### fillbiome
`mc.fillbiome(x1, y1, z1, x2, y2, z2, biome, filter_biome=None) -> bool`

Runs `fillbiome x1 y1 z1 x2 y2 z2 <biome>`, plus `replace <filter_biome>` when
given. Biome ids look like `minecraft:cherry_grove`. The vanilla command limits how
many blocks one call may change (a game rule, 32,768 by default), so split large
areas.

### placeFeature
`mc.placeFeature(feature, x=None, y=None, z=None) -> bool`

Runs `place feature <feature> [x y z]`, for example `minecraft:fancy_oak`. Without
all three coordinates the feature goes to the world spawn.

### placeStructure
`mc.placeStructure(structure, x=None, y=None, z=None) -> bool`

Runs `place structure <structure> [x y z]`, for example `minecraft:village_plains`.

### placeJigsaw
`mc.placeJigsaw(pool, target, max_depth, x=None, y=None, z=None) -> bool`

Runs `place jigsaw <pool> <target> <max_depth> [x y z]`. `max_depth` is 1-20.

### placeTemplate
`mc.placeTemplate(template, x=None, y=None, z=None, rotation="none", mirror="none", integrity=1.0, seed=0) -> bool`

Runs `place template <template> [x y z] <rotation> <mirror> <integrity> <seed>`. The
client always sends rotation and the arguments after it, so give x, y and z, or the
command is malformed. Rotations: `none`, `clockwise_90`, `180`,
`counterclockwise_90`. Mirror: `none`, `front_back`, `left_right`.

### spreadplayers
`mc.spreadplayers(center_x, center_z, spread_distance, max_range, usernames) -> bool`

Runs `spreadplayers <center_x> <center_z> <spread_distance> <max_range> false
<names...>`, which spreads the players in the main overworld, ignoring teams.

## Exceptions

```python
from mcpylib import MCPyLibError, AuthenticationError, CommandError
from mcpylib import ConnectionError as MCConnectionError
```

| Exception | Raised when |
|---|---|
| `MCPyLibError` | Base class of the three below |
| `MCConnectionError` | The TCP connection can't be opened; with 1.2.x clients also a timeout or a broken connection during a request. It is **not** the builtin `ConnectionError` |
| `AuthenticationError` | The server error text contains "token" (the server sends `Invalid token`) |
| `CommandError` | Any other server error, such as `Unknown action: <name>` or `Player not found: <name>` |
| `OSError` / `TimeoutError` | 1.1.x clients only: a send or receive failed twice (one automatic retry), and the socket error is re-raised unchanged |
| `json.JSONDecodeError` | The response line is not valid JSON |
