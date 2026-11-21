# Client configurations for mcpylib-mcp

Every client runs the same command:

```text
uvx --from git+https://github.com/treeleaves30760/MCPyLib-mcp mcpylib-mcp
```

with `MCPYLIB_TOKEN` (and, for a remote or non-default server, `MCPYLIB_HOST` and
`MCPYLIB_PORT`) in its environment. Replace `<token>` with the output of
`/mcpylib token`.

## Contents

- [Claude Code](#claude-code)
- [Claude Desktop](#claude-desktop)
- [Cursor](#cursor)
- [VS Code](#vs-code)
- [Codex](#codex)
- [Streamable HTTP](#streamable-http)
- [Without uv](#without-uv)

## Claude Code

```bash
claude mcp add --env MCPYLIB_TOKEN=<token> --transport stdio mcpylib -- uvx --from git+https://github.com/treeleaves30760/MCPyLib-mcp mcpylib-mcp
```

- Options go before the server name. `--env` takes several `KEY=value` pairs, so
  keep another option (here `--transport stdio`) between it and the name, or the name
  is read as a pair. Repeat `--env` for `MCPYLIB_HOST=...` and `MCPYLIB_PORT=...`.
- Everything after `--` is the server command.
- `--scope local` (default, this project, only you), `--scope project` (writes
  `.mcp.json` for everyone), `--scope user` (all your projects).
- Check: `claude mcp list`, `claude mcp get mcpylib`, or `/mcp` in a session.
- Tools appear as `mcp__mcpylib__<tool>`, for example `mcp__mcpylib__get_blocks`.

Shared project file `.mcp.json` (commit it; each user exports `MCPYLIB_TOKEN`):

```json
{
  "mcpServers": {
    "mcpylib": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/treeleaves30760/MCPyLib-mcp", "mcpylib-mcp"],
      "env": {
        "MCPYLIB_TOKEN": "${MCPYLIB_TOKEN}",
        "MCPYLIB_HOST": "${MCPYLIB_HOST:-localhost}"
      }
    }
  }
}
```

`${VAR:-default}` uses the default when the variable is unset. An unset variable
without a default stays as literal text, and `claude mcp list` warns about it.

## Claude Desktop

Open **Settings > Developer > Edit Config**. The file is
`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS and
`%APPDATA%\Claude\claude_desktop_config.json` on Windows.

```json
{
  "mcpServers": {
    "mcpylib": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/treeleaves30760/MCPyLib-mcp", "mcpylib-mcp"],
      "env": {
        "MCPYLIB_TOKEN": "<token>",
        "MCPYLIB_HOST": "localhost",
        "MCPYLIB_PORT": "65535"
      }
    }
  }
}
```

Restart Claude Desktop afterwards. If it reports `spawn uvx ENOENT`, it can't find
`uvx` on its PATH: put the full path in `command` (from `which uvx` on macOS or Linux,
`where uvx` on Windows).

## Cursor

`~/.cursor/mcp.json` for all projects, or `.cursor/mcp.json` in one project:

```json
{
  "mcpServers": {
    "mcpylib": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/treeleaves30760/MCPyLib-mcp", "mcpylib-mcp"],
      "env": { "MCPYLIB_TOKEN": "<token>" }
    }
  }
}
```

Keep a file that contains the token out of version control; the user-level
`~/.cursor/mcp.json` is the safer place.

## VS Code

`.vscode/mcp.json` in the workspace, or **MCP: Open User Configuration** for all
workspaces. VS Code uses `servers` (not `mcpServers`), and the input prompts for the
token once instead of storing it in the file:

```json
{
  "inputs": [
    {
      "type": "promptString",
      "id": "mcpylib-token",
      "description": "MCPyLib token (run /mcpylib token on the Minecraft server)",
      "password": true
    }
  ],
  "servers": {
    "mcpylib": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/treeleaves30760/MCPyLib-mcp", "mcpylib-mcp"],
      "env": { "MCPYLIB_TOKEN": "${input:mcpylib-token}" }
    }
  }
}
```

## Codex

`~/.codex/config.toml`, or `.codex/config.toml` in a trusted project:

```toml
[mcp_servers.mcpylib]
command = "uvx"
args = ["--from", "git+https://github.com/treeleaves30760/MCPyLib-mcp", "mcpylib-mcp"]
env_vars = ["MCPYLIB_TOKEN", "MCPYLIB_HOST"]   # forwarded from your shell
startup_timeout_sec = 60                       # the first uvx run downloads packages
```

Or from the command line:

```bash
codex mcp add mcpylib --env MCPYLIB_TOKEN=<token> -- uvx --from git+https://github.com/treeleaves30760/MCPyLib-mcp mcpylib-mcp
```

Check with `codex mcp list`, or `/mcp` in the Codex TUI.

## Streamable HTTP

For clients that connect to a URL, or to share one server process between clients,
start it yourself:

```bash
MCPYLIB_TOKEN=<token> uvx --from git+https://github.com/treeleaves30760/MCPyLib-mcp mcpylib-mcp --transport http --port 8000
```

In PowerShell, run `$env:MCPYLIB_TOKEN = "<token>"` first. Then point clients at
`http://127.0.0.1:8000/mcp`:

- Claude Code: `claude mcp add --transport http mcpylib http://127.0.0.1:8000/mcp`
- VS Code: `"mcpylib": { "type": "http", "url": "http://127.0.0.1:8000/mcp" }`
- Cursor: `"mcpylib": { "url": "http://127.0.0.1:8000/mcp" }`

The HTTP endpoint has **no authentication**. It binds to `127.0.0.1` by default; to
reach it from elsewhere, use an SSH tunnel, a VPN or an authenticating reverse proxy
rather than binding it to a public address.

## Without uv

```bash
pip install git+https://github.com/treeleaves30760/MCPyLib-mcp
mcpylib-mcp --list-tools
```

Then use `mcpylib-mcp` as the `command` (with no `args`) in the configurations above,
or its full path if the client doesn't see your virtual environment.
