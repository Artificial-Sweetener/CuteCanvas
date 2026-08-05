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
"""Build source-neutral edge modifications for scalar layer coverage."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from qpane.sdk.scene import RasterBounds

from cutecanvas.types import LayerEdgeOperation

from .filters import dilate_coverage, erode_coverage, feather_coverage
from .surface import CoverageSnapshot


@dataclass(frozen=True, slots=True)
class CoverageEdgeModificationRequest:
    """Describe one detached coverage transformation in source coordinates."""

    coverage: CoverageSnapshot
    operation: LayerEdgeOperation
    radius: float
    constraint: RasterBounds | None = None

    def __post_init__(self) -> None:
        """Validate immutable geometry and operation-specific radius rules."""
        if self.coverage.bounds is None:
            raise ValueError("coverage modification requires nonempty coverage")
        operation = LayerEdgeOperation(self.operation)
        radius = float(self.radius)
        if not math.isfinite(radius) or radius < 0.0:
            raise ValueError("coverage radius must be finite and non-negative")
        if operation is not LayerEdgeOperation.FEATHER and int(radius) != radius:
            raise ValueError("expand and contract radii must use whole pixels")
        if self.constraint is not None and (
            self.constraint.width <= 0 or self.constraint.height <= 0
        ):
            raise ValueError("coverage constraint must have positive dimensions")
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "radius", radius)


def build_coverage_edge_modification(
    request: CoverageEdgeModificationRequest,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> CoverageSnapshot | None:
    """Return detached modified coverage without mutating its source layer."""
    source_bounds = request.coverage.bounds
    assert source_bounds is not None
    clipped_source = _intersection(source_bounds, request.constraint)
    if clipped_source is None:
        return None
    margin = (
        math.ceil(request.radius * 3.0)
        if request.operation is LayerEdgeOperation.FEATHER
        else int(request.radius)
    )
    candidate = (
        clipped_source
        if request.operation is LayerEdgeOperation.CONTRACT
        else _padded_bounds(clipped_source, margin)
    )
    output_bounds = _intersection(candidate, request.constraint)
    if output_bounds is None:
        return None
    projected = _project_coverage(request.coverage, output_bounds)
    if request.operation is LayerEdgeOperation.EXPAND:
        pixels = dilate_coverage(projected, int(request.radius), cancelled=cancelled)
    elif request.operation is LayerEdgeOperation.CONTRACT:
        pixels = erode_coverage(projected, int(request.radius), cancelled=cancelled)
    else:
        pixels = feather_coverage(projected, request.radius, cancelled=cancelled)
    return _trim_coverage(
        CoverageSnapshot._adopt_detached(
            output_bounds,
            request.coverage.extent_policy,
            pixels,
        )
    )


def _intersection(
    bounds: RasterBounds,
    constraint: RasterBounds | None,
) -> RasterBounds | None:
    """Apply an optional finite output constraint."""
    return bounds if constraint is None else bounds.intersection(constraint)


def _padded_bounds(bounds: RasterBounds, margin: int) -> RasterBounds:
    """Return integer bounds expanded equally along every edge."""
    return RasterBounds(
        bounds.x - margin,
        bounds.y - margin,
        bounds.width + margin * 2,
        bounds.height + margin * 2,
    )


def _project_coverage(snapshot: CoverageSnapshot, bounds: RasterBounds) -> np.ndarray:
    """Project sparse source-aligned coverage into explicit output bounds."""
    result = np.zeros((bounds.height, bounds.width), dtype=np.uint8)
    source = snapshot.bounds
    if source is None:
        return result
    overlap = source.intersection(bounds)
    if overlap is None:
        return result
    source_x = overlap.x - source.x
    source_y = overlap.y - source.y
    target_x = overlap.x - bounds.x
    target_y = overlap.y - bounds.y
    result[
        target_y : target_y + overlap.height,
        target_x : target_x + overlap.width,
    ] = snapshot.pixels[
        source_y : source_y + overlap.height,
        source_x : source_x + overlap.width,
    ]
    return result


def _trim_coverage(snapshot: CoverageSnapshot) -> CoverageSnapshot | None:
    """Remove zero-only margins while preserving source coordinates."""
    if snapshot.bounds is None or not np.any(snapshot.pixels):
        return None
    rows, columns = np.nonzero(snapshot.pixels)
    left = int(columns.min())
    top = int(rows.min())
    right = int(columns.max()) + 1
    bottom = int(rows.max()) + 1
    bounds = snapshot.bounds
    trimmed = np.ascontiguousarray(snapshot.pixels[top:bottom, left:right])
    return CoverageSnapshot._adopt_detached(
        RasterBounds(bounds.x + left, bounds.y + top, right - left, bottom - top),
        snapshot.extent_policy,
        trimmed,
    )


__all__ = [
    "CoverageEdgeModificationRequest",
    "build_coverage_edge_modification",
]
