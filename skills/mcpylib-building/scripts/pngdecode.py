"""Minimal PNG reader in pure Python (zlib only), used by pixel_art.py.

read_png(path) -> (width, height, rows), where rows[y][x] = (r, g, b, a).

Supports non-interlaced PNGs of every colour type (grayscale, RGB, palette,
grayscale+alpha, RGBA) with bit depths 1-16, plus tRNS transparency.
Interlaced (Adam7) files raise ValueError. Re-save them without interlacing,
or install Pillow, which pixel_art.py prefers when it is available.
"""
from __future__ import annotations

import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(line: bytearray, prev: bytearray, ftype: int, bpp: int) -> None:
    n = len(line)
    if ftype == 0:
        return
    if ftype == 1:
        for i in range(bpp, n):
            line[i] = (line[i] + line[i - bpp]) & 0xFF
    elif ftype == 2:
        for i in range(n):
            line[i] = (line[i] + prev[i]) & 0xFF
    elif ftype == 3:
        for i in range(n):
            left = line[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
    elif ftype == 4:
        for i in range(n):
            left = line[i - bpp] if i >= bpp else 0
            up_left = prev[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + _paeth(left, prev[i], up_left)) & 0xFF
    else:
        raise ValueError(f"bad PNG filter type {ftype}")


def _samples(line: bytearray, width: int, channels: int, depth: int) -> list[int]:
    """Unpack one scanline into width*channels integer samples."""
    count = width * channels
    if depth == 8:
        return list(line[:count])
    if depth == 16:
        return [line[2 * i] for i in range(count)]  # keep the high byte
    out, mask, per_byte = [], (1 << depth) - 1, 8 // depth
    for byte in line:
        for k in range(per_byte):
            out.append((byte >> (8 - depth * (k + 1))) & mask)
    return out[:count]


def read_png(path: str):
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:8] != SIGNATURE:
        raise ValueError(f"{path} is not a PNG file")
    pos, idat, palette, trns, header = 8, [], None, None, None
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            header = struct.unpack(">IIBBBBB", chunk)
        elif ctype == b"PLTE":
            palette = [tuple(chunk[i:i + 3]) for i in range(0, len(chunk), 3)]
        elif ctype == b"tRNS":
            trns = chunk
        elif ctype == b"IDAT":
            idat.append(chunk)
        elif ctype == b"IEND":
            break
    if header is None:
        raise ValueError("PNG has no IHDR chunk")
    width, height, depth, color, _comp, _filter, interlace = header
    if interlace:
        raise ValueError("interlaced PNG is not supported; re-save without interlacing or install Pillow")
    if color not in CHANNELS:
        raise ValueError(f"unsupported PNG colour type {color}")
    channels = CHANNELS[color]
    bits = channels * depth
    bpp = max(1, bits // 8)
    stride = (width * bits + 7) // 8
    raw = zlib.decompress(b"".join(idat))
    scale = 255 // ((1 << depth) - 1) if color in (0, 4) and depth < 8 else 1
    # tRNS colour keys, compared against unpacked samples (16-bit keeps the high byte).
    gray_key = rgb_key = None
    if trns and color == 0 and len(trns) >= 2:
        gray_key = trns[0] if depth == 16 else (trns[0] << 8 | trns[1])
    if trns and color == 2 and len(trns) >= 6:
        rgb_key = (trns[0], trns[2], trns[4]) if depth == 16 else (trns[1], trns[3], trns[5])

    rows, prev, i = [], bytearray(stride), 0
    for _y in range(height):
        ftype = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        _unfilter(line, prev, ftype, bpp)
        prev = line
        s = _samples(line, width, channels, depth)
        row = []
        for x in range(width):
            if color == 0:
                v = s[x] * scale
                row.append((v, v, v, 0 if s[x] == gray_key else 255))
            elif color == 2:
                r, g, b = s[3 * x:3 * x + 3]
                row.append((r, g, b, 0 if (r, g, b) == rgb_key else 255))
            elif color == 3:
                idx = s[x]
                r, g, b = palette[idx] if palette and idx < len(palette) else (0, 0, 0)
                alpha = trns[idx] if trns and idx < len(trns) else 255
                row.append((r, g, b, alpha))
            elif color == 4:
                v, a = s[2 * x] * scale, s[2 * x + 1] * scale
                row.append((v, v, v, a))
            else:
                row.append(tuple(s[4 * x:4 * x + 4]))
        rows.append(row)
    return width, height, rows
