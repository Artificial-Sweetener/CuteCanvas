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
"""Shared transaction state and selection projection for raster brush strokes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import numpy as np
from qpane.sdk.scene import LayerDescriptor, RasterBounds, SceneDescriptor

from ..coverage import CoverageSnapshot
from ..selection import LayerCoverageProjector, PixelSelectionService


@dataclass(slots=True)
class RasterStrokeSession:
    """Own one unresolved raster stroke's original tiles and constraint."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    raster_id: uuid.UUID
    before_bounds: RasterBounds
    constraint: CoverageSnapshot | None
    constrained: bool
    before_tiles: dict[RasterBounds, np.ndarray] = field(default_factory=dict)

    def constraint_pixels(self, bounds: RasterBounds) -> np.ndarray | None:
        """Return local soft-selection coverage, including an empty selection."""
        if not self.constrained:
            return None
        pixels = np.zeros((bounds.height, bounds.width), dtype=np.uint8)
        constraint = self.constraint
        if constraint is None or constraint.bounds is None:
            return pixels
        overlap = constraint.bounds.intersection(bounds)
        if overlap is None:
            return pixels
        source_x = overlap.x - constraint.bounds.x
        source_y = overlap.y - constraint.bounds.y
        target_x = overlap.x - bounds.x
        target_y = overlap.y - bounds.y
        pixels[
            target_y : target_y + overlap.height,
            target_x : target_x + overlap.width,
        ] = constraint.pixels[
            source_y : source_y + overlap.height,
            source_x : source_x + overlap.width,
        ]
        return pixels


def selection_constraint(
    selections: PixelSelectionService,
    scene: SceneDescriptor,
    layer: LayerDescriptor,
) -> tuple[CoverageSnapshot | None, bool]:
    """Project the scene selection into one raster layer's local coordinates."""
    scene_selection = selections.state(scene.scene_id).coverage
    if (
        scene_selection is None
        or layer.transform is None
        or layer.raster_bounds is None
    ):
        return None, scene_selection is not None
    return (
        LayerCoverageProjector().project_to_layer(
            scene_selection,
            layer.transform,
            layer.raster_bounds,
        ),
        True,
    )
