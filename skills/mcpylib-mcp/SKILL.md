---
name: mcpylib-mcp
description: Installs, configures and uses mcpylib-mcp, the MCP server that exposes MCPyLib as 86 tools (blocks, players, world, entities, chat, scoreboard) for Claude Code, Claude Desktop, Cursor, VS Code, Codex and other MCP clients. Covers the uvx install, the MCPYLIB_HOST, MCPYLIB_PORT and MCPYLIB_TOKEN settings, per-client configuration, read-only mode, tool allow and deny lists, the per-call block limit, the text-layers build format, troubleshooting, and when to use MCP tools versus a Python script with the mcpylib library. Use when the user wants to connect an AI assistant or editor to a Minecraft server, mentions MCP, mcpylib-mcp, Model Context Protocol, uvx or claude mcp add, sees mcpylib tools such as get_blocks or build_from_layers, or asks whether to use tools or a script for a Minecraft task.
license: MCPyLib Non-Commercial License with Commercial Exception. Complete terms in LICENSE.txt
compatibility: Requires uv (for uvx) or Python 3.11+ with pip, an MCP client, and a Paper/Spigot 26.1+ server running the MCPyLib plugin 1.2.0+.
metadata:
  author: treeleaves30760
  version: "1.0.0"
  mcpylib-mcp-version: "0.1.0"
---

# mcpylib-mcp: MCPyLib as MCP tools

```text
MCP client --(stdio or HTTP)--> mcpylib-mcp --(TCP 65535 + token)--> MCPyLib plugin on Paper/Spigot
```

