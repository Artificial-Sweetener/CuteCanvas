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
"""Cancellable NumPy flood-fill coverage generation."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from qpane.sdk.scene import RasterBounds

from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.types import RasterExtentPolicy

from .sources import DenseFloodFillPixelSource, FloodFillPixelSource


class FillCancelledError(RuntimeError):
    """Report cooperative cancellation without publishing partial coverage."""


@dataclass(frozen=True, slots=True)
class FloodFillRequest:
    """Describe one immutable raster sampling request."""

    pixels: FloodFillPixelSource | np.ndarray
    bounds: RasterBounds
    seed_x: int
    seed_y: int
    tolerance: int = 32
    contiguous: bool = True
    antialias: bool = True
    constraint: CoverageSnapshot | None = None

    def __post_init__(self) -> None:
        """Validate detached request geometry without copying source pixels."""
        pixels = self.pixels
        source = (
            DenseFloodFillPixelSource(pixels, self.bounds)
            if isinstance(pixels, np.ndarray)
            else pixels
        )
        if not isinstance(source, FloodFillPixelSource):
            raise TypeError("flood fill requires an immutable pixel source")
        if source.bounds != self.bounds or source.channels not in (1, 3, 4):
            raise ValueError("flood-fill source must match request bounds")
        if not 0 <= int(self.tolerance) <= 255:
            raise ValueError("flood-fill tolerance must be between 0 and 255")
        object.__setattr__(self, "pixels", source)
        object.__setattr__(self, "tolerance", int(self.tolerance))


class FloodFillEngine:
    """Generate selection-quality coverage with linear memory and no recursion."""

    def fill(
        self,
        request: FloodFillRequest,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> CoverageSnapshot | None:
        """Return minimal fill coverage or raise on cooperative cancellation."""
        bounds = request.bounds
        local_x = int(request.seed_x) - bounds.x
        local_y = int(request.seed_y) - bounds.y
        if not (0 <= local_x < bounds.width and 0 <= local_y < bounds.height):
            return None
        source = request.pixels
        assert isinstance(source, FloodFillPixelSource)
        sample_bounds = RasterBounds(bounds.x + local_x, bounds.y + local_y, 1, 1)
        sample = source.read(sample_bounds)[0, 0].astype(np.int16, copy=False)
        soft = _similarity_coverage(
            source,
            bounds,
            sample,
            request.tolerance,
            request.antialias,
            cancelled,
        )
        if request.constraint is not None:
            soft = _apply_constraint(soft, bounds, request.constraint)
        if soft[local_y, local_x] == 0:
            return None
        coverage = (
            _contiguous_coverage(soft, local_x, local_y, cancelled)
            if request.contiguous
            else soft
        )
        if cancelled is not None and cancelled():
            raise FillCancelledError("flood fill cancelled")
        return _trim_coverage(coverage, bounds)


def _similarity_coverage(
    source: FloodFillPixelSource,
    bounds: RasterBounds,
    sample: np.ndarray,
    tolerance: int,
    antialias: bool,
    cancelled: Callable[[], bool] | None,
) -> np.ndarray:
    """Classify bounded row blocks without full-image int16 intermediates."""
    result = np.empty((bounds.height, bounds.width), dtype=np.uint8)
    band = max(2, min(16, tolerance // 4 + 2))
    rows_per_block = max(1, 1_048_576 // max(1, bounds.width))
    for top in range(0, bounds.height, rows_per_block):
        if cancelled is not None and cancelled():
            raise FillCancelledError("flood fill cancelled")
        bottom = min(bounds.height, top + rows_per_block)
        block = source.read(
            RasterBounds(bounds.x, bounds.y + top, bounds.width, bottom - top)
        ).astype(np.int16)
        difference = np.abs(block - sample)
        distance = difference if difference.ndim == 2 else np.max(difference, axis=2)
        if antialias:
            numerator = tolerance + band - distance
            result[top:bottom] = np.clip(
                np.rint(numerator * (255.0 / band)),
                0,
                255,
            ).astype(np.uint8)
        else:
            result[top:bottom] = np.where(distance <= tolerance, 255, 0)
    return result


def _contiguous_coverage(
    soft: np.ndarray,
    seed_x: int,
    seed_y: int,
    cancelled: Callable[[], bool] | None,
) -> np.ndarray:
    """Retain only the seed-connected component through scanline spans."""
    state = np.where(soft > 0, 1, 0).astype(np.uint8)
    result = np.zeros_like(soft)
    queue: deque[tuple[int, int]] = deque(((seed_x, seed_y),))
    state[seed_y, seed_x] = 2
    processed = 0
    while queue:
        x, y = queue.popleft()
        if state[y, x] == 0:
            continue
        left, right = _occupied_run_bounds(state[y], x)
        result[y, left:right] = soft[y, left:right]
        state[y, left:right] = 0
        for adjacent_y in (y - 1, y + 1):
            if not 0 <= adjacent_y < state.shape[0]:
                continue
            _enqueue_runs(state, adjacent_y, left, right, queue)
        processed += right - left
        if processed >= 16_384:
            processed = 0
            if cancelled is not None and cancelled():
                raise FillCancelledError("flood fill cancelled")
    return result


def _occupied_run_bounds(row: np.ndarray, x: int) -> tuple[int, int]:
    """Return the occupied run around ``x`` using vectorized row scans."""
    left_zeros = np.flatnonzero(row[:x] == 0)
    left = 0 if left_zeros.size == 0 else int(left_zeros[-1]) + 1
    right_zeros = np.flatnonzero(row[x + 1 :] == 0)
    right = row.shape[0] if right_zeros.size == 0 else x + 1 + int(right_zeros[0])
    return left, right


def _enqueue_runs(
    state: np.ndarray,
    y: int,
    left: int,
    right: int,
    queue: deque[tuple[int, int]],
) -> None:
    """Queue each not-yet-queued connected run along an adjacent row."""
    eligible = state[y, left:right] == 1
    if not np.any(eligible):
        return
    starts = np.flatnonzero(eligible & np.concatenate(([True], ~eligible[:-1])))
    for relative_x in starts:
        x = left + int(relative_x)
        state[y, x] = 2
        queue.append((x, y))


def _apply_constraint(
    coverage: np.ndarray,
    bounds: RasterBounds,
    constraint: CoverageSnapshot,
) -> np.ndarray:
    """Multiply coverage by an optional scene-aligned selection constraint."""
    result = np.zeros_like(coverage)
    source_bounds = constraint.bounds
    if source_bounds is None:
        return result
    overlap = bounds.intersection(source_bounds)
    if overlap is None:
        return result
    target_x = overlap.x - bounds.x
    target_y = overlap.y - bounds.y
    source_x = overlap.x - source_bounds.x
    source_y = overlap.y - source_bounds.y
    target = coverage[
        target_y : target_y + overlap.height,
        target_x : target_x + overlap.width,
    ].astype(np.uint16)
    mask = constraint.pixels[
        source_y : source_y + overlap.height,
        source_x : source_x + overlap.width,
    ].astype(np.uint16)
    result[
        target_y : target_y + overlap.height,
        target_x : target_x + overlap.width,
    ] = ((target * mask + 127) // 255).astype(np.uint8)
    return result


def _trim_coverage(
    coverage: np.ndarray,
    bounds: RasterBounds,
) -> CoverageSnapshot | None:
    """Return minimal nonzero immutable coverage."""
    occupied_rows = np.flatnonzero(np.any(coverage, axis=1))
    if occupied_rows.size == 0:
        return None
    occupied_columns = np.flatnonzero(np.any(coverage, axis=0))
    top = int(occupied_rows[0])
    bottom = int(occupied_rows[-1]) + 1
    left = int(occupied_columns[0])
    right = int(occupied_columns[-1]) + 1
    trimmed = np.ascontiguousarray(coverage[top:bottom, left:right])
    return CoverageSnapshot(
        RasterBounds(
            bounds.x + int(left),
            bounds.y + int(top),
            int(right - left),
            int(bottom - top),
        ),
        RasterExtentPolicy.EXPAND_ON_WRITE,
        trimmed,
    )
