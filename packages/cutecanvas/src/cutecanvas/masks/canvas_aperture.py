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

"""Derive active-mask authoring constraints from the composition canvas."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainterPath, QPolygonF

from qpane.sdk.scene import (
    BilinearLayerTransform,
    LayerDescriptor,
    PiecewiseLayerTransform,
    RasterBounds,
    SceneDescriptor,
)

from ..coverage import CoverageSnapshot
from ..coverage.spatial_constraint import (
    CoverageSpatialConstraint,
    PathCoverageConstraint,
    SnapshotCoverageConstraint,
)
from ..resources import ProjectResourceReference
from ..selection import LayerCoverageProjector, PixelSelectionService
from ..types import RasterExtentPolicy


class ActiveMaskCanvasAperture:
    """Own the canvas aperture shared by mask tools and stroke rendering."""

    def __init__(
        self,
        *,
        active_mask_id: Callable[[], uuid.UUID | None],
        active_scene: Callable[[], SceneDescriptor | None],
        pixel_selection: PixelSelectionService,
    ) -> None:
        """Bind mask identity, scene geometry, and pixel-selection state."""
        self._active_mask_id = active_mask_id
        self._active_scene = active_scene
        self._pixel_selection = pixel_selection
        self._coverage_projector = LayerCoverageProjector()
        self._path_key: tuple[object, ...] | None = None
        self._source_path: QPainterPath | None = None

    def stroke_constraint(
        self,
        mask_id: uuid.UUID,
    ) -> CoverageSpatialConstraint | None:
        """Project the canvas and optional pixel selection into mask-local space."""
        resolved = self._resolved_layer(mask_id)
        if resolved is None:
            return None
        scene, layer = resolved
        transform = layer.transform
        bounds = _canvas_bounds(scene)
        if transform is None or bounds is None:
            return None
        selection = self._pixel_selection.state(scene.scene_id).coverage
        if selection is not None:
            clipped = selection.clipped_to(bounds)
            if clipped is None:
                return SnapshotCoverageConstraint(_empty_constraint())
            projected = self._coverage_projector.project_to_layer(
                clipped,
                transform,
            )
            return None if projected is None else SnapshotCoverageConstraint(projected)
        return self.coverage_constraint(mask_id)

    def coverage_constraint(
        self,
        mask_id: uuid.UUID | None = None,
    ) -> CoverageSpatialConstraint | None:
        """Return the exact canvas aperture for coverage-changing operations."""

        path = self.coverage_aperture_path(mask_id)
        return None if path is None else PathCoverageConstraint(path)

    def coverage_aperture_path(
        self,
        mask_id: uuid.UUID | None = None,
    ) -> QPainterPath | None:
        """Return the scene canvas quadrilateral in active-mask source space."""
        resolved = self._resolved_layer(mask_id)
        if resolved is None:
            return None
        scene, layer = resolved
        bounds = scene.bounds
        key = (scene.scene_id, bounds, layer.layer_id, layer.transform)
        if key == self._path_key:
            return (
                None if self._source_path is None else QPainterPath(self._source_path)
            )
        transform = layer.transform
        if transform is None:
            return None
        scene_points = (
            QPointF(bounds.x, bounds.y),
            QPointF(bounds.x + bounds.width, bounds.y),
            QPointF(bounds.x + bounds.width, bounds.y + bounds.height),
            QPointF(bounds.x, bounds.y + bounds.height),
        )
        if isinstance(
            transform,
            (PiecewiseLayerTransform, BilinearLayerTransform),
        ):
            scene_path = QPainterPath()
            scene_path.addPolygon(QPolygonF(scene_points))
            scene_path.closeSubpath()
            path = transform.inverse_map_path(scene_path)
            if path.isEmpty():
                return None
            self._path_key = key
            self._source_path = QPainterPath(path)
            return path
        local_points = tuple(transform.inverse_map(point) for point in scene_points)
        if any(point is None for point in local_points):
            return None
        path = QPainterPath()
        path.addPolygon(
            QPolygonF([point for point in local_points if point is not None])
        )
        path.closeSubpath()
        self._path_key = key
        self._source_path = QPainterPath(path)
        return path

    def _resolved_layer(
        self,
        mask_id: uuid.UUID | None = None,
    ) -> tuple[SceneDescriptor, LayerDescriptor] | None:
        """Return one active mask's current scene descriptor."""
        target_id = self._active_mask_id() if mask_id is None else mask_id
        scene = self._active_scene()
        if target_id is None or scene is None:
            return None
        layer = next(
            (
                candidate
                for candidate in scene.layers
                if isinstance(candidate.source, ProjectResourceReference)
                and candidate.source.resource_id == target_id
            ),
            None,
        )
        return None if layer is None else (scene, layer)


def _empty_constraint() -> CoverageSnapshot:
    """Return an immutable empty stroke constraint."""
    return CoverageSnapshot(
        None,
        RasterExtentPolicy.FIXED,
        np.zeros((0, 0), dtype=np.uint8),
    )


def _canvas_bounds(scene: SceneDescriptor) -> RasterBounds | None:
    """Return enclosing integer bounds for one finite scene canvas."""
    bounds = scene.bounds
    left = math.floor(bounds.x)
    top = math.floor(bounds.y)
    right = math.ceil(bounds.x + bounds.width)
    bottom = math.ceil(bounds.y + bounds.height)
    if right <= left or bottom <= top:
        return None
    return RasterBounds(left, top, right - left, bottom - top)
