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
"""Adapt source-neutral coverage modifications to pixel selections."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from cutecanvas.coverage import (
    CoverageEdgeModificationRequest,
    CoverageSnapshot,
    build_coverage_edge_modification,
)
from cutecanvas.coverage.spatial_constraint import BoundsCoverageConstraint
from cutecanvas.types import LayerEdgeOperation
from qpane.sdk.scene import RasterBounds


@dataclass(frozen=True, slots=True)
class PixelSelectionModificationRequest:
    """Describe one detached selection transformation inside a finite canvas."""

    coverage: CoverageSnapshot
    canvas_bounds: RasterBounds
    operation: LayerEdgeOperation
    radius: float

    def __post_init__(self) -> None:
        """Validate immutable geometry and operation-specific radius rules."""
        if self.coverage.bounds is None:
            raise ValueError("selection modification requires nonempty coverage")
        if self.canvas_bounds.width <= 0 or self.canvas_bounds.height <= 0:
            raise ValueError("selection modification requires positive canvas bounds")
        operation = LayerEdgeOperation(self.operation)
        radius = float(self.radius)
        if not math.isfinite(radius) or radius < 0.0:
            raise ValueError(
                "selection modification radius must be finite and non-negative"
            )
        if operation is not LayerEdgeOperation.FEATHER and int(radius) != radius:
            raise ValueError("expand and contract radii must use whole pixels")
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "radius", radius)


def build_pixel_selection_modification(
    request: PixelSelectionModificationRequest,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> CoverageSnapshot | None:
    """Return one detached modified selection without mutating document state."""
    return build_coverage_edge_modification(
        CoverageEdgeModificationRequest(
            coverage=request.coverage,
            operation=request.operation,
            radius=request.radius,
            spatial_constraint=BoundsCoverageConstraint(request.canvas_bounds),
        ),
        cancelled=cancelled,
    )


__all__ = [
    "PixelSelectionModificationRequest",
    "build_pixel_selection_modification",
]
