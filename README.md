# MCPyLib Skills

[![Validate](https://github.com/treeleaves30760/MCPyLib-skills/actions/workflows/validate.yml/badge.svg)](https://github.com/treeleaves30760/MCPyLib-skills/actions/workflows/validate.yml)

[Agent Skills](https://agentskills.io) that teach AI coding agents (Claude Code,
Claude.ai, Codex, Cursor and others) to control a Minecraft server from Python with
[MCPyLib](https://github.com/treeleaves30760/MCPyLib).

[繁體中文說明](README.zh-TW.md)

MCPyLib is a Python library (`pip install mcpylib` or `uv add mcpylib`) plus a
Spigot/Paper plugin. The plugin opens a TCP socket (port 65535 by default) and runs
token-authenticated JSON commands on the server. These skills give an agent the exact
API (checked against the library's source), safe working habits, and tested scripts,
so it writes code that works the first time and doesn't wreck the world.

## Skills

| Skill | Use it for |
|---|---|
| [`mcpylib`](skills/mcpylib/SKILL.md) | The core: checking the setup, connecting, coordinates and build height, block ids, states and NBT, choosing between `setblock`, `fill`, `edit`, `clone` and `getblocks`, performance, errors and safety rules. Includes a complete API reference for all 72 methods, the raw JSON protocol for other languages, and troubleshooting. |
| [`mcpylib-building`](skills/mcpylib-building/SKILL.md) | Procedural building in pure Python (no numpy): spheres, domes, cylinders, cones, pyramids, tori, houses, towers, pixel art from images, and noise or heightmap terrain. Every script does a dry run first, refuses to overwrite blocks unless allowed, and writes an undo file. |
| [`mcpylib-minigames`](skills/mcpylib-minigames/SKILL.md) | Games and live events: polling loops with a call budget, join and leave detection, scoreboards, teams, boss bars, titles, sounds, particles, mobs, and crash-safe cleanup. Includes King of the Hill and a mob arena. |
| [`mcpylib-mcp`](skills/mcpylib-mcp/SKILL.md) | Installing and using the [mcpylib-mcp](https://github.com/treeleaves30760/MCPyLib-mcp) MCP server with Claude Code, Claude Desktop, Cursor, VS Code and Codex, and deciding when MCP tools beat a Python script. |

Each skill is a folder with a `SKILL.md` (YAML frontmatter with `name` and
`description`, then instructions) plus `references/` and `scripts/` that the agent
reads or runs only when needed.

## Requirements

- A Paper or Spigot server running Minecraft **26.1 or newer** (built against 26.3) on
  **Java 25**, with the MCPyLib plugin **1.2.0** in `plugins/`.
- **Python 3.11+** and the client: `pip install mcpylib` or `uv add mcpylib`. The skills
  target client 1.2.0. If your package index still serves 1.1.1, it works too, with a
  slower `edit()` path and older retry behaviour; the core skill explains the
  differences.
- The plugin token, from `/mcpylib token` in the server console. Keep it in the
  environment or a git-ignored `.env`:
  ```
  MCPYLIB_HOST=127.0.0.1
  MCPYLIB_PORT=65535
  MCPYLIB_TOKEN=paste-token-here
  ```
  The mcpylib-mcp server reads the same variables.

## Install

### Claude Code: plugin marketplace (recommended)

```text
/plugin marketplace add treeleaves30760/MCPyLib-skills
/plugin install mcpylib@mcpylib-skills
```

This installs all four skills as the `mcpylib` plugin. Claude loads a skill when
your request matches its description; you can also call one directly, for example
`/mcpylib:mcpylib-building`. Update later with `/plugin marketplace update mcpylib-skills`.

### Claude Code: copy the folders

```bash
git clone https://github.com/treeleaves30760/MCPyLib-skills
mkdir -p ~/.claude/skills
cp -r MCPyLib-skills/skills/* ~/.claude/skills/      # personal: all projects
# or, for one project:  cp -r MCPyLib-skills/skills/* .claude/skills/
```

On Windows PowerShell:
`Copy-Item -Recurse MCPyLib-skills\skills\* "$HOME\.claude\skills\"`. Restart Claude
Code, then check that the skills are listed (ask "what skills do you have?").

### Claude.ai

1. Build one zip per skill (each zip holds the skill folder at its root):
   ```bash
   python tools/package_skills.py      # writes dist/mcpylib.zip, dist/mcpylib-building.zip, ...
   ```
2. Turn on **Code execution and file creation** in Settings > Capabilities.
3. Open **Customize > Skills**, click **+**, choose **Create skill** > **Upload a skill**,
   and upload `mcpylib.zip`. Repeat for the other zips you want; the other three build
   on `mcpylib`.

Claude's sandbox on Claude.ai usually can't reach your Minecraft server, and network
access depends on your plan and settings. There the skills are most useful for
writing and reviewing scripts that you then run on your own computer.

### Codex

Codex reads skills from `~/.agents/skills/` (all repositories) and `.agents/skills/`
(one repository):

```bash
mkdir -p ~/.agents/skills
cp -r MCPyLib-skills/skills/* ~/.agents/skills/
```

Start Codex and type `$mcpylib` (or use `/skills`) to call a skill explicitly; Codex
also picks one by itself when the task matches its description.

### Cursor, Gemini CLI and other agents (AGENTS.md)

Agents without Agent Skills support can still use the files: they are plain Markdown
and Python. Put this repository (or its `skills/` folder) somewhere in or next to your
project and add a pointer to your project's `AGENTS.md`:

```markdown
## Minecraft and MCPyLib
Before writing code that talks to a Minecraft server through MCPyLib, read
`MCPyLib-skills/skills/mcpylib/SKILL.md` and follow its links. For builds also read
`skills/mcpylib-building/SKILL.md`; for games `skills/mcpylib-minigames/SKILL.md`;
for MCP setup `skills/mcpylib-mcp/SKILL.md`. Every method name and parameter must
match `skills/mcpylib/references/api.md`.
```

This repository's own [AGENTS.md](AGENTS.md) does the same for agents that work
inside it.

## Try it

After installing, ask your agent things like:

- "Check my MCPyLib setup. My player name is Steve."
- "Build a glass dome with radius 12 in front of Steve. Show me the plan first."
- "Turn logo.png into 64-block-wide pixel art on a wall next to spawn."
- "Run a 3-wave mob arena around Steve with a glass wall."
- "Set up the mcpylib-mcp server for Claude Desktop."

The agent should run `check_setup.py` first, do dry runs before building, ask before
replacing blocks, and keep the undo command it prints.

## Repository layout

```text
.claude-plugin/        marketplace.json + plugin.json (Claude Code plugin marketplace)
skills/
  mcpylib/             core skill: SKILL.md, references/ (api, protocol, troubleshooting), scripts/
  mcpylib-building/    building skill: recipes and block references, buildkit + generators
  mcpylib-minigames/   minigame skill: loops, HUD and entity references, game_kit + two games
  mcpylib-mcp/         MCP server skill: client configurations and the tool list
tools/
  validate.py          frontmatter, links, py_compile, API signatures, manifests
  smoke_test.py        runs every script against tools/mock_server.py
  mock_server.py       offline stand-in for the MCPyLib 1.2.0 plugin protocol
  package_skills.py    builds dist/<skill>.zip for Claude.ai
AGENTS.md              instructions for agents working in this repository
```

## Development

```bash
pip install pyyaml mcpylib skills-ref
python tools/validate.py        # frontmatter, links, py_compile, mc.* calls vs the real API
python tools/smoke_test.py      # every script against the mock plugin (about 30 s)
agentskills validate skills/mcpylib   # the reference validator, once per skill
claude plugin validate .        # if you have Claude Code installed
```

`validate.py` checks that every `mc.<method>(...)` call in the scripts and Markdown
binds to the signature of the installed `mcpylib`, and that the API reference lists
each public method exactly once with its exact signature. The GitHub Action in
`.github/workflows/validate.yml` runs the validators and smoke tests on Python 3.11
and 3.13. The smoke tests use a mock of the plugin's protocol, not a live server, so
test changes in game as well.

## Related projects

- [MCPyLib](https://github.com/treeleaves30760/MCPyLib): the Python library and the
  Spigot/Paper plugin.
- [MCPyLib-mcp](https://github.com/treeleaves30760/MCPyLib-mcp): MCP server exposing
  MCPyLib as tools.
- [MCPyLib website](https://treeleaves30760.github.io/MCPyLib-website/): documentation
  and showcase.

## License

[Non-Commercial License with Commercial Exception](LICENSE), the same license as
MCPyLib. Each skill folder carries a copy as `LICENSE.txt` so it stays licensed when
copied or zipped on its own.
