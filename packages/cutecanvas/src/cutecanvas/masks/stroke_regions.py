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
"""Map semantic layer-local brush segments into writable mask storage."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QRect

from cutecanvas.coverage import WritableCoverageRegion
from qpane.sdk.scene import RasterBounds

from ..coverage.spatial_constraint import CoverageSpatialConstraint
from ..painting import BrushDabEngine, BrushDabRegionPlanner, BrushStrokeSegment
from .mask import MaskLayer


@dataclass(frozen=True, slots=True)
class PreparedMaskStrokeRegion:
    """Describe a clipped storage-space segment ready for preview rendering."""

    segment: BrushStrokeSegment
    dirty_rect: QRect
    rebase_x: int = 0
    rebase_y: int = 0


class MaskStrokeRegionPlanner:
    """Apply source extent policy and translate local brush geometry to storage."""

    def __init__(
        self,
        prepare_writable: Callable[
            [uuid.UUID, RasterBounds], WritableCoverageRegion | None
        ],
    ) -> None:
        """Bind the source-owned writable-region boundary."""
        self._prepare_writable = prepare_writable
        self._dabs = BrushDabEngine()
        self._regions = BrushDabRegionPlanner()

    def prepare(
        self,
        mask_id: uuid.UUID,
        layer: MaskLayer,
        segment: BrushStrokeSegment,
        constraint: CoverageSpatialConstraint | None = None,
    ) -> PreparedMaskStrokeRegion | None:
        """Return storage-space geometry accepted for one semantic segment."""
        requested = self._requested_bounds(segment)
        if constraint is not None:
            constraint_bounds = constraint.bounds
            if constraint_bounds is None:
                return None
            requested = requested.intersection(constraint_bounds)
            if requested is None:
                return None
        write = self._prepare_writable(mask_id, requested)
        if write is None or write.writable is None or write.after_bounds is None:
            return None
        storage = layer.coverage.raster.storage_rect(write.writable)
        if storage is None:
            return None
        rebase_x = 0
        rebase_y = 0
        if write.expanded and write.before_bounds is not None:
            rebase_x = write.before_bounds.x - write.after_bounds.x
            rebase_y = write.before_bounds.y - write.after_bounds.y
        return PreparedMaskStrokeRegion(
            segment=segment.translated(
                float(-write.after_bounds.x),
                float(-write.after_bounds.y),
            ),
            dirty_rect=storage.to_qrect(),
            rebase_x=rebase_x,
            rebase_y=rebase_y,
        )

    def _requested_bounds(self, segment: BrushStrokeSegment) -> RasterBounds:
        """Return the conservative layer-local footprint of ``segment``."""
        bounds = self._regions.bounds(self._dabs.segment_dabs(segment))
        if bounds is None:
            raise ValueError("a paintable mask segment must resolve at least one dab")
        return bounds
