# Building recipes

## Contents

- [Local frame, anchors and rotation](#local-frame-anchors-and-rotation)
- [Voxel shape formulas](#voxel-shape-formulas)
- [Stairs, slopes and roofs](#stairs-slopes-and-roofs)
- [House and tower anatomy](#house-and-tower-anatomy)
- [Pixel art](#pixel-art)
- [Terrain](#terrain)
- [Mazes and other grids](#mazes-and-other-grids)
- [Raw-array pattern without buildkit](#raw-array-pattern-without-buildkit)

## Local frame, anchors and rotation

- Minecraft axes: +X east, +Z south, +Y up.
- Generators work in a **local frame**:
  - the footprint is centred on x = 0, z = 0
  - the base is at y = 0
  - the front (doorway, picture face) faces **local +Z**
- `--at X Y Z` puts local (0, 0, 0) at world (X, Y, Z).
- `--player NAME` reads the player's yaw from `getEntityPos(uuid)["yaw"]` and snaps
  it to a cardinal facing F:
  ```python
  ("south", "west", "north", "east")[round(yaw / 90) % 4]
  ```
  It then places the build so the front faces the player, with `gap` empty blocks
  between them:
  ```python
  anchor = player + F * (gap + 1 + front_extent)
  ```
- **Rotation**:
  - One clockwise quarter turn, seen from above, maps `(x, z) -> (-z, x)`.
  - It also maps `facing` north->east->south->west, the 16 `rotation` names by four
    steps, and swaps `axis` x<->z.
  - `turns_for_front(front) = (index(front) - index("south")) % 4`, using the order
    north, east, south, west.
- A player's facing vector from yaw: `dx = -sin(yaw)`, `dz = cos(yaw)`.

## Voxel shape formulas

Use `r + 0.5` as the cut-off radius. It avoids single-block spikes at the poles and
gives the round outlines players expect.

| Shape | Cell (x, y, z) is filled when |
|---|---|
| Sphere, radius r, centre (0, r, 0) | x² + (y−r)² + z² ≤ (r+0.5)² |
| Hollow shell, thickness t | the above, and not x² + (y−r)² + z² ≤ (r−t+0.5)² |
| Dome | sphere centred at (0, 0, 0), y ≥ 0 |
| Cylinder, radius r, height h | x² + z² ≤ (r+0.5)², 0 ≤ y < h |
| Cone | x² + z² ≤ (r·(1 − y/h) + 0.5)² |
| Torus, ring R, tube a | (√(x²+z²) − R)² + (y−a)² ≤ (a+0.5)² |
| Stepped pyramid, base b | level L is the square \|x\|, \|z\| ≤ (b−1)/2 − L |
| Ellipsoid, radii a, b, c | (x/a)² + (y/b)² + (z/c)² ≤ 1 (use a+0.5, b+0.5, c+0.5) |
| Arch, span s, rise h | 0 ≤ y ≤ h·√(1 − (2x/s)²), shell 1 thick |

Hollow interiors: to clear old blocks, write `"air"` inside the shell. To keep
whatever is there, leave those cells out (`None`).

## Stairs, slopes and roofs

- A stair's `facing` is the side with the full-height back, so it **rises toward
  `facing`**.
- `half: "top"` gives an upside-down stair, which is useful for eaves and arches.
  `shape` can force corners, such as `outer_left`, but straight stairs plus
  full-block corners look clean and avoid surprises.
- **Gable roof, ridge along X, overhang 1**:
  - Layer i sits at y = wall_top + i.
  - The front slope runs along z = front_wall + 1 − i, with `facing: north`.
  - The back slope runs along z = back_wall − 1 + i, with `facing: south`.
  - Fill the gable ends (x = left and right walls) between the two slopes from layer 1
    upwards.
  - Stop when the slopes meet. With an odd span, put a full-block ridge on the last
    row.
- **Pyramid with smooth sides**: on each edge, use a stair facing toward the centre.
  On the east edge that is `facing: west`. Use full blocks at the corners.
- Roof materials come in pairs: `spruce_stairs` with `spruce_planks`,
  `dark_oak_stairs` with `dark_oak_planks`, `stone_brick_stairs` with `stone_bricks`,
  `deepslate_tile_stairs` with `deepslate_tiles`. The full block's id is not always
  the stair id minus `_stairs`; for example, the full block for `stone_brick_stairs`
  is `stone_bricks`.

## House and tower anatomy

`buildings.py house` builds, in local coordinates:
- floor at y = 0
- walls at y = 1..H, with logs at the corners
- the interior cleared to air
- an oak door at the front centre, both halves given (`--door none` leaves a 1x2
  opening)
- glass windows every third block at y = 2 (and y = 3 when H ≥ 4)
- a gable roof with an attic cleared to air
- four torches, placed last with setblock

Extensions that work with plugin 1.2.1:
- Interior walls: `grid.box(...)` with planks.
- A second floor: a full plank layer, plus a ladder with `facing` pointing away from
  its wall.
- Chimneys: a column of bricks.
- Signs: `{"block": "oak_wall_sign", "block_state": {"facing": "south"}, "nbt": {"Text1": "Welcome"}}`
  on a wall.
- Beds: one cell `{"block": "red_bed", "block_state": {"facing": "north"}}` is the
  foot; the head is added one block toward `facing`.
- Slab roofs or floors: `{"block": "oak_slab", "block_state": {"type": "top"}}`.
- Trees: leaves with `{"persistent": "true"}`, so they don't decay.

`buildings.py tower` builds:
- a ring wall where cells satisfy r−0.5 < d ≤ r+0.5, on a solid disk floor
- a spruce door at +Z
- windows every four levels
- a platform at y = H+1
- a ladder on the back wall, `facing: south`, passing through the platform
- either checkerboard battlements or a hollow cone roof

## Pixel art

1. Load the image: Pillow if it is installed, otherwise the built-in `pngdecode`.
2. Box-filter it to the target width, keeping the aspect ratio. Weight colours by
   alpha so transparent edges don't darken the result.
3. Match each pixel to the nearest block colour using the **redmean** distance:
   ```
   rm = (r1 + r2) / 2
   d = (2 + rm/256)·dr² + 4·dg² + (2 + (255 − rm)/256)·db²
   ```
   Cache lookups by quantised colour.
4. Optional **Floyd-Steinberg dithering**: spread the error
   `7/16 →, 3/16 ↙, 5/16 ↓, 1/16 ↘`. It helps photos and hurts flat logos.
5. Map pixel (u, v) to local coordinates:
   - wall: `(u − W/2, H−1−v, 0)`
   - floor: `(u − W/2, 0, v − H/2)`

Palettes:
- `concrete`: flat colours.
- `wool`: brighter colours.
- `terracotta`: earthy tones.
- `full`: all 49 of the above.

The colours are approximate texture averages, so preview a small version first. A
64-block-wide wall is 64 × ~40 cells, which fits in one `edit()` call.

Very saturated colours have no close block. Pure `#FF0000` matches
`orange_concrete` with the concrete palette, because `red_concrete` is a dark red;
the wool and full palettes give `red_wool`. Pick the palette that fits the image, or
tone the image down before converting.

Map art, which is viewed on an in-game map, is a different technique that uses map
colours and height shading. The MCPyLib_Map_Art project implements it.

## Terrain

- Height source, normalised to n ∈ [0, 1]:
  - **Value-noise fBm**: hash the integer lattice, use smoothstep interpolation, and
    sum 4 octaves with gain 0.5 and lacunarity 2.
  - **Grayscale heightmap**: luminance = 0.299r + 0.587g + 0.114b.
- Surface height: `h = base_y + round((n − 0.5) · 2 · amplitude)`.
- Edge blend: `t = smoothstep(min(distance to edge / blend, 1))`, then
  `n = 0.5 + (n − 0.5)·t`, so the border sits at base_y.
- Column rules (y relative to the surface h):

  | Cells | Block |
  |---|---|
  | Below h − 3 | stone |
  | h − 3 .. h − 1 | dirt, or sand on shores |
  | h | grass_block; snow_block above the snow line; stone where the slope ≥ 4; gravel under water; sand on shores |
  | h + 1 .. water level | water |
  | Above that, up to `clear_above` | air |

- Write chunk-aligned tiles of 16 × 16 columns. Each tile spans only its own Y range,
  split further if it exceeds `--max-cells`. Stream the tiles instead of keeping the
  whole volume in memory.
- Lakes: keep the water level below base_y, so the blended edges (at base_y) hold
  the water in. Water placed by `edit()` is still, and a block update at an open
  edge makes it flow.

## Mazes and other grids

Generate a 2-D boolean grid, then extrude it. For each wall column, fill
`blocks[x][y][z]` for y in 0..height−1 with the wall block, and leave every other
cell `None`. Send the result as one `edit()` per ≤ 65,536 cells.

The MCPyLib repo's `examples/buildings/build_maze.py` has a DFS maze generator with
configurable corridor and wall widths. Wrap it with buildkit to get the survey and
undo.

Common grid generators:
- recursive backtracker (long corridors)
- Prim (branchy)
- cellular automata (caves)
- Wave Function Collapse (tiles)

## Raw-array pattern without buildkit

```python
import math
from mcpylib import MCPyLib

AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}

def place_cells(mc: MCPyLib, cells: dict, max_cells: int = 65536, apply: bool = False) -> int:
    """cells: {(x, y, z): "block_id" or {...}} in world coordinates."""
    xs, ys, zs = zip(*cells)
    x1, y1, z1, x2, y2, z2 = min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)
    sx, sy, sz = x2 - x1 + 1, y2 - y1 + 1, z2 - z1 + 1
    assert sx * sy * sz <= max_cells, "split the job into chunk-aligned pieces"
    current = mc.getblocks(x1, y1, z1, x2, y2, z2)          # read before write
    replaced = sum(1 for (x, y, z) in cells if current[x - x1][y - y1][z - z1] not in AIR)
    print(f"{len(cells)} cells, {replaced} existing non-air blocks would be replaced")
    if not apply:
        return 0
    blocks = [[[None] * sz for _ in range(sy)] for _ in range(sx)]  # None = untouched
    for (x, y, z), cell in cells.items():
        blocks[x - x1][y - y1][z - z1] = cell
    return mc.edit(x1, y1, z1, blocks)

# ring of glass, radius 6, around (100, 64, 200)
ring = {(100 + dx, 64, 200 + dz): "glass"
        for dx in range(-7, 8) for dz in range(-7, 8)
        if 5.5 < math.hypot(dx, dz) <= 6.5}
```
