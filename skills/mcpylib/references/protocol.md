# MCPyLib wire protocol (plugin 1.2.0)

Use this to talk to the MCPyLib plugin from any language. It is derived from the
plugin source (`ClientHandler.java`, `CommandHandler.java`, `TokenManager.java`).
`docs/protocol.md` in the main repo predates persistent connections and is wrong in
places.

## Contents

- [Transport](#transport)
- [Request and response](#request-and-response)
- [Value encoding rules](#value-encoding-rules)
- [Actions and JSON keys](#actions-and-json-keys)
- [bulkEdit encoding](#bulkedit-encoding)
- [Node.js example](#nodejs-example)
- [Quick manual test](#quick-manual-test)

## Transport

- **TCP**, UTF-8, default port **65535**, configured with `server.port` in
  `plugins/MCPyLib/config.yml`. The socket binds to `server.host` (default
  `0.0.0.0`, every interface; `127.0.0.1` allows local clients only). Plugin 1.1.x
  ignored `server.host` and always bound every interface.
- **Framing**: one JSON object per line, terminated by `\n`. Blank lines are ignored.
  Replies end with the server's line separator (`\r\n` on Windows hosts),
  so trim each line before parsing.
- **Persistent connection**: keep the socket open and send many requests. The server
  handles one request at a time per connection and answers in order. The plugin
  closes a connection that sends nothing for `server.idle-timeout-seconds` (default
  300; 0 = never). Reconnect when you find the socket closed.
- **Concurrency**: the plugin has a fixed pool of `server.max-connections` worker
  threads (default 10), and each open connection holds one. A connection beyond the
  limit gets one reply to its first request,
  `{"success":false,"error":"Server busy: max-connections (10) reached. ...","data":null}`,
  and is closed. Close sockets you don't need. (Plugin 1.1.x queued extra
  connections without answering them.)
- **Latency**: every request waits for the next tick of the server's main thread, so
  a single call takes up to ~50 ms and one connection completes about 20 calls per
  second. Batch work, for example with `bulkEdit`.

## Request and response

Request:
```json
{"token": "<token>", "action": "setblock", "params": {"x": 0, "y": 64, "z": 0, "block": "minecraft:stone"}}
```

- `token`: a string. The plugin generates a 43-character base64url token on first
  start. With `security.require-token: false`, any token is accepted. A missing token
  counts as `""`.
- `action`: case-insensitive (`setBlock` = `setblock`). An unknown action gives
  `Unknown action: <name>`.
- `params`: an object, which may be omitted.

Success response (`data` is omitted when it is null):
```json
{"success":true,"data":1}
```

Error response (normally without a `data` key; the `Server busy` reply carries
`"data":null`):
```json
{"success":false,"error":"Invalid block type: minecraft:stonee"}
```

Other errors:
- `Invalid token` for authentication failures. The Python client turns any error
  containing "token" into `AuthenticationError`.
- `Invalid JSON` when a line doesn't parse.
- `Missing parameter(s): ...` when a required key is absent.
- `Failed to <verb>: <java message>` from most handlers, for example
  `Failed to set block: ...`.
- `Error executing command: <java message>` for exceptions a handler doesn't catch,
  such as a value of the wrong type.
- `Server busy: max-connections (N) reached. ...` for a connection beyond the limit.
- A `null` token, action or params, params that are not an object, or a line that
  is just `null` make the plugin close the connection without replying.

## Value encoding rules

- **Omit optional keys** instead of sending `null`. Most handlers check whether a key
  exists and then read it, so `"yaw": null` fails. Only `setEntityTarget.target_uuid`,
  `ride.vehicle_uuid`, `damage.source_uuid`, `clearEffect.effect`, `clear.item`,
  `stopsound.sound`/`source`, `gamerule.value`, `setDisplaySlot.objective` and
  `fillbiome.filter_biome` accept null at the top level, plus the nested
  `setEntityEquipment.equipment.<slot>` and `setVillagerTrades.trades[].buy2`.
- **Integers**: block coordinates are read with Gson `getAsInt`, which truncates
  floats toward zero, so `-0.5` becomes `0`. Send integers, and floor entity
  positions yourself.
- **Doubles**: entity and teleport coordinates, velocities and volumes accept
  fractional numbers.
- **Strings for states**: `block_state` values are read as strings; JSON booleans and
  numbers are converted.
- **Responses** use Gson defaults. Java ints are JSON integers, doubles may print as
  `64.0`, and map entries whose value is null are **dropped**, so treat missing keys
  as null.

## Actions and JSON keys

`?` marks an optional key; omit it rather than sending null. Behaviour, limits and
return shapes are in [api.md](api.md). The Python method of the same name maps its
arguments to these keys. Where the names differ (`block_name` becomes `block`,
`entity_uuid` becomes `uuid`, `effect_type` becomes `effect`, and so on), the JSON
key is what matters.

| action | params | data |
|---|---|---|
| setblock | x, y, z, block, block_state?, nbt? | 1 |
| getblock | x, y, z | "minecraft:..." |
| getblocks | x1, y1, z1, x2, y2, z2 | [[[str]]] indexed [x][y][z] from the min corner |
| fill | x1, y1, z1, x2, y2, z2, block | int |
| bulkEdit | x, y, z + compressed or legacy body (see below) | int |
| clone | x1, y1, z1, x2, y2, z2, dest_x, dest_y, dest_z | int |
| getPos | username | [x, y, z] ints |
| teleport | username, x, y, z, yaw?, pitch? (both or neither) | true |
| gamemode | username, mode | true |
| give | username, item, amount? (1-64) | true |
| effect | username, effect, duration? (s, 30), amplifier? (0), hide_particles? | bool |
| clearEffect | username, effect? | true |
| clear | username, item?, max_count? (-1) | int |
| experience | username, action, amount (required), target? ("points") | {level, points, progress} |
| enchant | username, enchantment, level? (1) | true |
| getItem | username, slot | {item?, amount, enchantments?} |
| setItem | username, slot, item, amount? (1) | true |
| spawnpoint | username, x?, y?, z? | true |
| advancement | username, action, advancement | bool |
| list | (none) | {online_count, max_players, players:[{name, uuid, gamemode}]} |
| summon | entity_type, x, y, z | "uuid" |
| kill | selector | int |
| getEntityPos | uuid | {x, y, z, yaw, pitch} |
| getEntityStatus | uuid | {uuid, type, is_valid, is_dead, world, position, velocity, custom_name?, health?, max_health?, has_ai?} |
| teleportEntity | uuid, x, y, z, yaw?, pitch? | bool |
| setEntityVelocity | uuid, vx, vy, vz | true |
| setEntityRotation | uuid, yaw, pitch | true |
| setEntityAI | uuid, enabled | true |
| setEntityTarget | uuid, target_uuid? | true |
| removeEntity | uuid | true |
| getEntityEquipment | uuid | {helmet?, chestplate?, leggings?, boots?, main_hand?, off_hand?} |
| setEntityEquipment | uuid, equipment, drop_chances? | true |
| damage | uuid, amount, source_uuid? | true |
| ride | passenger_uuid, vehicle_uuid? | bool |
| attribute | uuid, attribute, action? ("get"), value? | {base_value, value} |
| addTag / removeTag | uuid, tag | bool |
| getTags | uuid | [str] |
| getVillagerData | uuid | {profession, level, trades} |
| setVillagerProfession | uuid, profession | true |
| setVillagerTrades | uuid, trades | true |
| time | action, value? | int |
| weather | condition, duration? (s) | true |
| difficulty | level | true |
| gamerule | rule, value? | "value" |
| defaultgamemode | mode | true |
| setworldspawn | x, y, z | bool |
| worldborder | action, value?, time?, x?, z? | object |
| forceload | action, x, z (block coords) | bool |
| locate | structure, x?, z? | {found, x?, y?, z?} |
| loot | loot_table, x, y, z | int |
| say | message | true |
| tell | username, message | true |
| title | username, title?, subtitle?, fade_in?, stay?, fade_out? | true |
| playsound | username, sound, source?, x?, y?, z?, volume?, pitch? | true |
| stopsound | username, sound?, source? | true |
| particle | particle, x, y, z, count?, dx?, dy?, dz?, speed? | true |
| addObjective | name, criteria, display_name? | true |
| removeObjective | name | true |
| setScore | objective, player, score | true |
| getScore | objective, player | int |
| setDisplaySlot | slot, objective? | true |
| team | action, name?, members?, option?, value?, display_name? | object |
| bossbar | action, id, title?, color?, style?, progress?, visible?, username? | object |
| exec | command | bool* |
| tellraw | username, json_text | bool* |
| fillbiome | x1, y1, z1, x2, y2, z2, biome, filter_biome? | bool* |
| placeFeature | feature, x?, y?, z? (all three or none) | bool* |
| placeStructure | structure, x?, y?, z? | bool* |
| placeJigsaw | pool, target, max_depth, x?, y?, z? | bool* |
| placeTemplate | template, x?, y?, z?, rotation?, mirror?, integrity?, seed? | bool* |
| spreadplayers | center_x, center_z, spread_distance, max_range, usernames | bool* |

\* These eight run a console command. `data` says whether it was dispatched, not
whether it worked. Plugins older than 1.2.0 freeze the server on them.

## bulkEdit encoding

The fast format, used by the 1.2.0 Python client:

```json
{"token": "...", "action": "bulkEdit", "params": {
  "x": 100, "y": 64, "z": 200,
  "sizeX": 2, "sizeY": 1, "sizeZ": 3,
  "palette": [null, "minecraft:stone", {"block": "oak_stairs", "block_state": {"facing": "north"}}],
  "data": "<base64(zlib(rle))>",
  "encoding": "palette_rle_zlib"
}}
```

1. Flatten the 3-D array in **x, then y, then z** order: flat index
   `i = (dx * sizeY + dy) * sizeZ + dz`.
2. Replace each cell with its palette index. Palette entries are `null` (skip the
   cell), a block id string, or an object with `block` and optional `block_state` and
   `nbt`.
3. Run-length encode the indices as `count,index` pairs joined by commas, for example
   `"5,1,1,0"`. The runs must cover exactly `sizeX*sizeY*sizeZ` cells. If they cover
   fewer, the remaining cells get palette index 0.
4. Compress that ASCII string with zlib (RFC 1950 stream, the default for
   `zlib.compress` or `deflateSync`). Send the **complete** stream: plugin 1.2.0
   inflates in a loop that never ends on empty or truncated data, which freezes
   the server's main thread. Data that isn't zlib at all is rejected with an error.
5. Encode it as standard base64 with padding. URL-safe base64 is rejected.

The response `data` is the number of cells written. On the plugin's fast path,
string palette entries are written directly into chunk sections, with no physics
and no lighting update, and cells outside the world or naming items are skipped
and not counted. Object entries with `block_state` or `nbt` get a second pass
through the Bukkit API; `{"block": ...}` alone acts like a string.

Legacy format: omit `encoding` and send `"blocks": [[[cell, ...], ...], ...]`, using
the same cell values in `[x][y][z]` order. Every cell then goes through the slower
Bukkit API. Plugins older than 1.2.0 accept only this format.

## Node.js example

Node 18+, no dependencies. Replies come back in request order, so a FIFO queue of
pending promises matches them. The client opens the socket on first use and again
after the server closed it (idle timeout, restart); requests in flight at that moment
are rejected.

```js
import net from "node:net";
import zlib from "node:zlib";

export class MCPyLibClient {
  constructor({ host = "127.0.0.1", port = 65535, token }) {
    Object.assign(this, { host, port, token, sock: null, connecting: null, buf: "", waiting: [] });
  }
  connect() {
    if (this.sock) return Promise.resolve();
    this.connecting ??= new Promise((resolve, reject) => {
      const sock = net.createConnection({ host: this.host, port: this.port });
      sock.setEncoding("utf8");
      sock.once("connect", () => { this.sock = sock; this.connecting = null; resolve(); });
      sock.on("data", (chunk) => this.onData(chunk));
      sock.on("error", (err) => { this.connecting = null; reject(err); });
      sock.on("close", () => {
        if (this.sock === sock) this.sock = null;
        this.failPending(new Error("MCPyLib connection closed"));
      });
    });
    return this.connecting;
  }
  onData(chunk) {
    this.buf += chunk;
    let nl;
    while ((nl = this.buf.indexOf("\n")) >= 0) {
      const line = this.buf.slice(0, nl).trim();   // replies may end in \r\n
      this.buf = this.buf.slice(nl + 1);
      const pending = line && this.waiting.shift();
      if (!pending) continue;
      const res = JSON.parse(line);
      res.success ? pending.resolve(res.data ?? null) : pending.reject(new Error(res.error));
    }
  }
  failPending(err) {
    for (const p of this.waiting.splice(0)) p.reject(err);
    this.buf = "";
  }
  async call(action, params = {}) {
    await this.connect();
    return new Promise((resolve, reject) => {
      this.waiting.push({ resolve, reject });
      this.sock.write(JSON.stringify({ token: this.token, action, params }) + "\n");
    });
  }
  close() { this.sock?.end(); }
}

// blocks[x][y][z] -> bulkEdit params (cells: null | "id" | {block, block_state?, nbt?})
export function bulkEditParams(x, y, z, blocks) {
  const palette = [], index = new Map(), rle = [];
  const sizeX = blocks.length, sizeY = blocks[0].length, sizeZ = blocks[0][0].length;
  let prev = -1, run = 0;
  for (const plane of blocks) for (const row of plane) for (const cell of row) {
    const key = JSON.stringify(cell);
    if (!index.has(key)) { index.set(key, palette.length); palette.push(cell); }
    const idx = index.get(key);
    if (idx === prev) run++; else { if (run) rle.push(run, prev); prev = idx; run = 1; }
  }
  if (run) rle.push(run, prev);
  const data = zlib.deflateSync(Buffer.from(rle.join(","))).toString("base64");
  return { x, y, z, sizeX, sizeY, sizeZ, palette, data, encoding: "palette_rle_zlib" };
}

// Usage:
// const client = new MCPyLibClient({ token: process.env.MCPYLIB_TOKEN });
// await client.connect();
// console.log(await client.call("list"));
// await client.call("bulkEdit", bulkEditParams(0, 64, 0, [[["stone", null]]]));
// client.close();
```

## Quick manual test

```bash
printf '{"token":"%s","action":"list","params":{}}\n' "$MCPYLIB_TOKEN" | nc -q 1 127.0.0.1 65535
```

The flag that keeps `nc` open long enough to read the reply differs between netcat
builds: `-q 1` on Debian, `-N` on OpenBSD.
