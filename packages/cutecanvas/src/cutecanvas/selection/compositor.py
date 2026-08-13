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
"""Coordinate-aware composition of pixel-selection coverage snapshots."""

from __future__ import annotations

import numpy as np
from cutecanvas.coverage import CoverageCombineMode, CoverageSnapshot, combine_coverage
from cutecanvas.types import RasterExtentPolicy
from qpane.sdk.scene import RasterBounds


def compose_selection_coverage(
    existing: CoverageSnapshot | None,
    incoming: CoverageSnapshot,
    mode: CoverageCombineMode,
) -> CoverageSnapshot | None:
    """Combine scene-coordinate coverage and trim transparent outer storage."""
    operation = CoverageCombineMode(mode)
    if operation is CoverageCombineMode.REPLACE or existing is None:
        return trim_selection_coverage(incoming)
    existing_bounds = existing.bounds
    incoming_bounds = incoming.bounds
    if existing_bounds is None or incoming_bounds is None:
        return trim_selection_coverage(existing)
    output_bounds = _output_bounds(existing_bounds, incoming_bounds, operation)
    if output_bounds is None:
        return None
    destination = _project_snapshot(existing, output_bounds)
    source = _project_snapshot(incoming, output_bounds)
    combined = combine_coverage(destination, source, operation)
    return trim_selection_coverage(
        CoverageSnapshot._adopt_detached(
            output_bounds,
            RasterExtentPolicy.EXPAND_ON_WRITE,
            combined,
        )
    )


def trim_selection_coverage(
    snapshot: CoverageSnapshot,
) -> CoverageSnapshot | None:
    """Return the smallest snapshot containing every nonzero coverage pixel."""
    bounds = snapshot.bounds
    if bounds is None or snapshot.pixels.size == 0:
        return None
    if int(snapshot.pixels.min()) > 0:
        return snapshot
    occupied_rows = np.flatnonzero(np.any(snapshot.pixels != 0, axis=1))
    if occupied_rows.size == 0:
        return None
    occupied_columns = np.flatnonzero(np.any(snapshot.pixels != 0, axis=0))
    left = int(occupied_columns[0])
    top = int(occupied_rows[0])
    right = int(occupied_columns[-1]) + 1
    bottom = int(occupied_rows[-1]) + 1
    if left == 0 and top == 0 and right == bounds.width and bottom == bounds.height:
        return snapshot
    trimmed_bounds = RasterBounds(
        bounds.x + left,
        bounds.y + top,
        right - left,
        bottom - top,
    )
    return CoverageSnapshot(
        bounds=trimmed_bounds,
        extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
        pixels=snapshot.pixels[top:bottom, left:right],
    )


def _output_bounds(
    existing: RasterBounds,
    incoming: RasterBounds,
    mode: CoverageCombineMode,
) -> RasterBounds | None:
    """Return storage bounds required by one combination operation."""
    if mode is CoverageCombineMode.ADD:
        return existing.united(incoming)
    if mode is CoverageCombineMode.INTERSECT:
        return existing.intersection(incoming)
    return existing


def _project_snapshot(
    snapshot: CoverageSnapshot,
    output_bounds: RasterBounds,
) -> np.ndarray:
    """Project one snapshot into an output-bounds-aligned array."""
    bounds = snapshot.bounds
    if bounds is not None and bounds.contains(output_bounds):
        source_x = output_bounds.x - bounds.x
        source_y = output_bounds.y - bounds.y
        return snapshot.pixels[
            source_y : source_y + output_bounds.height,
            source_x : source_x + output_bounds.width,
        ]
    output = np.zeros((output_bounds.height, output_bounds.width), dtype=np.uint8)
    if bounds is None:
        return output
    overlap = bounds.intersection(output_bounds)
    if overlap is None:
        return output
    source_x = overlap.x - bounds.x
    source_y = overlap.y - bounds.y
    target_x = overlap.x - output_bounds.x
    target_y = overlap.y - output_bounds.y
    output[
        target_y : target_y + overlap.height,
        target_x : target_x + overlap.width,
    ] = snapshot.pixels[
        source_y : source_y + overlap.height,
        source_x : source_x + overlap.width,
    ]
    return output
