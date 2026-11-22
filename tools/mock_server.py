#!/usr/bin/env python3
"""Offline stand-in for the MCPyLib 1.2.1 server plugin, used by smoke_test.py.

It speaks the plugin's protocol: one JSON request per line,
{"token", "action", "params"}, answered by {"success": true, "data": ...} or
{"success": false, "error": "..."}, over a persistent TCP connection. Requests run
one at a time under a lock, as they do on the server's main thread.

The world is flat: bedrock at y=-64, stone up to y=63, grass_block at y=64, air
above, void_air outside -64..319. The mock is strict where scripts tend to go
wrong:
  - block ids: modern lower-case ids only (items and renamed ids are rejected)
  - block_state: a fixed list of common vanilla properties (the plugin accepts
    every property the block has; the mock doesn't know which block has which)
    and does not add the missing half of doors and beds
  - compressed bulkEdit: palette indices and RLE length are checked
  - particles that need extra data fail, as they do on the server
  - entities can be marked unloaded (not found until their chunk is force-loaded)

Usage:  python tools/mock_server.py --port 25599 --token test-token --player Steve 0 65 0
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import re
import socketserver
import threading
import time
import uuid as uuidlib
import zlib

Y_MIN, Y_MAX = -64, 319
NAMESPACE = uuidlib.UUID("6f1c3c1e-6b8a-4c4e-9d55-3a1f0f3b2c10")
ID_RE = re.compile(r"^[a-z0-9_]+$")
# Item ids, generic names and renamed ids that are not valid block ids on 26.x.
NOT_BLOCKS = {
    "grass", "grass_path", "brick", "planks", "log", "wood", "wool", "concrete", "sign",
    "wall_sign", "leaves", "stone_brick", "diamond", "iron_ingot", "gold_ingot", "stick",
    "coal", "redstone", "string", "bed", "door", "slab", "stairs", "fence", "carpet",
}
STATE_VALUES = {
    "facing": {"north", "south", "east", "west", "up", "down"},
    "rotation": {"north", "north_north_east", "north_east", "east_north_east", "east",
                 "east_south_east", "south_east", "south_south_east", "south",
                 "south_south_west", "south_west", "west_south_west", "west",
                 "west_north_west", "north_west", "north_north_west"} | {str(i) for i in range(16)},
    "axis": {"x", "y", "z"},
    "half": {"top", "bottom", "upper", "lower"},
    "type": {"bottom", "top", "double", "single", "left", "right"},
    "part": {"head", "foot"},
    "hinge": {"left", "right"},
    "lit": {"true", "false"},
    "persistent": {"true", "false"},
    "hanging": {"true", "false"},
    "layers": {str(i) for i in range(1, 9)},
    "age": {str(i) for i in range(26)},
    "shape": {"straight", "inner_left", "inner_right", "outer_left", "outer_right"},
    "waterlogged": {"true", "false"},
    "open": {"true", "false"},
    "powered": {"true", "false"},
}
PARTICLES = {
    "flame", "soul_fire_flame", "heart", "happy_villager", "angry_villager", "end_rod",
    "totem_of_undying", "firework", "cloud", "crit", "enchanted_hit", "smoke", "large_smoke",
    "explosion", "explosion_emitter", "portal", "note", "snowflake", "witch", "enchant",
    "poof", "glow", "electric_spark", "composter", "dragon_breath", "bubble", "splash",
    "lava", "campfire_cosy_smoke", "campfire_signal_smoke", "sonic_boom", "wax_on", "wax_off",
    "damage_indicator", "sweep_attack", "dripping_water", "falling_water", "ash",
    "cherry_leaves", "gust", "trial_spawner_detection", "instant_effect", "effect",
    "mycelium", "dolphin", "rain", "fishing", "underwater", "reverse_portal",
}
DATA_PARTICLES = {"dust", "block", "item", "falling_dust", "entity_effect", "vibration",
                  "dust_color_transition", "sculk_charge", "shriek", "block_marker",
                  "dust_pillar", "trail", "block_crumble"}
HOSTILE = {"zombie", "skeleton", "spider", "cave_spider", "creeper", "husk", "stray",
           "drowned", "witch", "slime", "pillager", "vindicator", "zombie_villager",
           "bogged", "enderman", "blaze", "phantom"}
LIVING = HOSTILE | {"armor_stand", "villager", "pig", "cow", "sheep", "chicken", "wolf",
                    "cat", "iron_golem", "horse", "fox", "bat", "snow_golem", "allay"}
OTHER_ENTITIES = {"item_display", "block_display", "text_display", "marker", "boat",
                  "minecart", "tnt", "falling_block", "arrow", "lightning_bolt"}
OLD_ENTITY_NAMES = {"zombie_pigman", "pigman", "snowman", "evocation_illager", "villager_golem"}
CRITERIA = {"dummy", "trigger", "deathCount", "playerKillCount", "totalKillCount", "health",
            "level", "food", "air", "armor", "xp"}
SLOTS = {"sidebar", "player_list", "below_name"}
BAR_COLORS = {"WHITE", "PINK", "BLUE", "RED", "GREEN", "YELLOW", "PURPLE"}
BAR_STYLES = {"SOLID", "SEGMENTED_6", "SEGMENTED_10", "SEGMENTED_12", "SEGMENTED_20"}
GAMEMODES = {"survival", "creative", "adventure", "spectator"}
EQUIPMENT_SLOTS = {"helmet", "chestplate", "leggings", "boots", "main_hand", "off_hand"}


class MockError(Exception):
    pass


class World:
    """All mock state. Every request runs under self.lock."""

    def __init__(self, mob_lifetime: float | None = None, tick_delay: float = 0.0) -> None:
        self.lock = threading.RLock()
        self.blocks: dict = {}
        self.states: dict = {}
        self.players: dict = {}
        self.entities: dict = {}
        self.objectives: dict = {}
        self.display: dict = {}
        self.bossbars: dict = {}
        self.teams: dict = {}
        self.forced: set = set()
        self.difficulty = "normal"
        self.mob_lifetime = mob_lifetime
        self.tick_delay = tick_delay
        self.log: list = []

    # ------------------------------------------------------------ helpers

    def add_player(self, name, x, y, z, world="world", yaw=0.0, gamemode="SURVIVAL"):
        uid = str(uuidlib.uuid5(NAMESPACE, name))
        self.players[name] = {"name": name, "uuid": uid, "x": float(x), "y": float(y),
                              "z": float(z), "yaw": float(yaw), "pitch": 0.0, "world": world,
                              "gamemode": gamemode, "health": 20.0, "dead": False,
                              "effects": {}, "titles": [], "sounds": [], "messages": []}
        return uid

    def base_block(self, x, y, z):
        if y < Y_MIN or y > Y_MAX:
            return "minecraft:void_air"
        if y == Y_MIN:
            return "minecraft:bedrock"
        if y < 64:
            return "minecraft:stone"
        if y == 64:
            return "minecraft:grass_block"
        return "minecraft:air"

    def get(self, x, y, z):
        return self.blocks.get((x, y, z)) or self.base_block(x, y, z)

    def put(self, x, y, z, block, state=None):
        if Y_MIN <= y <= Y_MAX:
            self.blocks[(x, y, z)] = block
            if state:
                self.states[(x, y, z)] = dict(state)
            else:
                self.states.pop((x, y, z), None)
            return True
        return False

    @staticmethod
    def material(name) -> str | None:
        if not isinstance(name, str):
            return None
        n = name.lower()
        n = n[len("minecraft:"):] if n.startswith("minecraft:") else n
        if not ID_RE.match(n) or n in NOT_BLOCKS:
            return None
        return "minecraft:" + n

    @staticmethod
    def check_state(state) -> dict:
        if not isinstance(state, dict):
            raise MockError("block_state must be an object")
        out = {}
        for key, value in state.items():
            k = key.lower()
            v = str(value).lower()
            if k not in STATE_VALUES:
                raise MockError(f"Unsupported property '{key}={value}'")
            if v not in STATE_VALUES[k]:
                raise MockError(f"No enum constant for {k}: {value}")
            out[k] = v
        return out

    def player(self, name, exact=True):
        for pname, p in self.players.items():
            if pname.lower() == str(name).lower():
                return p
        if not exact:
            matches = [p for pname, p in self.players.items() if pname.lower().startswith(str(name).lower())]
            if len(matches) == 1:
                return matches[0]
        return None

    def need_player(self, name, exact=True):
        p = self.player(name, exact)
        if p is None:
            raise MockError(f"Player not found: {name}")
        return p

    def entity(self, uid):
        try:
            uuidlib.UUID(str(uid))
        except ValueError:
            raise MockError(f"Invalid UUID format: {uid}")
        self.expire_mobs()
        for p in self.players.values():
            if p["uuid"] == uid:
                return p
        e = self.entities.get(uid)
        if e is None or (e["unloaded"] and (math.floor(e["x"]) >> 4, math.floor(e["z"]) >> 4) not in self.forced):
            raise MockError(f"Entity not found: {uid}")
        return e

    def expire_mobs(self):
        now = time.monotonic()
        for uid, e in list(self.entities.items()):
            if e.get("dies_at") is not None and now >= e["dies_at"]:
                del self.entities[uid]  # killed by a player: gone, as on the server

    # ------------------------------------------------------------ dispatch

    def handle(self, request: dict) -> dict:
        action = request.get("action", "")
        params = request.get("params") or {}
        with self.lock:
            self.log.append((action, params))
            if self.tick_delay:
                time.sleep(self.tick_delay)
            fn = getattr(self, "do_" + action, None)
            if fn is None:
                return {"success": False, "error": f"Unknown action: {action}"}
            try:
                data = fn(**params)
            except MockError as exc:
                return {"success": False, "error": str(exc)}
            except TypeError as exc:
                return {"success": False, "error": f"Bad parameters for {action}: {exc}"}
            return {"success": True, "data": strip_none(data)}

    # ------------------------------------------------------------ blocks

    def do_getblock(self, x, y, z):
        return self.get(int(x), int(y), int(z))

    def do_getblocks(self, x1, y1, z1, x2, y2, z2):
        xa, xb = sorted((int(x1), int(x2)))
        ya, yb = sorted((int(y1), int(y2)))
        za, zb = sorted((int(z1), int(z2)))
        if (xb - xa + 1) * (yb - ya + 1) * (zb - za + 1) > 200_000:
            raise MockError("mock: getblocks request too large; split it")
        return [[[self.get(x, y, z) for z in range(za, zb + 1)] for y in range(ya, yb + 1)]
                for x in range(xa, xb + 1)]

    def do_setblock(self, x, y, z, block, block_state=None, nbt=None):
        mat = self.material(block)
        if mat is None:
            raise MockError(f"Invalid block type: {block}")
        state = None
        if block_state is not None:
            try:
                state = self.check_state(block_state)
            except MockError as exc:
                self.put(int(x), int(y), int(z), mat)
                raise MockError(f"Failed to set block state: {exc}")
        self.put(int(x), int(y), int(z), mat, state)
        return 1

    def do_fill(self, x1, y1, z1, x2, y2, z2, block):
        mat = self.material(block)
        if mat is None:
            raise MockError(f"Invalid block type: {block}")
        xa, xb = sorted((int(x1), int(x2)))
        ya, yb = sorted((int(y1), int(y2)))
        za, zb = sorted((int(z1), int(z2)))
        count = 0
        for x in range(xa, xb + 1):
            for y in range(ya, yb + 1):
                for z in range(za, zb + 1):
                    self.put(x, y, z, mat)
                    count += 1
        return count

    def do_bulkEdit(self, x, y, z, **body):
        x, y, z = int(x), int(y), int(z)
        if "encoding" in body:
            return self._bulk_compressed(x, y, z, **body)
        if "blocks" not in body:
            raise MockError("Missing parameters: blocks")
        return self._bulk_legacy(x, y, z, body["blocks"])

    def _cell(self, value, where):
        if value is None:
            return None
        if isinstance(value, str):
            mat = self.material(value)
            if mat is None:
                raise MockError(f"Invalid block type in {where}: {value}")
            return mat, None
        if isinstance(value, dict):
            if "block" not in value:
                raise MockError(f"Missing 'block' field in {where}")
            mat = self.material(value["block"])
            if mat is None:
                raise MockError(f"Invalid block type in {where}: {value['block']}")
            state = self.check_state(value["block_state"]) if "block_state" in value else None
            return mat, state
        raise MockError(f"Bad cell in {where}: {value!r}")

    def _bulk_compressed(self, x, y, z, encoding, sizeX, sizeY, sizeZ, palette, data):
        if encoding != "palette_rle_zlib":
            raise MockError(f"Unsupported encoding: {encoding}")
        cells = [self._cell(v, f"palette[{i}]") for i, v in enumerate(palette)]
        rle = [int(v) for v in zlib.decompress(base64.b64decode(data)).decode("utf-8").split(",") if v]
        if len(rle) % 2:
            raise MockError("Failed to bulk edit (compressed): odd RLE length")
        total = sizeX * sizeY * sizeZ
        run_total = sum(rle[0::2])
        if run_total != total:
            raise MockError(f"mock: RLE covers {run_total} cells, expected {total}")
        flat = []
        for count, index in zip(rle[0::2], rle[1::2]):
            if not 0 <= index < len(cells):
                raise MockError(f"mock: palette index {index} out of range")
            flat.extend([index] * count)
        written = 0
        for fi, pi in enumerate(flat):
            cell = cells[pi]
            if cell is None:
                continue
            dz = fi % sizeZ
            dy = (fi // sizeZ) % sizeY
            dx = fi // (sizeY * sizeZ)
            if self.put(x + dx, y + dy, z + dz, cell[0], cell[1]):
                written += 1
        return written

    def _bulk_legacy(self, x, y, z, blocks):
        written = 0
        for dx, plane in enumerate(blocks):
            for dy, row in enumerate(plane):
                for dz, value in enumerate(row):
                    cell = self._cell(value, f"blocks[{dx}][{dy}][{dz}]")
                    if cell is not None and self.put(x + dx, y + dy, z + dz, cell[0], cell[1]):
                        written += 1
        return written

    # ------------------------------------------------------------ players

    def do_list(self):
        return {"online_count": len(self.players), "max_players": 20,
                "players": [{"name": p["name"], "uuid": p["uuid"], "gamemode": p["gamemode"]}
                            for p in self.players.values()]}

    def do_getPos(self, username):
        p = self.need_player(username)
        return [math.floor(p["x"]), math.floor(p["y"]), math.floor(p["z"])]

    def do_teleport(self, username, x, y, z, yaw=None, pitch=None):
        p = self.need_player(username)
        p.update(x=float(x), y=float(y), z=float(z))
        if yaw is not None and pitch is not None:
            p.update(yaw=float(yaw), pitch=float(pitch))
        return True

    def do_gamemode(self, username, mode):
        p = self.need_player(username)
        if str(mode).lower() not in GAMEMODES:
            raise MockError(f"Invalid gamemode: {mode}")
        p["gamemode"] = str(mode).upper()
        return True

    def do_effect(self, username, effect, duration=30, amplifier=0, hide_particles=False):
        p = self.need_player(username, exact=False)
        if not ID_RE.match(str(effect).lower().removeprefix("minecraft:")):
            raise MockError(f"Invalid effect type: {effect}")
        p["effects"][str(effect).lower().removeprefix("minecraft:")] = (int(duration), int(amplifier))
        return True

    def do_clearEffect(self, username, effect=None):
        p = self.need_player(username, exact=False)
        if effect is None:
            p["effects"].clear()
        else:
            p["effects"].pop(str(effect).lower().removeprefix("minecraft:"), None)
        return True

    # ------------------------------------------------------------ entities

    def do_summon(self, entity_type, x, y, z):
        t = str(entity_type).lower().removeprefix("minecraft:")
        if t == "player":
            raise MockError(f"Cannot summon entity type: {t}")
        if t in OLD_ENTITY_NAMES or not (t in LIVING or t in OTHER_ENTITIES):
            raise MockError(f"Invalid entity type: {t}")
        uid = str(uuidlib.uuid4())
        e = {"uuid": uid, "type": t, "x": float(x), "y": float(y), "z": float(z), "yaw": 0.0,
             "pitch": 0.0, "world": "world", "tags": [], "equipment": {}, "drop_chances": {},
             "ai": True, "target": None, "living": t in LIVING, "unloaded": False,
             "dies_at": None, "health": 20.0}
        if t in HOSTILE and self.difficulty == "peaceful":
            return uid  # despawns at once on peaceful
        if t in HOSTILE and self.mob_lifetime is not None:
            e["dies_at"] = time.monotonic() + self.mob_lifetime
        self.entities[uid] = e
        return uid

    def _status(self, e):
        is_player = "gamemode" in e
        return {"uuid": e["uuid"], "type": "minecraft:" + ("player" if is_player else e["type"]),
                "is_valid": True, "is_dead": bool(e.get("dead")), "world": e["world"],
                "position": {"x": e["x"], "y": e["y"], "z": e["z"]},
                "velocity": {"x": 0.0, "y": 0.0, "z": 0.0},
                "health": e["health"] if is_player or e.get("living") else None,
                "max_health": 20.0 if is_player or e.get("living") else None,
                "has_ai": e.get("ai", True) if is_player or e.get("living") else None}

    def do_getEntityStatus(self, uuid):
        return self._status(self.entity(uuid))

    def do_getEntityPos(self, uuid):
        e = self.entity(uuid)
        return {"x": e["x"], "y": e["y"], "z": e["z"], "yaw": e["yaw"], "pitch": e["pitch"]}

    def do_removeEntity(self, uuid):
        e = self.entity(uuid)
        if "gamemode" in e:
            raise MockError("Cannot remove players using removeEntity")
        del self.entities[uuid]
        return True

    def do_teleportEntity(self, uuid, x, y, z, yaw=None, pitch=None):
        e = self.entity(uuid)
        e.update(x=float(x), y=float(y), z=float(z))
        if yaw is not None and pitch is not None:
            e.update(yaw=float(yaw), pitch=float(pitch))
        return True

    def do_addTag(self, uuid, tag):
        e = self.entity(uuid)
        tags = e.setdefault("tags", [])
        if tag in tags:
            return False
        tags.append(tag)
        return True

    def do_removeTag(self, uuid, tag):
        tags = self.entity(uuid).setdefault("tags", [])
        if tag not in tags:
            return False
        tags.remove(tag)
        return True

    def do_getTags(self, uuid):
        return list(self.entity(uuid).get("tags", []))

    def do_setEntityEquipment(self, uuid, equipment, drop_chances=None):
        e = self.entity(uuid)
        if not (e.get("living") or "gamemode" in e):
            raise MockError(f"Entity is not a LivingEntity: {uuid}")
        for slot, item in equipment.items():
            if slot in EQUIPMENT_SLOTS:
                if self.material(item) is None and item not in NOT_BLOCKS:
                    raise MockError(f"Invalid item: {item}")
                e.setdefault("equipment", {})[slot] = "minecraft:" + str(item).lower().removeprefix("minecraft:")
        for slot, chance in (drop_chances or {}).items():
            if slot in EQUIPMENT_SLOTS:
                e.setdefault("drop_chances", {})[slot] = float(chance)
        return True

    def do_setEntityTarget(self, uuid, target_uuid=None):
        e = self.entity(uuid)
        if e.get("type") not in HOSTILE | {"wolf", "iron_golem", "fox", "snow_golem"}:
            raise MockError(f"Entity is not a Mob (cannot have a target): {uuid}")
        if target_uuid is None:
            e["target"] = None
            return True
        try:
            target = self.entity(target_uuid)
        except MockError:
            raise MockError(f"Target entity not found: {target_uuid}")
        e["target"] = target["uuid"]
        return True

    def do_setEntityAI(self, uuid, enabled):
        e = self.entity(uuid)
        if not e.get("living"):
            raise MockError(f"Entity is not a LivingEntity: {uuid}")
        e["ai"] = bool(enabled)
        return True

    # ------------------------------------------------------------ world

    def do_forceload(self, action, x, z):
        chunk = (int(x) >> 4, int(z) >> 4)
        if action == "add":
            self.forced.add(chunk)
            return True
        if action == "remove":
            self.forced.discard(chunk)
            return True
        if action == "query":
            return chunk in self.forced
        raise MockError(f"Invalid action: {action} (valid: add, remove, query)")

    def do_difficulty(self, level):
        if str(level).lower() not in {"peaceful", "easy", "normal", "hard"}:
            raise MockError(f"Invalid difficulty: {level}")
        self.difficulty = str(level).lower()
        return True

    # ------------------------------------------------------------ chat, sound, particles

    def do_say(self, message):
        for p in self.players.values():
            p["messages"].append("[Server] " + message)
        return True

    def do_tell(self, username, message):
        self.need_player(username, exact=False)["messages"].append(message)
        return True

    def do_title(self, username, title="", subtitle="", fade_in=10, stay=70, fade_out=20):
        self.need_player(username, exact=False)["titles"].append((title, subtitle))
        return True

    def do_playsound(self, username, sound, source="master", volume=1.0, pitch=1.0,
                     x=None, y=None, z=None):
        p = self.need_player(username, exact=False)
        if not re.match(r"^(minecraft:)?[a-z0-9_.]+$", str(sound)):
            raise MockError(f"mock: suspicious sound key {sound!r}")
        p["sounds"].append(sound)
        return True

    def do_particle(self, particle, x, y, z, count=1, dx=0, dy=0, dz=0, speed=0):
        name = str(particle).lower().removeprefix("minecraft:")
        if name in DATA_PARTICLES:
            raise MockError(f"Failed to spawn particle: missing required data for {name}")
        if name not in PARTICLES:
            raise MockError(f"Invalid particle type: {name}")
        return True

    # ------------------------------------------------------------ scoreboard

    def do_addObjective(self, name, criteria, display_name=None):
        if name in self.objectives:
            raise MockError(f"Objective already exists: {name}")
        if criteria not in CRITERIA:
            raise MockError(f"mock: unknown criteria {criteria}")
        self.objectives[name] = {"criteria": criteria, "display": display_name or name, "scores": {}}
        return True

    def do_removeObjective(self, name):
        if name not in self.objectives:
            raise MockError(f"Objective not found: {name}")
        del self.objectives[name]
        for slot in [s for s, o in self.display.items() if o == name]:
            del self.display[slot]
        return True

    def do_setScore(self, objective, player, score):
        if objective not in self.objectives:
            raise MockError(f"Objective not found: {objective}")
        self.objectives[objective]["scores"][player] = int(score)
        return True

    def do_getScore(self, objective, player):
        if objective not in self.objectives:
            raise MockError(f"Objective not found: {objective}")
        return self.objectives[objective]["scores"].get(player, 0)

    def do_setDisplaySlot(self, slot, objective=None):
        if str(slot).lower() not in SLOTS and not str(slot).lower().startswith("sidebar_team_"):
            raise MockError(f"Invalid display slot: {str(slot).upper()} (valid: BELOW_NAME, SIDEBAR, PLAYER_LIST)")
        if objective is None:
            self.display.pop(str(slot).lower(), None)
            return True
        if objective not in self.objectives:
            raise MockError(f"Objective not found: {objective}")
        self.display[str(slot).lower()] = objective
        return True

    def do_team(self, action, name=None, members=None, option=None, value=None, display_name=None):
        if action == "list":
            return {"teams": [{"name": n, "display_name": t["display"], "members": t["members"],
                               "size": len(t["members"])} for n, t in self.teams.items()]}
        if action == "add":
            if name in self.teams:
                raise MockError(f"Team already exists: {name}")
            self.teams[name] = {"display": display_name or name, "members": [], "options": {}}
            return {"name": name}
        if name not in self.teams:
            raise MockError(f"Team not found: {name}")
        team = self.teams[name]
        if action == "remove":
            del self.teams[name]
            return {"removed": True}
        if action == "join":
            for m in members or []:
                for t in self.teams.values():
                    if m in t["members"]:
                        t["members"].remove(m)
                team["members"].append(m)
            return {"added": len(members or [])}
        if action == "leave":
            removed = [m for m in members or [] if m in team["members"]]
            for m in removed:
                team["members"].remove(m)
            return {"removed_count": len(removed)}
        if action == "modify":
            team["options"][option] = value
            return {"modified": True}
        raise MockError(f"Invalid action: {action}")

    def do_bossbar(self, action, id, title=None, color=None, style=None, progress=None,
                   visible=None, username=None):
        bars = self.bossbars
        if action == "list":
            return {"bars": list(bars)}
        if action == "add":
            if id in bars:
                raise MockError(f"BossBar already exists: {id}")
            bars[id] = {"title": title if title is not None else id,
                        "color": str(color).upper() if str(color).upper() in BAR_COLORS else "WHITE",
                        "style": str(style).upper() if str(style).upper() in BAR_STYLES else "SOLID",
                        "progress": max(0.0, min(1.0, float(progress))) if progress is not None else 1.0,
                        "visible": True if visible is None else bool(visible), "players": []}
            return {"id": id}
        if id not in bars:
            raise MockError(f"BossBar not found: {id}")
        bar = bars[id]
        if action == "remove":
            del bars[id]
            return {"removed": True}
        if action == "set":
            if color is not None and str(color).upper() not in BAR_COLORS:
                raise MockError(f"Failed to modify bossbar: No enum constant BarColor.{color}")
            if style is not None and str(style).upper() not in BAR_STYLES:
                raise MockError(f"Failed to modify bossbar: No enum constant BarStyle.{style}")
            for key, val in (("title", title), ("color", color), ("style", style), ("visible", visible)):
                if val is not None:
                    bar[key] = str(val).upper() if key in ("color", "style") else val
            if progress is not None:
                bar["progress"] = max(0.0, min(1.0, float(progress)))
            return {"updated": True}
        if action in ("addplayer", "removeplayer"):
            if username is None:
                raise MockError("Missing parameter: username")
            p = self.player(username, exact=False)
            if p is None:
                raise MockError("Player not found")
            if action == "addplayer" and p["name"] not in bar["players"]:
                bar["players"].append(p["name"])
            if action == "removeplayer" and p["name"] in bar["players"]:
                bar["players"].remove(p["name"])
            return {"added": True} if action == "addplayer" else {"removed": True}
        if action == "get":
            return {"id": id, **{k: bar[k] for k in ("title", "color", "style", "progress", "visible", "players")}}
        raise MockError(f"Invalid action: {action}")


def strip_none(value):
    """Gson drops null map values; mirror that."""
    if isinstance(value, dict):
        return {k: strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [strip_none(v) for v in value]
    return value


class MockServer:
    """Threaded TCP server; start() runs it in the background."""

    def __init__(self, world: World, token: str = "test-token", host: str = "127.0.0.1", port: int = 0):
        self.world, self.token = world, token
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                for raw in self.rfile:
                    line = raw.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        request = json.loads(line)
                    except json.JSONDecodeError:
                        response = {"success": False, "error": "Invalid JSON"}
                    else:
                        if request.get("token", "") != outer.token:
                            response = {"success": False, "error": "Invalid token"}
                        else:
                            response = outer.world.handle(request)
                    self.wfile.write((json.dumps(response) + "\n").encode("utf-8"))
                    self.wfile.flush()

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.server = Server((host, port), Handler)
        self.port = self.server.server_address[1]
        self.thread = None

    def start(self) -> "MockServer":
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the MCPyLib mock server in the foreground.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=25599)
    ap.add_argument("--token", default="test-token")
    ap.add_argument("--player", nargs=4, action="append", metavar=("NAME", "X", "Y", "Z"), default=[])
    ap.add_argument("--mob-lifetime", type=float, help="hostile mobs 'die' after this many seconds")
    args = ap.parse_args()
    world = World(mob_lifetime=args.mob_lifetime)
    for name, x, y, z in args.player:
        world.add_player(name, float(x), float(y), float(z))
    server = MockServer(world, args.token, args.host, args.port)
    print(f"mock MCPyLib server on {args.host}:{server.port} (token {args.token!r}); Ctrl+C to stop")
    try:
        server.server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
