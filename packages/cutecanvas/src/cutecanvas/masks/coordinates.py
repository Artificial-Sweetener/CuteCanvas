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

"""Coordinate mapping for the active editable mask layer."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import QPoint, QPointF
from qpane.sdk.rendering import (
    LayerLocalPoint,
    PanelPoint,
    SceneCoordinateSystem,
    ScenePoint,
)
from qpane.sdk.scene import LayerDescriptor, SceneDescriptor

from ..resources import ProjectResourceReference


class ActiveMaskLayerCoordinates:
    """Map through the active mask layer's resolved scene transform."""

    def __init__(
        self,
        *,
        active_mask_id: Callable[[], uuid.UUID | None],
        active_scene: Callable[[], SceneDescriptor | None],
        coordinates: SceneCoordinateSystem,
    ) -> None:
        """Capture mask identity, scene, and generic layer transforms."""
        self._active_mask_id = active_mask_id
        self._active_scene = active_scene
        self._coordinates = coordinates

    def panel_to_source(self, panel_point: QPoint | QPointF) -> QPointF | None:
        """Project a canvas panel point into unbounded mask-local space."""
        resolved = self._resolved_layer()
        if resolved is None:
            return None
        scene, layer = resolved
        local = self._coordinates.panel_to_layer_local(
            scene.scene_id,
            layer.layer_id,
            PanelPoint.from_qt(panel_point),
        )
        return None if local is None else local.to_qt()

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
        local = self._coordinates.scene_to_layer_local(
            ScenePoint.from_qt(scene.scene_id, scene_point),
            layer.layer_id,
        )
        return None if local is None else local.to_qt()

    def source_to_panel(self, source_point: QPoint | QPointF) -> QPointF | None:
        """Project active-mask source coordinates into panel space."""
        resolved = self._resolved_layer()
        if resolved is None:
            return None
        scene, layer = resolved
        panel = self._coordinates.layer_local_to_panel(
            LayerLocalPoint.from_qt(
                scene.scene_id,
                layer.layer_id,
                source_point,
            )
        )
        return None if panel is None else panel.to_qt()

    def _resolved_layer(
        self,
    ) -> tuple[SceneDescriptor, LayerDescriptor] | None:
        """Return the active mask's resolved scene and layer descriptor."""
        mask_id = self._active_mask_id()
        scene = self._active_scene()
        if mask_id is None or scene is None:
            return None
        for layer in scene.layers:
            source = layer.source
            if (
                isinstance(source, ProjectResourceReference)
                and source.resource_id == mask_id
            ):
                return scene, layer
        return None
