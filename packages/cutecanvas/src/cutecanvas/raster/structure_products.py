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
"""Build detached editable-raster structure products."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from qpane.sdk.execution import CancellationToken
from qpane.sdk.scene import RasterBounds

from .color_surface import ColorRasterSurface
from .sparse_grid import SparseRasterSnapshot, reframe_sparse_raster_snapshot


@dataclass(frozen=True, slots=True)
class RasterReframeProduct:
    """Carry source chronology and one detached reframed raster."""

    source_revisions: tuple[int, int]
    source_snapshot: SparseRasterSnapshot
    result: SparseRasterSnapshot


def build_raster_reframe(
    surface: ColorRasterSurface,
    bounds: RasterBounds,
    cancellation: CancellationToken,
) -> RasterReframeProduct:
    """Snapshot and reframe one color raster cooperatively."""
    return build_sparse_reframe(
        surface.versioned_sparse_snapshot,
        bounds,
        cancellation,
    )


def build_sparse_reframe(
    capture: Callable[[], tuple[int, int, SparseRasterSnapshot]],
    bounds: RasterBounds,
    cancellation: CancellationToken,
) -> RasterReframeProduct:
    """Capture and reframe any authoritative sparse raster surface."""
    cancellation.raise_if_cancelled()
    content, structure, snapshot = capture()
    cancellation.raise_if_cancelled()
    result = reframe_sparse_raster_snapshot(snapshot, bounds)
    cancellation.raise_if_cancelled()
    return RasterReframeProduct((content, structure), snapshot, result)
