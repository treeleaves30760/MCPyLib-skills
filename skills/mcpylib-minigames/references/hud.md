# HUD: text, scoreboards, teams, boss bars, sounds and particles

## Contents

- [Colour and format codes](#colour-and-format-codes)
- [Titles](#titles)
- [Chat](#chat)
- [Scoreboard objectives and the sidebar](#scoreboard-objectives-and-the-sidebar)
- [Teams](#teams)
- [Boss bars](#boss-bars)
- [Action bar and JSON chat](#action-bar-and-json-chat)
- [Sounds](#sounds)
- [Particles](#particles)

## Colour and format codes

Titles, chat, boss bar titles, team prefixes and objective display names take legacy
text with `§` codes. JSON text components (click and hover events) need the console
route in [Action bar and JSON chat](#action-bar-and-json-chat).

| Code | Colour | Code | Colour |
|---|---|---|---|
| `§0` | black | `§8` | dark gray |
| `§1` | dark blue | `§9` | blue |
| `§2` | dark green | `§a` | green |
| `§3` | dark aqua | `§b` | aqua |
| `§4` | dark red | `§c` | red |
| `§5` | dark purple | `§d` | light purple |
| `§6` | gold | `§e` | yellow |
| `§7` | gray | `§f` | white |

Formats: `§l` bold, `§o` italic, `§n` underline, `§m` strikethrough, `§k` obfuscated,
`§r` reset. Put the colour before the format: `"§6§lWINNER"`. Write the `§`
character directly in UTF-8 source, or as `"§"`.

## Titles

```python
mc.title("Steve", "§6Round 2", "§7Fight!", fade_in=5, stay=40, fade_out=10)
mc.title("Steve", "", "§eSubtitle only")   # empty title, subtitle still shows
```

- One player per call; selectors such as `@a` don't work. Loop over names, or use
  `game_kit.title_all`.
- Times are in ticks (20 = 1 s). A new title replaces the one on screen.
- There is no action-bar call. For constant information, use the sidebar or a boss
  bar.

## Chat

- `mc.say(message)` broadcasts to everyone with a `[Server]` prefix.
- `mc.tell(username, message)` sends the plain text to one player, with no prefix.
- Both accept `§` codes. Keep announcements short; the 1.2.0 plugin has no clickable
  or hover text.

## Scoreboard objectives and the sidebar

```python
mc.addObjective("race", "dummy", "§b§lRACE")
mc.setDisplaySlot("sidebar", "race")
mc.setScore("race", "Steve", 3)          # a player line
mc.setScore("race", "§7Laps to go", 5)   # a label line (holders can be any text)
print(mc.getScore("race", "Steve"))      # 0 when no score was set
mc.removeObjective("race")               # also clears the sidebar slot
```

- **Criteria**:
  - `dummy` and `trigger` change only when scripts set them.
  - `deathCount`, `playerKillCount`, `totalKillCount` count automatically.
  - `health`, `food`, `level`, `xp`, `air` and `armor` mirror player stats.
- **Slots**: `sidebar`, `player_list` (the tab list), `below_name`, and per-team
  sidebars that only that team's members see: `sidebar_team_red` on Paper,
  `sidebar_red` on Spigot (the server's own enum names). `mc.setDisplaySlot("sidebar")`
  with no objective clears the slot.
- Each slot shows one objective at a time. Setting yours replaces whatever was
  there, and MCPyLib can't read the previous one to restore it. Warn the user on
  servers that already use the sidebar.
- The sidebar shows up to 15 lines, sorted by score from high to low. Use scores to
  order label lines (a "header" label with a high score stays on top).
- Everything uses the server's **main scoreboard**, so every player sees the same
  display slots. Objectives persist across restarts until removed.
- `addObjective` fails with `Objective already exists: <name>`. Pick game-specific
  names and remove them at the end.

## Teams

```python
mc.team("add", "red", display_name="Red team")
mc.team("modify", "red", option="color", value="RED")          # name tags and glow colour
mc.team("modify", "red", option="friendlyfire", value="false")
mc.team("modify", "red", option="prefix", value="§c[R] ")
mc.team("join", "red", members=["Steve", "Alex"])               # names, or entity UUID strings
mc.team("leave", "red", members=["Alex"])
print(mc.team("list"))   # {"teams": [{"name", "display_name", "members", "size"}]}
mc.team("remove", "red")
```

- Colours are chat colour names: `BLACK`, `DARK_BLUE`, `DARK_GREEN`, `DARK_AQUA`,
  `DARK_RED`, `DARK_PURPLE`, `GOLD`, `GRAY`, `DARK_GRAY`, `BLUE`, `GREEN`, `AQUA`,
  `RED`, `LIGHT_PURPLE`, `YELLOW`, `WHITE`.
- `modify` options are `displayname`, `color`, `friendlyfire`,
  `seefriendlyinvisibles`, `prefix` and `suffix`. Values are strings.
- Joining a team removes the entry from its previous team. Removing the team frees
  all members. Record teams with `tracker.team(name)` so cleanup removes them.

## Boss bars

```python
mc.bossbar("add", "race_timer", title="§eTime left: 120 s", color="YELLOW",
           style="SEGMENTED_10", progress=1.0)
mc.bossbar("addplayer", "race_timer", username="Steve")   # one player per call
mc.bossbar("set", "race_timer", title="§eTime left: 60 s", progress=0.5)
mc.bossbar("removeplayer", "race_timer", username="Steve")
mc.bossbar("remove", "race_timer")                        # always, in finally:
```

- Colours: `WHITE`, `PINK`, `BLUE`, `RED`, `GREEN`, `YELLOW`, `PURPLE`. Styles:
  `SOLID`, `SEGMENTED_6`, `SEGMENTED_10`, `SEGMENTED_12`, `SEGMENTED_20`.
- `add` silently falls back to `WHITE`/`SOLID` for unknown values; `set` raises.
- A new bar is shown to nobody until `addplayer`. A player who leaves and rejoins
  is a new player object and must be added again (`Bar.forget(left)` +
  `Bar.show(joined)` handle that).
- Bars exist only in plugin memory: vanilla `/bossbar` can't see them, a server
  restart deletes them (`/mcpylib reload` doesn't), and a crashed script leaves its
  bar on screen until someone removes it or the server restarts.
- `mc.bossbar("list", "any")` lists ids; the second argument is required but
  ignored.

## Action bar and JSON chat

MCPyLib has no action-bar or JSON-chat method, but on plugin **1.2.0+** you can run
the vanilla commands through `exec` and `tellraw`. On older plugins these calls
freeze the server.

```python
import json
import re

NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")   # Java player names; refuse anything else

def actionbar(mc, name, text):
    """Small text above the hotbar; it fades after about 3 s, so resend it to keep it up."""
    if NAME_RE.match(name):
        mc.exec(f"title {name} actionbar {json.dumps(text, ensure_ascii=False)}")

def chat_link(mc, name, label, url):
    if NAME_RE.match(name):
        mc.tellraw(name, json.dumps({"text": label, "color": "aqua", "underlined": True,
                                     "click_event": {"action": "open_url", "url": url}}))
```

- Both return `True` once the command is dispatched, even if it failed; mistakes
  only show in the server console. Test each new command in game.
- Minecraft 26.x uses the 1.21.5+ text component format: `click_event` and
  `hover_event`, with fields such as `url` or `command` instead of the old `value`.
- Check names against `NAME_RE` and never put chat input or other untrusted text into
  a command: the console can run anything.

## Sounds

```python
mc.playsound("Steve", "entity.experience_orb.pickup")
mc.playsound("Steve", "block.note_block.pling", pitch=2.0)
mc.playsound("Steve", "entity.generic.explode", x=100, y=64, z=-20, volume=2.0)
mc.stopsound("Steve")   # stop everything playing for Steve
```

| Use | Sound key |
|---|---|
| Point scored, pickup | `entity.experience_orb.pickup` |
| Level or round complete | `entity.player.levelup` |
| Victory | `ui.toast.challenge_complete` |
| Countdown tick / go | `block.note_block.hat` / `block.note_block.pling` (pitch 2.0) |
| Error, contested | `block.note_block.bass`, `entity.villager.no` |
| Wave start | `event.raid.horn` |
| Bell, round start | `block.bell.use` |
| Hit confirmation | `entity.arrow.hit_player` |
| Teleport | `entity.enderman.teleport` |
| Fireworks | `entity.firework_rocket.launch`, `entity.firework_rocket.blast` |
| Defeat | `entity.wither.death` (use volume 0.6) |

- Keys are vanilla sound event ids; `minecraft:` is optional. **Unknown keys play
  nothing and raise no error**, so test new keys in game.
- `source` (default `master`) is the volume slider category: `master`, `music`,
  `record`, `weather`, `block`, `hostile`, `neutral`, `player`, `ambient`, `voice`.
- `pitch` 0.5-2.0 (note-block pitches: 0.5 x 2^(n/12)). `volume` above 1.0 only
  widens the hearing range (16 blocks x volume); it doesn't get louder.
- Without x, y, z the sound plays at the player. With all three it plays at that
  point, so it fades with distance.

## Particles

```python
mc.particle("end_rod", 100.5, 65.2, -19.5, count=3, dy=0.2)              # small sparkle
mc.particle("happy_villager", 100.5, 66, -19.5, count=20, dx=0.5, dy=0.5, dz=0.5)
mc.particle("totem_of_undying", 100.5, 66, -19.5, count=80, dx=1, dy=1, dz=1, speed=0.4)
```

- Particles always appear in the main overworld, visible to players nearby (about
  32 blocks).
- `count` is the number of particles. `dx`, `dy`, `dz` are the random spread around
  the point (Gaussian, roughly that many blocks). `speed` is the extra speed.
- Ids that work: `flame`, `soul_fire_flame`, `heart`, `happy_villager`,
  `angry_villager`, `end_rod`, `totem_of_undying`, `firework`, `cloud`, `crit`,
  `enchanted_hit`, `smoke`, `large_smoke`, `explosion`, `portal`, `note`,
  `snowflake`, `witch`, `enchant`, `poof`, `glow`, `electric_spark`.
- Types that need extra data fail with `Failed to spawn particle: ...`: `dust`,
  `dust_color_transition`, `block`, `block_marker`, `falling_dust`, `item`,
  `entity_effect`, `vibration`, `sculk_charge`, `shriek`. MCPyLib can't send the
  data, so pick a data-free type.
- Old Bukkit names such as `VILLAGER_HAPPY`, `REDSTONE` or `TOTEM` fail; use the
  modern ids above.
- **Shapes cost one call per point.** A ring of 12 points is 12 calls (0.6 s). Spread
  a shape over several steps (one point per step gives a spinning effect), or use one
  call with a spread for clouds and bursts.
