#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Sparse tile authority shared by editable coverage and color rasters."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..scene.raster import RasterBounds, RasterExtentPolicy


@dataclass(frozen=True, slots=True)
class SparseRasterTile:
    """Carry one detached nonempty tile in layer-local coordinates."""

    bounds: RasterBounds
    pixels: np.ndarray

    def __post_init__(self) -> None:
        """Detach tile pixels and make the value immutable to consumers."""
        pixels = np.array(self.pixels, copy=True, order="C")
        pixels.flags.writeable = False
        object.__setattr__(self, "pixels", pixels)


@dataclass(frozen=True, slots=True)
class SparseRasterSnapshot:
    """Capture sparse authoritative pixels and their logical layer extent."""

    bounds: RasterBounds | None
    extent_policy: RasterExtentPolicy
    channels: int
    tile_size: int
    tiles: tuple[SparseRasterTile, ...]

    def __post_init__(self) -> None:
        """Normalize policy and validate every detached canonical tile."""
        if self.channels < 1:
            raise ValueError("channels must be positive")
        if self.tile_size < 16:
            raise ValueError("tile_size must be at least 16")
        policy = RasterExtentPolicy(self.extent_policy)
        tiles = tuple(self.tiles)
        for tile in tiles:
            expected = (
                (self.tile_size, self.tile_size)
                if self.channels == 1
                else (self.tile_size, self.tile_size, self.channels)
            )
            if tile.pixels.dtype != np.uint8 or tile.pixels.shape != expected:
                raise ValueError(f"sparse tile pixels must match {expected}")
            if (
                self.bounds is not None
                and tile.bounds.intersection(self.bounds) is None
            ):
                raise ValueError("sparse tiles must intersect logical bounds")
        object.__setattr__(self, "extent_policy", policy)
        object.__setattr__(self, "tiles", tiles)

    @property
    def retained_bytes(self) -> int:
        """Return detached authoritative bytes retained by this snapshot."""
        return sum(tile.pixels.nbytes for tile in self.tiles)


