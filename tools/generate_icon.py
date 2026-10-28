#!/usr/bin/env python3
"""Export 32x32 tiles from Blue Sky's atlas using Tile Explorer indices."""

from __future__ import annotations

import argparse
from pathlib import Path

from generate_frame import ATLAS_COLUMNS, TILE_SIZE, read_indexed_png, write_rgba_png


def export_tile(
    atlas: list[tuple[int, int, int, int]],
    atlas_width: int,
    tile_index: int,
    destination: Path,
) -> None:
    cols = atlas_width // TILE_SIZE
    x0 = (tile_index % cols) * TILE_SIZE
    y0 = (tile_index // cols) * TILE_SIZE
    tile: list[tuple[int, int, int, int]] = []
    for y in range(TILE_SIZE):
        start = (y0 + y) * atlas_width + x0
        tile.extend(atlas[start : start + TILE_SIZE])
    write_rgba_png(destination, TILE_SIZE, TILE_SIZE, tile)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--atlas",
        type=Path,
        default=Path("../dungeon_game/data/assets/atlas.png"),
        help="Path to data/assets/atlas.png",
    )
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--tile", type=int, help="Tile Explorer index, 0–207")
    choice.add_argument("--all", action="store_true", help="Export every 32x32 atlas tile")
    parser.add_argument("--output", type=Path, help="Output path for --tile (defaults to img/icons/tile-NNN.png)")
    parser.add_argument("--output-dir", type=Path, default=Path("img/icons"), help="Folder used by --all")
    args = parser.parse_args()

    width, height, atlas = read_indexed_png(args.atlas)
    if width % TILE_SIZE or width // TILE_SIZE != ATLAS_COLUMNS or height % TILE_SIZE:
        parser.error("Expected Blue Sky's atlas arranged as 32x32 tiles in 8 columns")
    count = (width // TILE_SIZE) * (height // TILE_SIZE)

    if args.tile is not None:
        if not 0 <= args.tile < count:
            parser.error(f"Tile index must be between 0 and {count - 1}")
        output = args.output or args.output_dir / f"tile-{args.tile:03}.png"
        export_tile(atlas, width, args.tile, output)
        print(f"Exported atlas tile {args.tile} to {output}")
        return

    for index in range(count):
        export_tile(atlas, width, index, args.output_dir / f"tile-{index:03}.png")
    print(f"Exported {count} 32x32 tiles to {args.output_dir}")


if __name__ == "__main__":
    main()
