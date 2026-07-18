#    QPane - High-performance PySide6 image viewer
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

"""Coordinate mapping for the active editable mask layer."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import QPoint, QPointF

from ..scene.model import SceneDescriptor
from ..scene.sources import MaskLayerSource


class ActiveMaskLayerCoordinates:
    """Map through the active mask layer's resolved scene transform."""

    def __init__(
        self,
        *,
        active_mask_id: Callable[[], uuid.UUID | None],
        active_scene: Callable[[], SceneDescriptor | None],
        panel_to_scene: Callable[[QPoint | QPointF], QPointF | None],
        layer_to_panel: Callable[
            [uuid.UUID, uuid.UUID, QPoint | QPointF], QPointF | None
        ],
    ) -> None:
        """Capture mask identity, scene, and generic layer transforms."""
        self._active_mask_id = active_mask_id
        self._active_scene = active_scene
        self._panel_to_scene = panel_to_scene
        self._layer_to_panel = layer_to_panel

    def panel_to_source(self, panel_point: QPoint | QPointF) -> QPointF | None:
        """Project a canvas panel point into unbounded mask-local space."""
        scene_point = self._panel_to_scene(panel_point)
        return None if scene_point is None else self.scene_to_source(scene_point)

    def scene_to_source(self, scene_point: QPoint | QPointF) -> QPointF | None:
        """Project a canvas scene point into unbounded mask-local space."""
        resolved = self._resolved_layer()
        if resolved is None:
            return None
        scene, layer = resolved
        bounds = scene.bounds
        if not (
            bounds.x <= scene_point.x() < bounds.x + bounds.width
            and bounds.y <= scene_point.y() < bounds.y + bounds.height
        ):
            return None
        transform = layer.transform
        if transform is None:
            return None
        return transform.inverse_map(QPointF(scene_point))

    def source_to_panel(self, source_point: QPoint | QPointF) -> QPointF | None:
        """Project active-mask source coordinates into panel space."""
        resolved = self._resolved_layer()
        if resolved is None:
            return None
        scene, layer = resolved
        raster_bounds = layer.raster_bounds
        if raster_bounds is None:
            return None
        storage_point = QPointF(
            source_point.x() - raster_bounds.x,
            source_point.y() - raster_bounds.y,
        )
        return self._layer_to_panel(scene.scene_id, layer.layer_id, storage_point)

    def _resolved_layer(self):
        """Return the active mask's resolved scene and layer descriptor."""
        mask_id = self._active_mask_id()
        scene = self._active_scene()
        if mask_id is None or scene is None:
            return None
        for layer in scene.layers:
            source = layer.source
            if isinstance(source, MaskLayerSource) and source.mask_id == mask_id:
                return scene, layer
        return None
