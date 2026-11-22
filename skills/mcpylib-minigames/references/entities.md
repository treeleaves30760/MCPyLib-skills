# Entities: summoning, control and cleanup

## Contents

- [Summon and track](#summon-and-track)
- [Read state](#read-state)
- [Move, aim and freeze](#move-aim-and-freeze)
- [Targets and combat](#targets-and-combat)
- [Equipment](#equipment)
- [Attributes](#attributes)
- [Villager shops and NPCs](#villager-shops-and-npcs)
- [Riding](#riding)
- [Despawning, peaceful and unloaded chunks](#despawning-peaceful-and-unloaded-chunks)
- [Extras through console commands (plugin 1.2.0+)](#extras-through-console-commands-plugin-120)
- [Cleanup](#cleanup)

## Summon and track

```python
uid = mc.summon("zombie", x + 0.5, y, z + 0.5)   # returns the UUID string
tracker.entity(uid, x, z)                        # record it before anything else
mc.addTag(uid, "arena")                          # so an operator can /kill @e[tag=arena]
```

- Entities always spawn in the **main overworld**, at the exact coordinates. Add
  `0.5` to x and z to centre on a block, and use the feet level (`y` of the block
  above the floor).
- Ids are entity type ids: `zombie`, `husk`, `skeleton`, `stray`, `spider`,
  `armor_stand`, `villager`, `iron_golem`, `minecraft:pig`. Players and
  non-spawnable types fail with `Cannot summon entity type: <type>`; unknown ids fail
  with `Invalid entity type: <type>`.
- Avoid `creeper` in arenas (it blows holes in the floor) unless the user wants that.
- There is no find-by-tag call. Keep every UUID you summon; tags are only for humans
  and console commands.

## Read state

| Call | Returns |
|---|---|
| `mc.getEntityStatus(uid)` | `uuid`, `type`, `is_valid`, `is_dead`, `world`, `position {x,y,z}`, `velocity {x,y,z}`; for living entities also `health`, `max_health`, `has_ai`; `custom_name` only when set |
| `mc.getEntityPos(uid)` | `x`, `y`, `z`, `yaw`, `pitch` |
| `mc.getEntityEquipment(uid)` | Filled slots only, such as `{"helmet": "minecraft:leather_helmet"}` |
| `mc.getTags(uid)` | Scoreboard tags |

A dead or removed entity raises `CommandError` (`Entity not found: <uuid>`). Treat
that as "gone".

## Move, aim and freeze

```python
mc.teleportEntity(uid, 100.5, 65, -19.5)               # keeps its rotation
mc.teleportEntity(uid, 100.5, 65, -19.5, yaw=180, pitch=0)
mc.setEntityRotation(uid, 90, 0)                       # yaw 0 south, 90 west, 180 north, 270 east
mc.setEntityVelocity(uid, 0, 1.2, 0)                   # blocks per tick; each component clamped to +/-10
mc.setEntityAI(uid, False)                             # statue / NPC: no movement, no attacks
```

- `teleportEntity` dismounts an entity that rides something, then moves it. It
  returns `False`, without raising, when the server refuses, for example for an
  entity that carries passengers. `setEntityRotation` turns non-players in place,
  including mounted entities and ones carrying passengers. Players are turned by a
  teleport and stay mounted; if that teleport is cancelled it raises `CommandError`.
- To face a point: `yaw = math.degrees(math.atan2(-(tx - x), tz - z))`.
- `setEntityVelocity` also works on players (launch pads, knockback). Look the
  player's UUID up in `mc.list()`.
- `setEntityAI` needs a living entity (`Entity is not a LivingEntity` otherwise).

## Targets and combat

```python
mc.setEntityTarget(mob, player_uuid)    # attack this player (or any living entity)
mc.setEntityTarget(mob)                 # clear the target
mc.damage(mob, 4.0, source_uuid=player_uuid)   # 2 hearts, credited to the player
```

- Targets work on mobs only (`Entity is not a Mob ...`). The target must be a living
  entity and must be loaded.
- Mobs lose interest after a while or when they lose sight of the target. Re-target
  every 10 s or so, spreading the calls over several loop steps.
- Players in creative or spectator mode are ignored by mobs.

## Equipment

```python
mc.setEntityEquipment(uid, {"helmet": "leather_helmet", "main_hand": "iron_sword"},
                      drop_chances={"helmet": 0.0, "main_hand": 0.0})
```

- Slots: `helmet`, `chestplate`, `leggings`, `boots`, `main_hand`, `off_hand`.
  Unknown slot names are silently ignored. Items are plain (no enchantments).
- **Any helmet stops zombies, skeletons and strays from burning in daylight.** Set
  its drop chance to 0 so players can't farm it.
- Equipment works on any living entity, including armor stands (for displays) and
  players, but `drop_chances` works on mobs only: leave it out for armor stands and
  players, or the call raises after the gear is already on.

## Attributes

```python
mc.attribute(uid, "scale", "set", 2.5)            # a giant (scale exists since 1.20.5)
mc.attribute(uid, "movement_speed", "set", 0.35)  # zombie default is about 0.23
mc.attribute(uid, "attack_damage", "set", 6)
print(mc.attribute(uid, "max_health"))            # {"base_value": 20.0, "value": 20.0}
```

- `action` is `"get"` (default) or `"set"`, which changes the base value. Names are
  registry ids (`max_health`, `movement_speed`, `attack_damage`, `armor`,
  `knockback_resistance`, `follow_range`, `scale`, `gravity`, `jump_strength`);
  legacy forms such as `GENERIC_MAX_HEALTH` also work.
- Raising `max_health` does **not** heal: a fresh zombie set to 100 still has 20
  health. MCPyLib has no heal call for mobs; see the console-command extras below.

## Villager shops and NPCs

```python
shop = mc.summon("villager", x + 0.5, y, z + 0.5)
tracker.entity(shop, x, z)
mc.setEntityAI(shop, False)                       # stays put, but still trades
mc.setVillagerProfession(shop, "librarian")       # set the job first
mc.setVillagerTrades(shop, [
    {"buy1": {"item": "emerald", "amount": 3}, "sell": {"item": "diamond", "amount": 1}, "max_uses": 999},
    {"buy1": {"item": "emerald", "amount": 1}, "buy2": {"item": "book", "amount": 1},
     "sell": {"item": "experience_bottle", "amount": 8}},
])
```

- `setVillagerTrades` replaces every trade. `max_uses` defaults to 10 and
  `experience_reward` (XP orbs for the player) to `True`. Items are plain.
- On a villager with 0 XP the plugin also sets 1 XP, so vanilla AI doesn't take the
  new profession away again.
- `getVillagerData(uid)` returns `profession`, `level` and the current trades.

## Riding

```python
horse = mc.summon("horse", x + 0.5, y, z + 0.5)
mc.ride(player_uuid, horse)    # passenger, vehicle
mc.ride(player_uuid)           # dismount
```

Any entity can carry another, so stacks of mobs or a player on a minecart work too.
`teleportEntity` on a passenger dismounts it; on a vehicle that carries passengers
it returns `False`, so dismount the riders first.

## Despawning, peaceful and unloaded chunks

- **Peaceful difficulty removes hostile mobs at once.** If every mob of a wave is gone
  straight after spawning, ask the user to change the difficulty
  (`mc.difficulty("normal")`). That is server-wide, and MCPyLib can't read the old
  value to restore it.
- Summoned mobs are not persistent: they despawn when no player is near (about 128
  blocks), and sometimes beyond 32 blocks. Keep games where the players are.
- Entities in unloaded chunks can't be found, so calls on them raise
  `Entity not found`. `game_kit.py --cleanup` force-loads the recorded chunks
  (`mc.forceload("add", x, z)`), retries, and removes the force-load again.

## Extras through console commands (plugin 1.2.0+)

`exec` runs vanilla commands, which can do what the dedicated methods can't. A UUID
works wherever a command takes an entity. These only work on plugin 1.2.0 (older
plugins freeze), return `True` even when the command fails, and use the 26.x NBT and
text formats, so test each one in game first.

```python
mc.exec(f"data merge entity {uid} {{Health:100f}}")              # heal up to max_health
mc.exec(f"data merge entity {uid} {{PersistenceRequired:1b}}")   # never despawn
mc.exec(f'data merge entity {uid} {{CustomName:"Arena Boss",CustomNameVisible:1b}}')
mc.exec(f"effect give {uid} minecraft:glowing 30 0 true")        # outline in team colour
```

## Cleanup

- Remove what you created with `mc.removeEntity(uid)` (no drops; refuses players).
  `game_kit.Tracker` does this for every recorded UUID.
- Never use `mc.kill("all")` or `mc.kill("<type>")` on a shared world: they remove
  pets, villagers, item frames, armor stands and dropped items everywhere in the
  overworld.
- Forget mobs that died (`tracker.forget_entity(uid)`) so the state file stays small.
- As a last resort, an operator can type `/kill @e[tag=<game_id>]` in game, or a
  script on plugin 1.2.0+ can run `mc.exec("kill @e[tag=<game_id>]")`. Both only reach
  loaded entities.
