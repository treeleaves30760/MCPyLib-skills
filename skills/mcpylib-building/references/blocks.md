# Blocks for MCPyLib builds

Block ids are modern vanilla ids, the Bukkit material names in lower case. The
`minecraft:` prefix is optional. Reads return `minecraft:<id>` without states.

## Contents

- [Palettes by purpose](#palettes-by-purpose)
- [Ids that trip people up](#ids-that-trip-people-up)
- [States you can set](#states-you-can-set)
- [Blocks that misbehave without physics](#blocks-that-misbehave-without-physics)
- [Lighting](#lighting)
- [Colour families for pixel art](#colour-families-for-pixel-art)

## Palettes by purpose

| Purpose | Good choices |
|---|---|
| Walls (wood) | oak_planks, spruce_planks, birch_planks, dark_oak_planks, stripped_oak_log, oak_log (corners) |
| Walls (stone) | stone_bricks, cracked_stone_bricks, mossy_stone_bricks, cobblestone, deepslate_bricks, polished_andesite, smooth_stone |
| Modern | white_concrete, light_gray_concrete, smooth_quartz, quartz_block, polished_blackstone, glass |
| Roofs | spruce_stairs + spruce_planks, dark_oak_stairs + dark_oak_planks, deepslate_tile_stairs + deepslate_tiles, brick_stairs + bricks |
| Floors | oak_planks, polished_andesite, smooth_stone, stone_bricks, white_wool (carpet-like) |
| Windows | glass, white_stained_glass, tinted_glass (full blocks; panes won't connect) |
| Light (place with setblock) | torch, lantern (needs a block below), glowstone, sea_lantern, shroomlight, jack_o_lantern |
| Foliage that never decays | moss_block, green_wool, lime_terracotta, azalea (plant), flowering_azalea |
| Paths and roads | dirt_path, gravel (floats if unsupported), cobblestone, stone_bricks |
| Markers and previews | red_wool, lime_wool, yellow_concrete (easy to see, easy to undo) |

## Ids that trip people up

- `short_grass`, not `grass`. The id changed in 1.20.3; `grass_block` is the block
  with dirt underneath.
- `dirt_path`, not `grass_path`.
- `bricks` is the block; `brick` is the item. `oak_sign` and `oak_wall_sign`, not
  `sign`.
- There are no generic ids such as `planks`, `log`, `wool` or `concrete`: pick a
  colour or wood type, such as `oak_planks` or `white_wool`.
- Items are not blocks: `setblock`, `fill` and `edit()` reject `"diamond"` with
  `Invalid block type: diamond (this is an item, not a placeable block)`.
  `"diamond_block"` works.
- Air comes in three types: `air`, `cave_air`, `void_air`. Treat all three as empty
  when reading.

## States you can set

`block_state` takes any vanilla property of the block, with vanilla values written
as strings. A key the block doesn't have fails with `Unsupported property`.
Bukkit enum names still work for `facing`, `rotation`, `axis`, `half`, `shape`,
`waterlogged`, `open` and `powered`.

| Key | Values | Used by |
|---|---|---|
| facing | north, south, east, west (up, down for some) | stairs, furnaces, chests, ladders, wall signs, wall torches, observers, trapdoors, gates, doors, beds |
| rotation | 0-15 (0 = south, 4 = west, 8 = north, 12 = east), or names such as south_south_west | standing signs, banners, heads |
| axis | x, y, z | logs, pillars, basalt, chains |
| half | top, bottom (stairs, trapdoors); lower, upper (doors, tall plants) | |
| shape | straight, inner_left, inner_right, outer_left, outer_right | stairs |
| type | bottom, top, double (slabs); single, left, right (chests) | slabs, chests |
| part | foot, head | beds |
| hinge | left, right | doors |
| lit | true, false | furnaces, campfires, redstone lamps, candles |
| persistent | true, false | leaves (true = never decays) |
| layers | 1-8 | snow |
| age | 0-7 for most crops | wheat, carrots, potatoes, ... |
| hanging | true, false | lanterns |
| waterlogged | true, false | slabs, stairs, fences, lanterns... |
| open | true, false | doors, trapdoors, fence gates |
| powered | true, false | levers, buttons, pressure plates... |

Two-block blocks in `edit()` (plugin 1.2.1): give one cell, the door's lower half or
the bed's foot (`{"block": "red_bed", "block_state": {"facing": "south"}}` or just
`"red_bed"`), and the other half is added: one block up for doors and tall plants,
one block toward `facing` for a bed's head. It replaces whatever is there, unless
the array sets that position itself. With both halves in the array, any order works.
A double chest needs two cells, `type: left` and `type: right`, with the same
`facing`.

NBT: only `CustomName` (containers, plain text) and `Text1`..`Text4` (sign front
lines) are applied. Chest contents (`Items`) are ignored.

## Blocks that misbehave without physics

`edit()` and `fill()` write without block updates, dict cells in `edit()` included.
`setblock()` runs physics.

| Block type | What happens with edit/fill | Workaround |
|---|---|---|
| Sand, red_sand, gravel, concrete powder, anvils | Float until disturbed, then fall | Put solid blocks under them, or use sandstone or smooth stone |
| Water, lava | Placed as still source blocks; flow starts on the next nearby update | Enclose them fully, or keep them away from open edges |
| Fences, glass panes, iron bars, walls | Show as unconnected posts | Use full blocks (glass, stone walls built from bricks) |
| Redstone dust, repeaters, pistons | Don't update or power | Place redstone by hand, or with setblock in order, and test it |
| Leaves | Plain ids keep distance=7, persistent=false, and decay over time | Set `persistent: true` |
| Torches, lanterns, flowers, carpets, rails, buttons | Need support; fine in edit(), but pop off in setblock() without support | Place them after their support block exists |
| Doors, beds, tall flowers | Work in edit() on plugin 1.2.1 (other half added). fill() places single halves. With setblock() the first half breaks unless placed in order | Use edit(); with setblock(), place the door's upper half or the bed's head first |

## Lighting

String cells in `edit()` are written without lighting recalculation:
- New light sources may not shine.
- Big roofs can leave odd bright or dark patches until a block update nearby or a
  chunk reload fixes them.

Place light sources with `setblock()` after the bulk edit. buildkit does this for
cells set with `defer=True`.

## Colour families for pixel art

`pixel_art.py` contains approximate average RGB values for the 16 concrete colours,
16 wool colours and 17 terracotta colours. Concrete is flat and saturated, wool is
lighter and brighter, and terracotta covers skin tones and earth tones. For
grayscale, the gradient white_concrete → light_gray_concrete → gray_concrete →
black_concrete works, with extra steps from the wool and terracotta greys.
