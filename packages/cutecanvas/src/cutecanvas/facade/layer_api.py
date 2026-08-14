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

import math
import uuid
from dataclasses import replace

from PySide6.QtCore import QPointF

from cutecanvas.types import LayerEdgeOperation
from qpane.sdk.scene import LayerTransform, compose_layer_mappings


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
        return bool(
            instance is not None
            and service.layer_edits.replace_instance(
                resolved_scene_id,
                replace(instance, visible=visible),
            )
        )

    def setLayerOpacity(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        opacity: float,
    ) -> bool:
        """Set one layer's final visual-only presentation multiplier.

        The multiplier is applied after source coverage presentation. It does not
        rewrite scalar coverage, brush hardness, or authored paint opacity.
        """
        _validate_layer_ids(scene_id, layer_id)
        if isinstance(opacity, bool):
            raise TypeError("opacity must be numeric")
        try:
            normalized = float(opacity)
        except (TypeError, ValueError) as exc:
            raise TypeError("opacity must be numeric") from exc
        if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
            raise ValueError("opacity must be finite and between 0.0 and 1.0")
        resolved = self._resolve_public_scene_id(scene_id)
        result = self.sceneMutationCoordinator().set_opacity(
            resolved,
            layer_id,
            normalized,
        )
        return bool(result.accepted and result.changed)

    def beginLayerEdgePreview(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> uuid.UUID | None:
        """Begin a canvas-bounded edge preview from the layer's current revision."""
        _validate_layer_ids(scene_id, layer_id)
        return self.layerEdgeModificationCoordinator().begin(
            self._resolve_public_scene_id(scene_id),
            layer_id,
        )

    def updateLayerEdgePreview(
        self,
        session_id: uuid.UUID,
        operation: LayerEdgeOperation,
        radius: float,
    ) -> uuid.UUID | None:
        """Replace a preview session's pending value with the latest request."""
        if not isinstance(session_id, uuid.UUID):
            raise TypeError("session_id must be a UUID")
        if not isinstance(operation, LayerEdgeOperation):
            raise TypeError("operation must be LayerEdgeOperation")
        return self.layerEdgeModificationCoordinator().update(
            session_id,
            operation,
            radius,
        )

    def settleLayerEdgePreview(self, session_id: uuid.UUID) -> bool:
        """Commit the latest preview once as soon as its product is ready."""
        if not isinstance(session_id, uuid.UUID):
            raise TypeError("session_id must be a UUID")
        return self.layerEdgeModificationCoordinator().settle(session_id)

    def cancelLayerEdgePreview(self, session_id: uuid.UUID) -> bool:
        """Discard a preview session without changing authoritative content."""
        if not isinstance(session_id, uuid.UUID):
            raise TypeError("session_id must be a UUID")
        return self.layerEdgeModificationCoordinator().cancel(session_id)

    def expandLayerEdges(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        pixels: int,
    ) -> uuid.UUID | None:
        """Expand coverage inside the canvas as one asynchronous undoable edit."""
        return self._request_layer_edge_operation(
            scene_id,
            layer_id,
            LayerEdgeOperation.EXPAND,
            _positive_whole_pixels(pixels),
        )

    def contractLayerEdges(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        pixels: int,
    ) -> uuid.UUID | None:
        """Contract coverage inside the canvas as one asynchronous undoable edit."""
        return self._request_layer_edge_operation(
            scene_id,
            layer_id,
            LayerEdgeOperation.CONTRACT,
            _positive_whole_pixels(pixels),
        )

    def featherLayerEdges(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        radius: float,
    ) -> uuid.UUID | None:
        """Feather coverage inside the canvas as one asynchronous undoable edit."""
        return self._request_layer_edge_operation(
            scene_id,
            layer_id,
            LayerEdgeOperation.FEATHER,
            radius,
        )

    def _request_layer_edge_operation(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        operation: LayerEdgeOperation,
        radius: float,
    ) -> uuid.UUID | None:
        """Resolve public IDs and submit one generic layer edge operation."""
        _validate_layer_ids(scene_id, layer_id)
        return self.layerEdgeModificationCoordinator().request(
            self._resolve_public_scene_id(scene_id),
            layer_id,
            operation,
            radius,
        )

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
        if self.currentCompositionID() != scene_id:
            return False
        instance = self.compositionService().layers.layer(scene_id, layer_id)
        if instance is None:
            return False
        translated = compose_layer_mappings(
            instance.transform,
            LayerTransform(dx=offset.x(), dy=offset.y()),
        )
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
        if self.currentCompositionID() != scene_id:
            return False
        service = self.compositionService()
        try:
            record = service.record(scene_id)
        except KeyError:
            return False
        instance = service.layers.layer(scene_id, layer_id)
        active_scene = self.sceneMutationCoordinator().active_scene()
        layer = (
            None
            if active_scene is None or active_scene.scene_id != scene_id
            else next(
                (
                    candidate
                    for candidate in active_scene.layers
                    if candidate.layer_id == layer_id
                ),
                None,
            )
        )
        local_bounds = (
            None
            if layer is None
            else self.layerGeometryResolver().resolved_local_bounds(layer)
        )
        if instance is None or local_bounds is None:
            return False
        transform = instance.transform
        mapped_bounds = transform.map_rect(local_bounds)
        canvas_center = record.canvas_bounds.center()
        layer_center = mapped_bounds.center()
        offset = QPointF(
            canvas_center.x() - layer_center.x() if horizontally else 0.0,
            canvas_center.y() - layer_center.y() if vertically else 0.0,
        )
        translated = compose_layer_mappings(
            transform,
            LayerTransform(dx=offset.x(), dy=offset.y()),
        )
        return self.setLayerTransform(scene_id, layer_id, translated)


def _validate_layer_ids(scene_id: uuid.UUID, layer_id: uuid.UUID) -> None:
    """Reject invalid public layer identifiers consistently."""
    if not isinstance(scene_id, uuid.UUID) or not isinstance(layer_id, uuid.UUID):
        raise TypeError("scene_id and layer_id must be UUIDs")


def _positive_whole_pixels(pixels: int) -> float:
    """Require a positive non-boolean whole-pixel distance."""
    if isinstance(pixels, bool) or not isinstance(pixels, int):
        raise TypeError("edge distance must be an integer")
    if pixels <= 0:
        raise ValueError("edge distance must be positive")
    return float(pixels)
