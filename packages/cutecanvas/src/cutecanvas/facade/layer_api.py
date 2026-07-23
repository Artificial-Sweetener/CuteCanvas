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

"""Public generic layer presentation and alignment commands."""

from __future__ import annotations

import uuid
from dataclasses import replace

from PySide6.QtCore import QPointF
from PySide6.QtGui import QTransform


class LayerApiMixin:
    """Expose source-neutral layer commands through composition ownership."""

    def setLayerVisible(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        visible: bool,
    ) -> bool:
        """Set whether one active composition layer renders and hit-tests.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the layer instance.
            visible: Whether the layer participates in rendering and hit testing.

        Returns:
            True when visibility changed and one history command was recorded.
        """
        _validate_layer_ids(scene_id, layer_id)
        if not isinstance(visible, bool):
            raise TypeError("visible must be a bool")
        if not self._anchor_floating_pixels_before_edit():
            return False
        resolved_scene_id = self._resolve_public_scene_id(scene_id)
        service = self.compositionService()
        instance = service.layers.layer(resolved_scene_id, layer_id)
        if instance is None or not service.layer_edits.replace_instance(
            resolved_scene_id,
            replace(instance, visible=visible),
        ):
            return False
        self._publish_scene_layer_change()
        return True

    def translateLayer(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        offset: QPointF,
    ) -> bool:
        """Translate one movable layer in scene coordinates without distortion.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the layer instance.
            offset: Scene-coordinate displacement to add to the exact transform.

        Returns:
            True when the transform changed and one history command was recorded.
        """
        _validate_layer_ids(scene_id, layer_id)
        if not isinstance(offset, QPointF):
            raise TypeError("offset must be a QPointF")
        transform = self.layerTransform(scene_id, layer_id)
        if transform is None:
            return False
        translated = transform * QTransform.fromTranslate(offset.x(), offset.y())
        return self.setLayerTransform(scene_id, layer_id, translated)

    def centerLayer(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        *,
        horizontally: bool = True,
        vertically: bool = True,
    ) -> bool:
        """Center one movable layer on selected axes of the composition canvas.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the layer instance.
            horizontally: Align the layer and canvas horizontal centers.
            vertically: Align the layer and canvas vertical centers.

        Returns:
            True when the transform changed and one history command was recorded.
        """
        _validate_layer_ids(scene_id, layer_id)
        if not isinstance(horizontally, bool) or not isinstance(vertically, bool):
            raise TypeError("centering axis flags must be bool values")
        if not horizontally and not vertically:
            return False
        scene = self.currentScene()
        transform = self.layerTransform(scene_id, layer_id)
        local_bounds = self.layerLocalBounds(scene_id, layer_id)
        if scene is None or transform is None or local_bounds is None:
            return False
        mapped_bounds = transform.mapRect(local_bounds)
        canvas_center = scene.bounds.center()
        layer_center = mapped_bounds.center()
        offset = QPointF(
            canvas_center.x() - layer_center.x() if horizontally else 0.0,
            canvas_center.y() - layer_center.y() if vertically else 0.0,
        )
        return self.translateLayer(scene_id, layer_id, offset)


def _validate_layer_ids(scene_id: uuid.UUID, layer_id: uuid.UUID) -> None:
    """Reject invalid public layer identifiers consistently."""
    if not isinstance(scene_id, uuid.UUID) or not isinstance(layer_id, uuid.UUID):
        raise TypeError("scene_id and layer_id must be UUIDs")