class SparseRasterGrid:
    """Own zero-default raster tiles without allocating transparent gaps."""

    def __init__(
        self,
        *,
        channels: int,
        tile_size: int = 512,
    ) -> None:
        """Initialize an empty uint8 grid with a fixed tile geometry."""
        if channels < 1:
            raise ValueError("channels must be positive")
        if tile_size < 16:
            raise ValueError("tile_size must be at least 16")
        self._channels = int(channels)
        self._tile_size = int(tile_size)
        self._tiles: dict[tuple[int, int], np.ndarray] = {}

    @property
    def channels(self) -> int:
        """Return the canonical channel count."""
        return self._channels

    @property
    def tile_size(self) -> int:
        """Return the square tile edge in source pixels."""
        return self._tile_size

    @property
    def allocated_bytes(self) -> int:
        """Return authoritative pixel bytes currently retained by tiles."""
        return sum(tile.nbytes for tile in self._tiles.values())

    @property
    def tile_count(self) -> int:
        """Return the number of nonempty allocated tiles."""
        return len(self._tiles)

    def clear(self) -> None:
        """Discard every allocated tile."""
        self._tiles.clear()

    def snapshot(
        self,
        bounds: RasterBounds | None,
        extent_policy: RasterExtentPolicy,
    ) -> SparseRasterSnapshot:
        """Return one detached sparse structural snapshot."""
        return SparseRasterSnapshot(
            bounds,
            extent_policy,
            self._channels,
            self._tile_size,
            self.tiles(bounds),
        )

    def restore(self, snapshot: SparseRasterSnapshot) -> None:
        """Replace all tiles from one compatible detached snapshot."""
        if snapshot.channels != self._channels or snapshot.tile_size != self._tile_size:
            raise ValueError("sparse snapshot geometry does not match the grid")
        self._tiles = {
            (
                tile.bounds.x // self._tile_size,
                tile.bounds.y // self._tile_size,
            ): np.array(
                tile.pixels,
                copy=True,
                order="C",
            )
            for tile in snapshot.tiles
        }

    def replace(self, bounds: RasterBounds, pixels: np.ndarray) -> None:
        """Replace the grid from one dense region while omitting zero tiles."""
        normalized = self._normalize_pixels(bounds, pixels)
        self._tiles.clear()
        self.write(bounds, normalized)

    def read(self, bounds: RasterBounds) -> np.ndarray:
        """Return one zero-padded detached dense region."""
        result = self._zeros(bounds.height, bounds.width)
        for key in self._keys_for(bounds):
            tile = self._tiles.get(key)
            if tile is None:
                continue
            tile_bounds = self._tile_bounds(key)
            overlap = tile_bounds.intersection(bounds)
            if overlap is None:
                continue
            source_x = overlap.x - tile_bounds.x
            source_y = overlap.y - tile_bounds.y
            target_x = overlap.x - bounds.x
            target_y = overlap.y - bounds.y
            result[
                target_y : target_y + overlap.height,
                target_x : target_x + overlap.width,
            ] = tile[
                source_y : source_y + overlap.height,
                source_x : source_x + overlap.width,
            ]
        return result

    def read_strided(self, bounds: RasterBounds, stride: int) -> np.ndarray:
        """Sample a possibly enormous region without materializing transparent gaps."""
        step = max(1, int(stride))
        height = (bounds.height + step - 1) // step
        width = (bounds.width + step - 1) // step
        shape = (
            (height, width) if self._channels == 1 else (height, width, self._channels)
        )
        result = np.zeros(shape, dtype=np.uint8)
        for tile_bounds, tile in self.borrowed_tiles(bounds):
            overlap = tile_bounds.intersection(bounds)
            if overlap is None:
                continue
            first_x = overlap.x + (-(overlap.x - bounds.x)) % step
            first_y = overlap.y + (-(overlap.y - bounds.y)) % step
            if first_x >= overlap.right or first_y >= overlap.bottom:
                continue
            source_x = first_x - tile_bounds.x
            source_y = first_y - tile_bounds.y
            destination_x = (first_x - bounds.x) // step
            destination_y = (first_y - bounds.y) // step
            sampled = tile[
                source_y : overlap.bottom - tile_bounds.y : step,
                source_x : overlap.right - tile_bounds.x : step,
            ]
            result[
                destination_y : destination_y + sampled.shape[0],
                destination_x : destination_x + sampled.shape[1],
            ] = sampled
        return result

    def count_tiles(self, visible: RasterBounds | None = None) -> int:
        """Return allocated tile count, optionally culled without copying pixels."""
        if visible is None:
            return len(self._tiles)
        return sum(
            self._tile_bounds(key).intersection(visible) is not None
            for key in self._tiles
        )

    def write(self, bounds: RasterBounds, pixels: np.ndarray) -> None:
        """Replace one region and prune tiles that become entirely transparent."""
        normalized = self._normalize_pixels(bounds, pixels)
        for key in self._keys_for(bounds):
            tile_bounds = self._tile_bounds(key)
            overlap = tile_bounds.intersection(bounds)
            if overlap is None:
                continue
            source_x = overlap.x - bounds.x
            source_y = overlap.y - bounds.y
            tile_x = overlap.x - tile_bounds.x
            tile_y = overlap.y - tile_bounds.y
            tile = self._tiles.get(key)
            replacement = normalized[
                source_y : source_y + overlap.height,
                source_x : source_x + overlap.width,
            ]
            if tile is None:
                if not np.any(replacement):
                    continue
                tile = self._zeros(self._tile_size, self._tile_size)
                self._tiles[key] = tile
            tile[
                tile_y : tile_y + overlap.height,
                tile_x : tile_x + overlap.width,
            ] = replacement
            if not np.any(tile):
                self._tiles.pop(key, None)

    def crop(self, bounds: RasterBounds) -> None:
        """Discard pixels outside one fixed layer-local extent."""
        for key in tuple(self._tiles):
            tile_bounds = self._tile_bounds(key)
            overlap = tile_bounds.intersection(bounds)
            if overlap is None:
                self._tiles.pop(key, None)
                continue
            if overlap == tile_bounds:
                continue
            tile = self._tiles[key]
            retained = self._zeros(self._tile_size, self._tile_size)
            source_x = overlap.x - tile_bounds.x
            source_y = overlap.y - tile_bounds.y
            retained[
                source_y : source_y + overlap.height,
                source_x : source_x + overlap.width,
            ] = tile[
                source_y : source_y + overlap.height,
                source_x : source_x + overlap.width,
            ]
            if np.any(retained):
                self._tiles[key] = retained
            else:
                self._tiles.pop(key, None)

    def content_bounds(self) -> RasterBounds | None:
        """Return the exact envelope of nonzero pixels across allocated tiles."""
        occupied: RasterBounds | None = None
        for key, tile in self._tiles.items():
            if self._channels == 1:
                occupancy = tile
            else:
                occupancy = tile[:, :, -1]
            occupied_y, occupied_x = np.nonzero(occupancy)
            if occupied_x.size == 0:
                continue
            tile_bounds = self._tile_bounds(key)
            left = int(occupied_x.min())
            top = int(occupied_y.min())
            bounds = RasterBounds(
                tile_bounds.x + left,
                tile_bounds.y + top,
                int(occupied_x.max()) - left + 1,
                int(occupied_y.max()) - top + 1,
            )
            occupied = bounds if occupied is None else occupied.united(bounds)
        return occupied

    def tiles(
        self, visible: RasterBounds | None = None
    ) -> tuple[SparseRasterTile, ...]:
        """Return detached nonempty tiles, optionally culled to a local region."""
        selected: list[SparseRasterTile] = []
        for key in sorted(self._tiles, key=lambda item: (item[1], item[0])):
            tile_bounds = self._tile_bounds(key)
            if visible is not None and tile_bounds.intersection(visible) is None:
                continue
            selected.append(SparseRasterTile(tile_bounds, self._tiles[key]))
        return tuple(selected)

    def borrowed_tiles(
        self,
        visible: RasterBounds | None = None,
    ) -> tuple[tuple[RasterBounds, np.ndarray], ...]:
        """Return internal tile arrays for a synchronized owning adapter."""
        selected: list[tuple[RasterBounds, np.ndarray]] = []
        for key in sorted(self._tiles, key=lambda item: (item[1], item[0])):
            tile_bounds = self._tile_bounds(key)
            if visible is not None and tile_bounds.intersection(visible) is None:
                continue
            selected.append((tile_bounds, self._tiles[key]))
        return tuple(selected)

    def contains_tile(self, bounds: RasterBounds) -> bool:
        """Return whether one exact canonical tile remains allocated."""
        size = self._tile_size
        if (
            bounds.width != size
            or bounds.height != size
            or bounds.x % size
            or bounds.y % size
        ):
            return False
        return (bounds.x // size, bounds.y // size) in self._tiles

    def _keys_for(self, bounds: RasterBounds) -> tuple[tuple[int, int], ...]:
        """Return every tile coordinate intersecting ``bounds``."""
        size = self._tile_size
        left = bounds.x // size
        top = bounds.y // size
        right = (bounds.right - 1) // size
        bottom = (bounds.bottom - 1) // size
        return tuple(
            (tile_x, tile_y)
            for tile_y in range(top, bottom + 1)
            for tile_x in range(left, right + 1)
        )

    def _tile_bounds(self, key: tuple[int, int]) -> RasterBounds:
        """Map one signed tile coordinate into layer-local geometry."""
        tile_x, tile_y = key
        return RasterBounds(
            tile_x * self._tile_size,
            tile_y * self._tile_size,
            self._tile_size,
            self._tile_size,
        )

    def _normalize_pixels(
        self,
        bounds: RasterBounds,
        pixels: np.ndarray,
    ) -> np.ndarray:
        """Validate one uint8 region against grid geometry."""
        normalized = np.asarray(pixels)
        expected = (
            (bounds.height, bounds.width)
            if self._channels == 1
            else (bounds.height, bounds.width, self._channels)
        )
        if normalized.dtype != np.uint8 or normalized.shape != expected:
            raise ValueError(
                f"sparse raster pixels must be uint8 with shape {expected}"
            )
        return normalized

    def _zeros(self, height: int, width: int) -> np.ndarray:
        """Allocate one canonical zero-filled dense array."""
        shape = (
            (height, width) if self._channels == 1 else (height, width, self._channels)
        )
        return np.zeros(shape, dtype=np.uint8)


def reframe_sparse_raster_snapshot(
    snapshot: SparseRasterSnapshot,
    bounds: RasterBounds,
) -> SparseRasterSnapshot:
    """Crop or enlarge one sparse snapshot without allocating its envelope."""
    retained: list[SparseRasterTile] = []
    for tile in snapshot.tiles:
        overlap = tile.bounds.intersection(bounds)
        if overlap is None:
            continue
        if overlap == tile.bounds:
            retained.append(tile)
            continue
        pixels = np.zeros_like(tile.pixels)
        x = overlap.x - tile.bounds.x
        y = overlap.y - tile.bounds.y
        pixels[y : y + overlap.height, x : x + overlap.width] = tile.pixels[
            y : y + overlap.height,
            x : x + overlap.width,
        ]
        if np.any(pixels):
            retained.append(SparseRasterTile(tile.bounds, pixels))
    return SparseRasterSnapshot(
        bounds,
        snapshot.extent_policy,
        snapshot.channels,
        snapshot.tile_size,
        tuple(retained),
    )
