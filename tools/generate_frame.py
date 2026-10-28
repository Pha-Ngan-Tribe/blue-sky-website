#!/usr/bin/env python3
"""Generate a transparent UI frame from Blue Sky's 32x32 atlas frame tiles.

The perimeter assembly follows core/frame.odin: fixed corners, decorative
joints next to them, then repeated 8x8 edge tiles. The output size is rounded
up to the game's 8px sub-tile grid.

Uses only the Python standard library. Supports the game's indexed PNG atlas.
"""

from __future__ import annotations

import argparse
import math
import struct
import zlib
from pathlib import Path


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
TILE_SIZE = 32
SUB_TILE = 8
ATLAS_COLUMNS = 8
FRAME_FIRST_TILE = 200


def read_indexed_png(path: Path) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError(f"Not a PNG file: {path}")

    offset = len(PNG_SIGNATURE)
    width = height = bit_depth = color_type = interlace = None
    palette: bytes | None = None
    alpha_table = b""
    compressed = bytearray()
    while offset < len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        offset += length + 12
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
        elif kind == b"PLTE":
            palette = payload
        elif kind == b"tRNS":
            alpha_table = payload
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break

    if color_type != 3 or bit_depth not in (1, 2, 4, 8) or interlace != 0:
        raise ValueError("Atlas must be a non-interlaced indexed PNG")
    if palette is None or width is None or height is None or bit_depth is None:
        raise ValueError("PNG is missing required image data")

    raw = zlib.decompress(compressed)
    row_bytes = (width * bit_depth + 7) // 8
    bpp = 1
    rows: list[bytes] = []
    previous = bytearray(row_bytes)
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        source = raw[cursor : cursor + row_bytes]
        cursor += row_bytes
        decoded = bytearray(row_bytes)
        for i, value in enumerate(source):
            left = decoded[i - bpp] if i >= bpp else 0
            up = previous[i]
            upper_left = previous[i - bpp] if i >= bpp else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = up
            elif filter_type == 3:
                predictor = (left + up) // 2
            elif filter_type == 4:
                p = left + up - upper_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upper_left)
                predictor = left if pa <= pb and pa <= pc else up if pb <= pc else upper_left
            else:
                raise ValueError(f"Unsupported PNG filter: {filter_type}")
            decoded[i] = (value + predictor) & 0xFF
        rows.append(bytes(decoded))
        previous = decoded

    rgba: list[tuple[int, int, int, int]] = []
    mask = (1 << bit_depth) - 1
    for y in range(height):
        row = rows[y]
        for x in range(width):
            bit = x * bit_depth
            index = (row[bit // 8] >> (8 - bit_depth - bit % 8)) & mask
            p = index * 3
            rgba.append(
                (palette[p], palette[p + 1], palette[p + 2], alpha_table[index] if index < len(alpha_table) else 255)
            )
    return width, height, rgba


def write_rgba_png(path: Path, width: int, height: int, pixels: list[tuple[int, int, int, int]]) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    scanlines = bytearray()
    for y in range(height):
        scanlines.append(0)  # no per-row filter
        start = y * width
        for r, g, b, a in pixels[start : start + width]:
            scanlines.extend((r, g, b, a))
    payload = PNG_SIGNATURE
    payload += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    payload += chunk(b"IDAT", zlib.compress(bytes(scanlines), 9))
    payload += chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def parse_fill(value: str | None) -> tuple[int, int, int, int] | None:
    if value is None or value.lower() == "transparent":
        return None
    text = value.removeprefix("#")
    if len(text) not in (6, 8):
        raise argparse.ArgumentTypeError("Fill must be #RRGGBB, #RRGGBBAA, or transparent")
    try:
        channels = tuple(int(text[i : i + 2], 16) for i in range(0, len(text), 2))
    except ValueError as error:
        raise argparse.ArgumentTypeError("Fill must be a hexadecimal color") from error
    return channels + (255,) if len(channels) == 3 else channels


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atlas", required=True, type=Path, help="Path to data/assets/atlas.png")
    parser.add_argument("--style", type=int, default=1, choices=range(1, 9), help="Frame style 1–8 (atlas tile 200–207)")
    parser.add_argument("--width", required=True, type=int, help="Requested frame width in pixels")
    parser.add_argument("--height", required=True, type=int, help="Requested frame height in pixels")
    parser.add_argument("--output", required=True, type=Path, help="Output PNG path")
    parser.add_argument("--fill", default="transparent", help="Interior fill color; default: transparent")
    args = parser.parse_args()

    atlas_width, atlas_height, atlas = read_indexed_png(args.atlas)
    if atlas_width % TILE_SIZE or atlas_width // TILE_SIZE != ATLAS_COLUMNS:
        parser.error("Expected an atlas with 8 columns of 32px tiles")
    if args.width < 3 * SUB_TILE or args.height < 3 * SUB_TILE:
        parser.error("Frame width and height must each be at least 24px")

    cols = max(3, math.ceil(args.width / SUB_TILE))
    rows = max(3, math.ceil(args.height / SUB_TILE))
    width, height = cols * SUB_TILE, rows * SUB_TILE
    fill = parse_fill(args.fill)
    blank = fill or (0, 0, 0, 0)
    output = [blank] * (width * height)

    tile = FRAME_FIRST_TILE + args.style - 1
    tile_x = (tile % ATLAS_COLUMNS) * TILE_SIZE
    tile_y = (tile // ATLAS_COLUMNS) * TILE_SIZE

    # Mirrors FRAME_LAYOUT in core/frame.odin: TL, TR, BL, BR.
    corners = ((0, 0), (3, 0), (0, 3), (3, 3))
    for (dst_x, dst_y), (src_x, src_y) in zip(
        ((0, 0), (width - 8, 0), (0, height - 8), (width - 8, height - 8)), corners
    ):
        blit_subtile(output, width, atlas, atlas_width, tile_x, tile_y, src_x, src_y, dst_x, dst_y)

    # Edge IDs match core/frame.odin: top, right, left, bottom.
    lines = ((2, 0), (3, 2), (0, 1), (1, 3))
    joints = ((1, 0), (3, 1), (0, 2), (2, 3))
    for edge, count in ((0, cols), (1, rows), (2, rows), (3, cols)):
        for i in range(1, count - 1):
            source = lines[edge]
            if args.style == 4:
                if edge == 0 and i == 1:
                    source = joints[edge]
                elif edge == 1:
                    source = (3, 2) if i == count - 2 else (3, 1)
                elif edge == 2 and i == count - 2:
                    source = joints[edge]
                elif edge == 3 and (i == 1 or i == count - 2):
                    source = joints[edge]
            elif i == 1 or i == count - 2:
                source = joints[edge]

            if edge == 0:
                dst_x, dst_y = i * 8, 0
            elif edge == 1:
                dst_x, dst_y = width - 8, i * 8
            elif edge == 2:
                dst_x, dst_y = 0, i * 8
            else:
                dst_x, dst_y = i * 8, height - 8
            blit_subtile(output, width, atlas, atlas_width, tile_x, tile_y, *source, dst_x, dst_y)

    write_rgba_png(args.output, width, height, output)
    print(f"Wrote {width}x{height} frame (style {args.style}, tile {tile}) to {args.output}")


def blit_subtile(
    destination: list[tuple[int, int, int, int]],
    destination_width: int,
    atlas: list[tuple[int, int, int, int]],
    atlas_width: int,
    tile_x: int,
    tile_y: int,
    sub_x: int,
    sub_y: int,
    dest_x: int,
    dest_y: int,
) -> None:
    for y in range(SUB_TILE):
        src_start = (tile_y + sub_y * SUB_TILE + y) * atlas_width + tile_x + sub_x * SUB_TILE
        dst_start = (dest_y + y) * destination_width + dest_x
        destination[dst_start : dst_start + SUB_TILE] = atlas[src_start : src_start + SUB_TILE]


if __name__ == "__main__":
    main()
