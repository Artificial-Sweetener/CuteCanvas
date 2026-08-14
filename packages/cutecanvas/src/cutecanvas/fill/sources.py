#    CuteCanvas - High-performance layered image editor
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Immutable tile-backed pixel sources for asynchronous flood filling."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from qpane.sdk.scene import RasterBounds

from ..coverage import CoverageAssetSnapshot, CoverageDocument
from ..coverage.evaluation import CoverageDocumentEvaluator
from ..coverage.operations import combine_coverage
from ..raster.sparse_grid import SparseRasterSnapshot


@runtime_checkable
class FloodFillPixelSource(Protocol):
    """Read immutable target-local pixels in bounded worker-owned regions."""

    @property
    def bounds(self) -> RasterBounds:
        """Return the finite searchable extent."""
        ...

    @property
    def channels(self) -> int:
        """Return one for coverage or three/four for color pixels."""
        ...

    def read(self, bounds: RasterBounds) -> np.ndarray:
        """Return detached pixels for one contained region."""
        ...


class DenseFloodFillPixelSource:
    """Adapt one detached dense array to bounded source reads."""

    def __init__(self, pixels: np.ndarray, bounds: RasterBounds) -> None:
        """Validate immutable array geometry without copying it."""
        array = np.asarray(pixels)
        channels = 1 if array.ndim == 2 else array.shape[2]
        if (
            array.dtype != np.uint8
            or array.ndim not in (2, 3)
            or channels not in (1, 3, 4)
            or array.shape[:2] != (bounds.height, bounds.width)
        ):
            raise ValueError("dense flood-fill pixels do not match their bounds")
        self._pixels = array
        self._bounds = bounds
        self._channels = channels

    @property
    def bounds(self) -> RasterBounds:
        """Return the exact dense source extent."""
        return self._bounds

    @property
    def channels(self) -> int:
        """Return the source channel count."""
        return self._channels

    def read(self, bounds: RasterBounds) -> np.ndarray:
        """Return one detached contained view region."""
        if not self._bounds.contains(bounds):
            raise ValueError("flood-fill reads must remain inside source bounds")
        x = bounds.x - self._bounds.x
        y = bounds.y - self._bounds.y
        return np.ascontiguousarray(
            self._pixels[y : y + bounds.height, x : x + bounds.width]
        )


class SparseFloodFillPixelSource:
    """Read one immutable sparse raster snapshot without its transparent envelope."""

    def __init__(self, snapshot: SparseRasterSnapshot) -> None:
        """Index immutable canonical tiles for bounded reads."""
        if snapshot.bounds is None:
            raise ValueError("flood-fill sources require finite bounds")
        self._snapshot = snapshot
        self._tiles = {tile.bounds: tile.pixels for tile in snapshot.tiles}

    @property
    def bounds(self) -> RasterBounds:
        """Return the sparse resource's logical searchable extent."""
        assert self._snapshot.bounds is not None
        return self._snapshot.bounds

    @property
    def channels(self) -> int:
        """Return the sparse snapshot channel count."""
        return self._snapshot.channels

    def read(self, bounds: RasterBounds) -> np.ndarray:
        """Materialize only one requested worker block."""
        if not self.bounds.contains(bounds):
            raise ValueError("flood-fill reads must remain inside source bounds")
        shape = (
            (bounds.height, bounds.width)
            if self.channels == 1
            else (bounds.height, bounds.width, self.channels)
        )
        result = np.zeros(shape, dtype=np.uint8)
        for tile_bounds, pixels in self._tiles.items():
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
            ] = pixels[
                source_y : source_y + overlap.height,
                source_x : source_x + overlap.width,
            ]
        return result


class HybridCoverageFillPixelSource:
    """Evaluate sparse raster and retained coverage by requested worker block."""

    def __init__(self, snapshot: CoverageAssetSnapshot) -> None:
        """Bind detached hybrid authority and derive a finite searchable extent."""
        raster = SparseFloodFillPixelSource(snapshot.raster)
        evaluator = CoverageDocumentEvaluator()
        retained_bounds = evaluator.candidate_bounds(snapshot.retained)
        self._bounds = (
            raster.bounds
            if retained_bounds is None
            else raster.bounds.united(retained_bounds)
        )
        self._raster = raster
        self._retained = snapshot.retained
        self._evaluator = evaluator

    @property
    def bounds(self) -> RasterBounds:
        """Return storage plus retained authored geometry bounds."""
        return self._bounds

    @property
    def channels(self) -> int:
        """Return the single coverage channel."""
        return 1

    def read(self, bounds: RasterBounds) -> np.ndarray:
        """Evaluate one bounded hybrid block without dense envelope allocation."""
        if not self._bounds.contains(bounds):
            raise ValueError("flood-fill reads must remain inside source bounds")
        overlap = self._raster.bounds.intersection(bounds)
        pixels = np.zeros((bounds.height, bounds.width), dtype=np.uint8)
        if overlap is not None:
            source = self._raster.read(overlap)
            x = overlap.x - bounds.x
            y = overlap.y - bounds.y
            pixels[y : y + overlap.height, x : x + overlap.width] = source
        for item in self._retained.items:
            contribution = self._evaluator.evaluate(
                CoverageDocument(items=(item,)),
                bounds,
            ).pixels
            pixels = combine_coverage(pixels, contribution, item.combine_mode)
        return np.ascontiguousarray(pixels)
