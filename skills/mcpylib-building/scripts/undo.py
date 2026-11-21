#!/usr/bin/env python3
"""Undo a build made by the mcpylib-building scripts (dry run unless --apply).

  python undo.py mcpylib-undo/undo-house-20261122-101500.jsonl
  python undo.py mcpylib-undo/undo-house-20261122-101500.jsonl --apply

Undo files are JSON Lines: a header, then {"cells": [[x, y, z, previous, placed], ...]}
per batch. A cell is restored only if it still holds what the build placed, so
later edits by players survive; --force restores those cells anyway. Block
types only: orientation, container contents and sign text come back as defaults.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import buildkit as bk


def main() -> int:
    ap = argparse.ArgumentParser(description="Undo an mcpylib-building build.")
    ap.add_argument("undo_file")
    ap.add_argument("--apply", action="store_true", help="actually restore (default: dry run)")
    ap.add_argument("--force", action="store_true", help="also restore cells changed since the build")
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    lines = Path(args.undo_file).read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0]) if lines else {}
    if header.get("format") != bk.UNDO_FORMAT:
        sys.exit(f"{args.undo_file} is not an {bk.UNDO_FORMAT} file.")
    batches = [json.loads(l)["cells"] for l in lines[1:] if l.strip()]
    total = sum(len(b) for b in batches)
    print(f"Undo '{header.get('label')}' from {header.get('created')}: {total:,} cells in {len(batches)} batches")

    restorable = skipped = written = 0
    with bk.connect(args) as mc:
        for rows in batches:
            xs, ys, zs = [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows]
            x1, y1, z1, x2, y2, z2 = min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)
            current = mc.getblocks(x1, y1, z1, x2, y2, z2)
            blocks = [[[None] * (z2 - z1 + 1) for _ in range(y2 - y1 + 1)] for _ in range(x2 - x1 + 1)]
            any_cell = False
            for x, y, z, previous, placed in rows:
                now = current[x - x1][y - y1][z - z1]
                if now == previous:
                    continue  # already restored
                if now != placed and not args.force:
                    skipped += 1
                    continue
                blocks[x - x1][y - y1][z - z1] = previous
                restorable += 1
                any_cell = True
            if args.apply and any_cell:
                written += mc.edit(x1, y1, z1, blocks)
    print(f"Restorable: {restorable:,}; skipped (changed since the build): {skipped:,}")
    if not args.apply:
        print("Dry run. Re-run with --apply to restore" + (" (add --force to include skipped cells)."
                                                         if skipped else "."))
    else:
        print(f"Restored {written:,} cells.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