`mcpylib-mcp` (https://github.com/treeleaves30760/MCPyLib-mcp, version 0.1.0) wraps
the MCPyLib Python client as 86 typed MCP tools, three resources and two prompts. The
agent calls tools; nobody writes Python. For the underlying API and the server-side
setup, use the **mcpylib** skill.

## 1. Install and check

1. **Plugin and token**: the Minecraft server needs the MCPyLib plugin 1.2.0+.
   Run `/mcpylib token` in the console (or in game with `mcpylib.admin`) and copy
   the token.
2. **Runner**: install uv (it provides `uvx`), or use Python 3.11+ with
   `pip install mcpylib-mcp`.
3. **Check** that the server starts. This needs no token and doesn't connect to
   Minecraft:
   ```bash
   uvx mcpylib-mcp --list-tools
   ```
   `uvx` installs it from PyPI and caches it; add `--refresh` once to pick up a new
   release, or pin one with `uvx mcpylib-mcp@0.1.0`.

## 2. Add it to a client

Claude Code (options must come before the name, and another option must separate
`--env` from the name):

```bash
claude mcp add --env MCPYLIB_TOKEN=<token> --transport stdio mcpylib -- uvx mcpylib-mcp
```

Add `--env MCPYLIB_HOST=<ip>` for a remote server and `--scope user` for all projects.
Check with `claude mcp list` or `/mcp`.

| Client | Where the configuration goes |
|---|---|
| Claude Code | `claude mcp add ...`, or `.mcp.json` in the project with `"MCPYLIB_TOKEN": "${MCPYLIB_TOKEN}"` |
| Claude Desktop | `claude_desktop_config.json` (Settings > Developer > Edit Config), then restart |
| Cursor | `~/.cursor/mcp.json` (all projects) or `.cursor/mcp.json` (one project) |
| VS Code | `.vscode/mcp.json` with a `promptString` input for the token |
| Codex | `[mcp_servers.mcpylib]` in `~/.codex/config.toml`, or `codex mcp add` |

Copy-ready configurations for each client, plus the HTTP transport, are in
[references/clients.md](references/clients.md).

**Token hygiene**: put the token in an `env` block or environment variable, never in
`args` (command lines are visible to other users) and never in a committed file. Use
`${MCPYLIB_TOKEN}` in shared `.mcp.json` files.

## 3. Settings

Environment variables; flags of the same meaning take precedence.

| Variable | Default | Meaning |
|---|---|---|
| `MCPYLIB_TOKEN` | required | Plugin token |
| `MCPYLIB_HOST` / `MCPYLIB_PORT` | `localhost` / `65535` | Where the plugin listens (`--mc-host`, `--mc-port`) |
| `MCPYLIB_TIMEOUT` | `30` | Seconds to wait for each plugin reply |
| `MCPYLIB_MAX_BLOCKS` | `100000` | Most blocks one tool call may read or change |
| `MCPYLIB_READ_ONLY` | `false` | Register only the 21 read-only tools |
| `MCPYLIB_ALLOWED_TOOLS` / `MCPYLIB_DENIED_TOOLS` | all / none | Names, globs (`get_*`) or groups (`group:blocks`); the denylist wins |
| `MCPYLIB_TRANSPORT` | `stdio` | `stdio` or `http` (streamable HTTP on `MCPYLIB_HTTP_HOST:MCPYLIB_HTTP_PORT/mcp`, default `127.0.0.1:8000`) |
| `MCPYLIB_LOG_LEVEL` | `INFO` | Logs go to stderr; `DEBUG` shows every plugin call |

Good presets:
- **Look but don't touch**: `MCPYLIB_READ_ONLY=true`.
- **Building only**: `MCPYLIB_ALLOWED_TOOLS="group:blocks get_players get_player_position"`.
- **Shared server**: `MCPYLIB_DENIED_TOOLS=run_command,kill_entities`. `run_command` runs
  any console command and bypasses the block limit.

## 4. Working with the tools

1. **Orient**: `get_players`, `get_player_position`, or the `minecraft://server/status`
   resource. All block, world and particle tools act on the main overworld; Y is
   -64..319.
2. **Read before you write**: `get_blocks` (text layers) or `get_height_map` over the
   site. Report what would be replaced and get confirmation before destructive
   tools such as `fill_region` with air, `kill_entities` or `clear_inventory`.
3. **Build**: `build_from_layers` for designed structures, `edit_blocks` for 3D
   arrays, `fill_region` for one material, `set_block` for a few blocks with states or
   sign text. Then verify with `get_blocks`.
4. **Stay within limits**: 100,000 blocks per call (split bigger jobs) and 32,768 for
   `clone_region`.

The **layers format** used by `get_blocks` and `build_from_layers`:
- `palette` maps single characters to blocks, or to
  `{"block": ..., "block_state": {...}}`.
- `layers` run bottom to top. Each layer is a list of rows from north to south, and
  each row a string read west to east.
- `.` is air and a space leaves the existing block unchanged.

```json
{"x": 100, "y": 64, "z": -20,
 "palette": {"#": "stone_bricks", "G": "glass"},
 "layers": [["###", "#.#", "###"], ["#G#", "G.G", "#G#"]]}
```

Other habits:
- Keep approval prompts on for destructive tools; tools carry MCP read-only and
  destructive annotations.
- After a timeout the action may still have happened on the server, and with mcpylib
  1.1.1 it is retried once, so `give_item` or
  `summon_entity` may even have run twice. Check before repeating it.
- The `build_structure` and `survey_area` prompts and the `minecraft://guide/building`
  resource give a ready-made workflow.

## 5. MCP tools or a Python script?

| Task | Use | Why |
|---|---|---|
| Questions and inspection (who is online, what is here, find flat ground) | MCP | One call, no code |
| One-off actions (time, weather, give, teleport, effects) | MCP | Instant, approvable |
| Small or medium designed builds (up to about 100,000 blocks) | MCP `build_from_layers` | Agent designs the layers directly |
| Large or procedural builds (spheres, terrain, pixel art from an image) | Python, **mcpylib-building** | Math in code, chunked batches, dry run and undo files |
| Anything that loops or reacts over time (minigames, timers, polling) | Python, **mcpylib-minigames** | MCP calls are request and response; a loop needs a running program |
| Repeatable jobs, sharing, version control | Python | Re-run the same script |
| Users without a terminal (Claude Desktop chat) | MCP | Nothing to install beyond the server entry |

They combine well: survey with MCP tools, then write a script for the heavy part. A
script and the MCP server can use the same token; each open connection takes one of
the plugin's `server.max-connections` slots (default 10).

[references/tools.md](references/tools.md) lists every tool with the MCPyLib method
it calls, which helps when moving a task from MCP tools to a script.

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `no MCPyLib token configured` | Set `MCPYLIB_TOKEN` in the client's `env` block |
| `Authentication failed ... rejected the token` | Token wrong or regenerated: run `/mcpylib token` and update the config |
| `Cannot reach the MCPyLib plugin at host:port` | Server down, plugin not loaded, wrong host or port, or a firewall |
| `Timed out after 30s ...` | Use smaller regions, or raise `MCPYLIB_TIMEOUT` |
| `... more than the per-call limit ...` | Split the region; raise `MCPYLIB_MAX_BLOCKS` only on purpose |
| No tools in the client | Run the configured command with `--list-tools` in a terminal; check allow and deny lists; Claude Desktop may need the full path to `uvx` (`spawn uvx ENOENT`) |
| `uvx` cannot fetch the repository | Check the URL and network, or clone the repository and run `uv run mcpylib-mcp` |

## References

- [references/clients.md](references/clients.md): configurations for Claude Code,
  Claude Desktop, Cursor, VS Code, Codex and HTTP clients.
- [references/tools.md](references/tools.md): all 86 tools by group, with access
  level and the MCPyLib method behind each.
