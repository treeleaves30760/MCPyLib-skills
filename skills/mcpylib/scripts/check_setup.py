#!/usr/bin/env python3
"""Read-only check that MCPyLib can reach and authenticate with a Minecraft server.

It never changes the world. Exit status 0 = ready, 1 = a check failed.

Usage:
    python check_setup.py [--player NAME] [--host H] [--port P] [--env-file .env]

Settings come from (highest priority first): command-line flags, environment
variables MCPYLIB_HOST / MCPYLIB_PORT / MCPYLIB_TOKEN (or SERVER_IP /
SERVER_PORT / SERVER_TOKEN as used by the MCPyLib examples), then a .env file.
Prefer the environment for the token; --token is visible in process lists.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path

MIN_CLIENT = (1, 2, 0)
results: list[tuple[str, str, str]] = []


def report(status: str, check: str, detail: str = "") -> None:
    results.append((status, check, detail))
    print(f"[{status:^4}] {check}" + (f" - {detail}" if detail else ""))


def load_env_file(path: str) -> None:
    """Load KEY=VALUE lines without overriding variables that are already set."""
    try:
        from dotenv import load_dotenv  # installed together with mcpylib
    except ImportError:
        load_dotenv = None
    if load_dotenv is not None:
        load_dotenv(path, override=False)
        return
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        os.environ.setdefault(key, value)


def first_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def parse_version(text: str) -> tuple[int, ...]:
    parts = []
    for piece in text.split(".")[:3]:
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only MCPyLib connection check.")
    ap.add_argument("--host", help="server address (default MCPYLIB_HOST or 127.0.0.1)")
    ap.add_argument("--port", type=int, help="plugin port (default MCPYLIB_PORT or 65535)")
    ap.add_argument("--token", help="token (prefer the MCPYLIB_TOKEN environment variable)")
    ap.add_argument("--player", help="online player to look up (position, world, block below)")
    ap.add_argument("--env-file", default=".env", help="dotenv file to read (default ./.env)")
    ap.add_argument("--timeout", type=float, default=10.0, help="socket timeout in seconds")
    args = ap.parse_args()

    # 1. Python
    if sys.version_info >= (3, 11):
        report("OK", "Python", sys.version.split()[0])
    else:
        report("FAIL", "Python", f"{sys.version.split()[0]} < 3.11 (mcpylib needs 3.11+)")

    # 2. Package
    try:
        import importlib.metadata as md
        version = md.version("mcpylib")
        import mcpylib  # noqa: F401
        from mcpylib import MCPyLib, AuthenticationError, CommandError, MCPyLibError
    except Exception as exc:  # PackageNotFoundError or ImportError
        report("FAIL", "mcpylib package", f"not importable ({exc}); run: pip install mcpylib")
        return summarize()
    if parse_version(version) >= MIN_CLIENT:
        report("OK", "mcpylib package", version)
    else:
        report("WARN", "mcpylib package",
               f"{version} < 1.2.0: edit() uses the slower legacy format; "
               "upgrade with: pip install -U mcpylib")

    # 3. Settings
    load_env_file(args.env_file)
    host = args.host or first_env("MCPYLIB_HOST", "SERVER_IP") or "127.0.0.1"
    port = args.port or int(first_env("MCPYLIB_PORT", "SERVER_PORT") or 65535)
    token = args.token or first_env("MCPYLIB_TOKEN", "SERVER_TOKEN") or ""
    report("OK", "settings", f"host={host} port={port} token={'set' if token else 'MISSING'}")
    if not token:
        report("FAIL", "token",
               "set MCPYLIB_TOKEN (run '/mcpylib token' in the server console, or read "
               "security.token in plugins/MCPyLib/config.yml)")
        return summarize()

    # 4. Raw TCP reachability (separates network problems from auth problems)
    try:
        with socket.create_connection((host, port), timeout=args.timeout):
            pass
        report("OK", "TCP connect", f"{host}:{port} accepts connections")
    except OSError as exc:
        report("FAIL", "TCP connect",
               f"{host}:{port} unreachable ({exc}). Is the server running with the MCPyLib "
               "plugin enabled ('/plugins')? Is server.port right? Is a firewall blocking it?")
        return summarize()

    # 5. Authenticated read
    mc = MCPyLib(ip=host, port=port, token=token, timeout=args.timeout)
    try:
        info = mc.list()
        names = [p.get("name") for p in info.get("players", [])]
        report("OK", "token accepted",
               f"{info.get('online_count')}/{info.get('max_players')} online: {', '.join(names) or '-'}")
    except AuthenticationError as exc:
        report("FAIL", "token accepted",
               f"{exc}. Copy the token again from '/mcpylib token'. If you edited "
               "config.yml, restart the server ('/mcpylib reload' keeps the old token).")
        mc.close()
        return summarize()
    except (MCPyLibError, OSError) as exc:
        report("FAIL", "authenticated request",
               f"{type(exc).__name__}: {exc}. 'Server busy' means every plugin connection "
               "slot is taken (close other clients or raise server.max-connections); a "
               "timeout means the server's main thread is frozen or very busy.")
        mc.close()
        return summarize()

    # 6. Bulk-edit compatibility probe: an all-None 1x1x1 edit places nothing.
    try:
        placed = mc.edit(0, 0, 0, [[[None]]])
        report("OK", "edit() format", f"plugin accepted the client's bulkEdit format (placed {placed})")
    except CommandError as exc:
        if "Missing parameters" in str(exc):
            report("WARN", "edit() format",
                   "plugin is older than the client; update the server to "
                   "MCPyLib-Plugin-1.2.0.jar (edit() will fail until then)")
        else:
            report("WARN", "edit() format", str(exc))

    # 7. Optional player lookup
    if args.player:
        try:
            x, y, z = mc.getPos(args.player)
            report("OK", f"player {args.player}", f"feet at ({x}, {y}, {z})")
            uuid = next((p.get("uuid") for p in info.get("players", [])
                         if str(p.get("name", "")).lower() == args.player.lower()), None)
            if uuid:
                world = mc.getEntityStatus(uuid).get("world", "?")
                if world.endswith(("_nether", "_the_end")):
                    report("WARN", "player world",
                           f"'{world}': block calls always target the main overworld, "
                           "so this player's coordinates point elsewhere there")
                else:
                    report("OK", "player world", world)
            below = mc.getblock(x, y - 1, z)
            report("OK", "block below feet", below)
        except CommandError as exc:
            report("FAIL", f"player {args.player}", f"{exc} (is the player online?)")
        except (MCPyLibError, OSError) as exc:
            report("FAIL", f"player {args.player}", f"{type(exc).__name__}: {exc}")

    mc.close()
    return summarize()


def summarize() -> int:
    failed = [r for r in results if r[0] == "FAIL"]
    warned = [r for r in results if r[0] == "WARN"]
    print()
    if failed:
        print(f"NOT READY: {len(failed)} failed, {len(warned)} warning(s).")
        return 1
    print(f"READY ({len(warned)} warning(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
