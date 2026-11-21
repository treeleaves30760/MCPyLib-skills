# mcpylib-mcp tools

All 86 tools of mcpylib-mcp 0.1.0, as printed by `mcpylib-mcp --list-tools`, with
the MCPyLib client method each one calls. Look those methods up in the API reference
of the **mcpylib** skill, which describes the same behaviour from the Python side.

- **read-only**: never changes the world; still available with `MCPYLIB_READ_ONLY=true`.
- **changes**: modifies the world without destroying anything.
- **destructive**: can overwrite or delete things that can't be restored. Confirm with
  the user first.

Groups (for `MCPYLIB_ALLOWED_TOOLS` and `MCPYLIB_DENIED_TOOLS`, written `group:<name>`):
server, blocks, players, world, entities, chat, scoreboard.

## Contents

- [server](#server)
- [blocks](#blocks)
- [players](#players)
- [world](#world)
- [entities](#entities)
- [chat](#chat)
- [scoreboard](#scoreboard)

## server

| Tool | What it does | Access | MCPyLib call |
|---|---|---|---|
| `get_players` | List online players (name, UUID, game mode) and the player limit. | read-only | `list` |
| `run_command` | Run any Minecraft command as the server console. The block limit does not apply. | destructive | `exec` |

## blocks

| Tool | What it does | Access | MCPyLib call |
|---|---|---|---|
| `get_block` | Return the block id at one position, e.g. `minecraft:stone`. | read-only | `getblock` |
| `get_blocks` | Read every block in a box, as text layers, an index array or block counts. | read-only | `getblocks` |
| `get_height_map` | For each column of an area, the Y of the highest non-air block, optionally ignoring leaves or plants. | read-only | `getblocks` |
| `set_block` | Place one block, with optional block state and sign text, replacing what is there. | destructive | `setblock` |
| `fill_region` | Fill a box with one block; use `air` to clear an area. | destructive | `fill` |
| `clone_region` | Copy a box of blocks to another place (at most 32,768 blocks, a plugin limit). | destructive | `clone` |
| `edit_blocks` | Place many different blocks in one call from a 3D array (MCPyLib's bulk edit). | destructive | `edit` |
| `build_from_layers` | Build from text layers: floor plans stacked bottom to top, each character one block. | destructive | `edit` |

## players

| Tool | What it does | Access | MCPyLib call |
|---|---|---|---|
| `get_player_position` | Block position of an online player's feet. | read-only | `getPos` |
| `teleport_player` | Teleport a player, optionally setting where they face. | changes | `teleport` |
| `set_gamemode` | Set a player's game mode. | changes | `gamemode` |
| `give_item` | Add items to a player's inventory. | changes | `give` |
| `get_inventory` | List a player's non-empty inventory slots with items, amounts and enchantments. | read-only | `getItem` |
| `set_inventory_slot` | Put an item stack into one slot, replacing what was there. | destructive | `setItem` |
| `clear_inventory` | Remove all items, or one item type, from a player's inventory. | destructive | `clear` |
| `enchant_held_item` | Enchant the item in a player's main hand. | changes | `enchant` |
| `apply_effect` | Give a player a status effect such as speed or night vision. | changes | `effect` |
| `clear_effects` | Remove one or all status effects. | changes | `clearEffect` |
| `get_experience` | A player's level, points and progress to the next level. | read-only | `experience` |
| `update_experience` | Add or set experience points or levels. | changes | `experience` |
| `set_spawnpoint` | Set where a player respawns. | changes | `spawnpoint` |
| `get_advancement` | Whether a player has completed an advancement. | read-only | `advancement` |
| `set_advancement` | Grant or revoke an advancement. | destructive | `advancement` |
| `spread_players` | Teleport players to random surface positions around a point (`/spreadplayers`). | changes | `spreadplayers` |

## world

| Tool | What it does | Access | MCPyLib call |
|---|---|---|---|
| `get_time` | Time of day: ticks, phase (day, sunset, night, sunrise) and clock time. | read-only | `time` |
| `set_time` | Set or advance the time, by preset (`day`, `noon`, `night`...) or ticks. | changes | `time` |
| `set_weather` | Clear, rain or thunder, optionally for a duration. | changes | `weather` |
| `set_difficulty` | Set the difficulty. | changes | `difficulty` |
| `get_gamerule` | Current value of a game rule. | read-only | `gamerule` |
| `set_gamerule` | Set a game rule and return the value the server now reports. | changes | `gamerule` |
| `set_world_spawn` | Set the world spawn point. | changes | `setworldspawn` |
| `set_default_gamemode` | Set the game mode new players get. | changes | `defaultgamemode` |
| `get_world_border` | The world border's size, centre, damage and warning settings. | read-only | `worldborder` |
| `set_world_border` | Change any combination of world-border settings in one call. | changes | `worldborder` |
| `get_chunk_force_loaded` | Whether the chunk containing a block is force-loaded. | read-only | `forceload` |
| `set_chunk_force_loaded` | Force-load a chunk, or stop force-loading it. | changes | `forceload` |
| `fill_biome` | Change the biome of a box. | destructive | `fillbiome` |
| `locate_structure` | Find the nearest structure of a type, such as a village. | read-only | `locate` |
| `place_feature` | Generate a feature (tree, ore vein...) as world generation does. | destructive | `placeFeature` |
| `place_structure` | Generate a whole structure (village, temple...). | destructive | `placeStructure` |
| `place_jigsaw` | Generate a jigsaw structure from a template pool. | destructive | `placeJigsaw` |
| `place_template` | Place a saved structure template. | destructive | `placeTemplate` |
| `spawn_loot` | Roll a loot table and drop the items at a position. | changes | `loot` |

## entities

| Tool | What it does | Access | MCPyLib call |
|---|---|---|---|
| `summon_entity` | Spawn an entity and return its UUID, which the other entity tools use. | changes | `summon` |
| `kill_entities` | Remove entities by type, a player, or all non-player entities (at most 1,000 per call). | destructive | `kill` |
| `remove_entity` | Delete one entity without drops. | destructive | `removeEntity` |
| `get_entity` | An entity's type, name, position, rotation, velocity, health and AI state. | read-only | `getEntityPos`, `getEntityStatus` |
| `teleport_entity` | Move an entity to an exact position. | changes | `teleportEntity` |
| `set_entity_velocity` | Push an entity by setting its velocity vector. | changes | `setEntityVelocity` |
| `set_entity_rotation` | Turn an entity without moving it. | changes | `setEntityRotation` |
| `set_entity_ai` | Turn a mob's AI on or off. | changes | `setEntityAI` |
| `set_entity_target` | Make a mob attack an entity, or clear its target. | changes | `setEntityTarget` |
| `get_entity_equipment` | Items in an entity's armour and hand slots. | read-only | `getEntityEquipment` |
| `set_entity_equipment` | Equip a mob or armor stand, with optional drop chances. | destructive | `setEntityEquipment` |
| `damage_entity` | Hurt a living entity. | destructive | `damage` |
| `ride_entity` | Make one entity ride another, or dismount it. | changes | `ride` |
| `get_entity_attribute` | Base and effective value of an attribute, e.g. `max_health`. | read-only | `attribute` |
| `set_entity_attribute` | Set an attribute's base value, e.g. `scale` 2. | changes | `attribute` |
| `get_entity_tags` | An entity's scoreboard tags. | read-only | `getTags` |
| `update_entity_tags` | Add and remove scoreboard tags. | changes | `addTag`, `getTags`, `removeTag` |
| `get_villager` | A villager's profession, level and trades. | read-only | `getVillagerData` |
| `set_villager_profession` | Change a villager's profession, which resets its trades. | destructive | `setVillagerProfession` |
| `set_villager_trades` | Replace all of a villager's trades. | destructive | `setVillagerTrades` |

## chat

| Tool | What it does | Access | MCPyLib call |
|---|---|---|---|
| `broadcast_message` | Send a chat message to every player. | changes | `say` |
| `send_message` | Send a private message to one player. | changes | `tell` |
| `send_rich_message` | Send formatted, clickable text with `/tellraw`. | changes | `tellraw` |
| `show_title` | Show a title and subtitle on a player's screen. | changes | `title` |
| `play_sound` | Play a sound to a player. | changes | `playsound` |
| `stop_sound` | Stop one sound, or all sounds, for a player. | changes | `stopsound` |
| `spawn_particles` | Show particles at a position. | changes | `particle` |

## scoreboard

| Tool | What it does | Access | MCPyLib call |
|---|---|---|---|
| `create_objective` | Create a scoreboard objective. | changes | `addObjective` |
| `remove_objective` | Delete an objective and all of its scores. | destructive | `removeObjective` |
| `set_objective_display` | Show an objective in the sidebar, below names or in the list, or clear a slot. | changes | `setDisplaySlot` |
| `set_score` | Set a score, replacing the previous value. | destructive | `setScore` |
| `get_score` | Read a score. | read-only | `getScore` |
| `list_teams` | All teams with display names and members. | read-only | `team` |
| `create_team` | Create a team. | changes | `team` |
| `remove_team` | Delete a team. | destructive | `team` |
| `update_team_members` | Add and remove team members. | changes | `team` |
| `set_team_option` | Change a team option such as colour or friendly fire. | changes | `team` |
| `list_bossbars` | Boss bars created through MCPyLib, with their settings and viewers. | read-only | `bossbar` |
| `create_bossbar` | Create a boss bar and show it to players. | changes | `bossbar` |
| `update_bossbar` | Change a boss bar's title, colour, style, progress or viewers. | changes | `bossbar` |
| `remove_bossbar` | Delete a boss bar. | destructive | `bossbar` |

## Notes

- `get_blocks` and `get_height_map` read with `getblocks`, then convert the result:
  text layers (`layout="layers"`), palette indices in `[x][y][z]` order
  (`layout="xyz"`, the `edit_blocks` format) or block counts (`layout="summary"`).
- `build_from_layers` decodes the layers format and sends one `edit` call.
- `run_command`, `send_rich_message`, `spread_players`, `fill_biome` and the `place_*`
  tools dispatch console commands. They report that the command was dispatched, not
  that it succeeded, so verify the result with a read tool.
