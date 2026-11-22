---
name: mcpylib-building
description: Procedural Minecraft building with MCPyLib in pure Python (no numpy). Generates spheres, domes, cylinders, cones, pyramids, tori, houses, towers, pixel art from images and heightmap or noise terrain as rectangular block arrays, then places them with edit() in chunk-sized batches with a dry-run plan, overwrite protection and an undo file. Use when the user asks to build, generate or draw something in a Minecraft world with code, such as shapes, buildings, statues, image or pixel art, landscapes, mazes or other large structures, or wants faster bulk placement than setblock loops. Builds on the mcpylib skill for connection and API details.
license: MCPyLib Non-Commercial License with Commercial Exception. Complete terms in LICENSE.txt
compatibility: Requires Python 3.11+, the mcpylib package (1.2.2 recommended) and a Paper/Spigot 26.1+ server with the MCPyLib plugin. Pillow is optional (non-PNG images).
metadata:
  author: treeleaves30760
  version: "1.1.0"
  mcpylib-version: "1.2.2"
---

# Procedural building with MCPyLib

Generate block layouts in Python, then write them in a few big `edit()` calls.
For connection setup, API details and general safety rules, use the **mcpylib**
skill. Connection settings come from `MCPYLIB_HOST`, `MCPYLIB_PORT` and
`MCPYLIB_TOKEN` (environment or `./.env`).

## Workflow

Copy this checklist and tick it off:

```
- [ ] 1. Setup works: mcpylib skill -> scripts/check_setup.py --player NAME
- [ ] 2. Location chosen: --player NAME (front faces the player) or --at X Y Z
- [ ] 3. Dry run: run the script WITHOUT --apply and read the plan
- [ ] 4. Show the plan to the user (box, cells, "existing non-air blocks that would be replaced")
- [ ] 5. If anything would be replaced, get explicit confirmation -> add --allow-overwrite
- [ ] 6. Re-run with --apply; keep the printed undo command
- [ ] 7. Ask the user to check it in game; undo with scripts/undo.py if needed
```

All scripts are dry runs by default. With `--apply` they still **refuse** to replace
non-air blocks unless `--allow-overwrite` is given, and they write
`mcpylib-undo/undo-<label>-<time>.jsonl` before changing anything. They only write
cells that actually change, so existing blocks that already match keep their states.

## Bundled scripts

Run these from this skill's `scripts/` directory (they import `buildkit.py`):

| Script | Builds | Example |
|---|---|---|
| `scripts/shapes.py` | sphere, dome, cylinder, cone, pyramid (optional stairs), torus, box | `python shapes.py dome --radius 10 --block glass --hollow --player Steve` |
| `scripts/buildings.py` | `house` (gable roof, windows, door, torches), `tower` (battlements or cone roof, ladder) | `python buildings.py house --width 9 --depth 7 --player Steve` |
| `scripts/pixel_art.py` | image to wall or floor art (concrete, wool, terracotta or full palette, optional dithering) | `python pixel_art.py logo.png --width 64 --player Steve` |
| `scripts/terrain.py` | noise or heightmap landscape with soil layers, beaches, lakes and snow | `python terrain.py --at 1000 -500 --size 96 96 --survey` |
| `scripts/undo.py` | restores an undo file (skips cells players changed since) | `python undo.py mcpylib-undo/undo-house-....jsonl --apply` |

Common flags:
- `--at X Y Z`: centre of the footprint at base level.
- `--player NAME`: build `--gap` blocks in front of the player, front facing them.
- `--front north|east|south|west`: which way the front faces.
- `--apply`, `--allow-overwrite`: see the workflow above.
- `--max-cells`: cells per call (default 65,536).
- `--host`, `--port`, `--timeout`: connection overrides.

`terrain.py` instead takes `--at X Z` (the north-west corner) and needs
`--allow-overwrite` to apply, because it rewrites whole columns.

Run any script with `--help` for its options. With `--player`, the scripts refuse if
the player is in the Nether or End, because MCPyLib always builds in the main
overworld.

## Writing your own generator

Prefer `buildkit` over raw arrays. It handles rotation, Y clipping, the
read-before-write survey, batching, undo and deferred light sources:

```python
import argparse
import buildkit as bk

ap = argparse.ArgumentParser()
ap.add_argument("--steps", type=int, default=10)
bk.add_common_args(ap)
args = ap.parse_args()

grid = bk.Grid()                      # local coords: footprint centred, base y = 0, front = +Z
n = args.steps
for i in range(n):                    # a straight staircase climbing toward -Z (away from the front)
    if i:
        grid.box(0, 0, -i, 0, i - 1, -i, "stone_bricks")      # solid support under each step
    grid.set(0, i, -i, bk.stair("stone_brick_stairs", "north"))
grid.box(0, 0, -n, 0, n - 1, -n, "stone_bricks")               # landing column at the top
grid.set(0, n, -n, "lantern", defer=True)  # light source on solid ground, placed with setblock()

with bk.connect(args) as mc:
    anchor, turns = bk.resolve_placement(mc, args, grid)
    raise SystemExit(bk.execute(mc, bk.Build.from_grid(grid, anchor, turns, "stairs"), args))
```

Save it next to `buildkit.py` and run it like the other scripts. For a one-off build
without buildkit, follow the core skill's rules:
- Arrays are rectangular `blocks[dx][dy][dz]`.
- Use `None` for cells you don't touch.
- Keep each call to about 65,536 cells, split at chunk borders.
- `getblocks` the box first and report what would be replaced.

## Design rules that matter with MCPyLib 1.2.2

- **States**: `block_state` takes any vanilla property with vanilla values, such as
  slab `type: top`/`double`, leaves `persistent: true` (otherwise they decay),
  lantern `hanging`, `lit`, sign `rotation: 0-15`. A key the block doesn't have
  raises `Unsupported property`.
- **Doors and beds**: in `edit()`, give one cell (door's lower half, bed's foot, or
  just `"red_bed"`) and the plugin adds the other half, replacing whatever is there
  unless the array sets that cell. Giving both halves yourself keeps them in the
  survey and undo file. With `setblock()`, place the upper half or the head first.
- **Stairs face their full side**: `facing` is where the tall back of the step is,
  so a slope rises toward its `facing`. On a gable roof, the south slope uses
  `facing: north`. `bk.stair()` builds these cells, and rotation remaps them.
- **No physics or updates in `edit()`**, dict cells included: use glass blocks
  rather than panes, and walls of solid blocks rather than fences, which won't
  connect. Gravel and sand float until disturbed, and placed water stays still.
  Place torches, lanterns and glowstone with `defer=True` (setblock) so their light
  updates.
- **Main overworld only**, Y -64..319. Cells outside are dropped, and the plan
  reports them.
- **Size**: expect about 0.05 s per call plus about 150,000 cells/s. A 64x64 pixel
  art is one call; a 256x256 terrain is about 300 calls (around a minute). Warn the
  user before anything above about 100,000 changed cells, and make sure they are
  near the area so the chunks are loaded.

## References

- [references/recipes.md](references/recipes.md): shape formulas, the local frame and
  rotation, roof and tower anatomy, pixel-art colour matching, terrain noise, mazes,
  and a raw-array pattern without buildkit.
- [references/blocks.md](references/blocks.md): block palettes by purpose, renamed
  ids, which blocks misbehave without physics, multi-block pitfalls, lighting.
