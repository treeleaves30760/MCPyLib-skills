# AGENTS.md

Instructions for AI coding agents (Codex, Cursor, Gemini CLI, Claude and others)
working in this repository or using its skills.

## What this repository is

Four Agent Skills that teach agents to control a Minecraft (Paper/Spigot 26.1+)
server from Python with MCPyLib, plus the tooling that keeps them correct:

| Skill | Read it when |
|---|---|
| `skills/mcpylib/SKILL.md` | Any MCPyLib task: setup, connecting, blocks, players, entities, errors, safety |
| `skills/mcpylib-building/SKILL.md` | Building structures, shapes, pixel art or terrain with code |
| `skills/mcpylib-minigames/SKILL.md` | Games, events, scoreboards, boss bars, polling loops, mobs |
| `skills/mcpylib-mcp/SKILL.md` | Setting up or using the mcpylib-mcp MCP server |

## Using the skills (if your tool has no native skill support)

1. Read the matching `SKILL.md` before writing code; follow its links into
   `references/` only as needed.
2. Every method name and parameter must match
   `skills/mcpylib/references/api.md` (generated from and checked against the
   library's `client.py`). Don't invent methods.
3. Prefer the bundled scripts (`skills/*/scripts/`) over writing new code. They do
   dry runs, refuse to overwrite blocks without `--allow-overwrite`, write undo
   files, and clean up after games.
4. Safety: read before you write, confirm destructive or world-wide changes with the
   user, never call `kill("all")` or `kill("<type>")` on a shared world, and never
   print, commit or pass the token on a command line. The token comes from
   `MCPYLIB_TOKEN` (environment or `.env`).

## Working on this repository

- Layout: `skills/<name>/` holds `SKILL.md`, `LICENSE.txt` (a copy of the root
  `LICENSE`), `references/` and `scripts/`. `.claude-plugin/` holds the Claude Code
  marketplace and plugin manifests. `tools/` holds the validator, the mock plugin,
  the smoke tests and the packager.
- `SKILL.md` frontmatter uses only `name`, `description`, `license`, `compatibility`
  and `metadata` (string values). `name` matches the folder (lowercase letters,
  digits, single hyphens). `description` is one plain line under 1,024 characters
  that says what the skill does and contains "Use when".
- Keep each `SKILL.md` under 500 lines; move detail to `references/` (one level
  deep, linked from `SKILL.md`).
- Scripts are pure Python 3.11+ with only `mcpylib` (and optional Pillow). They must
  pass `py_compile`, run with `--help` before `mcpylib` is configured, and read the
  token from the environment only.
- After any change, run and pass all of these:
  ```bash
  python tools/validate.py
  python tools/smoke_test.py
  agentskills validate skills/<each skill>
  claude plugin validate .        # when Claude Code is available
  ```
- When `client.py` changes, update `skills/mcpylib/references/api.md` until
  `validate.py` passes; its signature lines must match exactly.
- Add new script behaviour to `tools/mock_server.py` and a test to
  `tools/smoke_test.py`.
- Bump `version` in `.claude-plugin/plugin.json` (and `metadata.version` in the
  changed skills) for user-visible changes.
