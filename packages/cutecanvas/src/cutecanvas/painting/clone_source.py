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
"""Resolve Clone Stamp source identity and rendered layer scope."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from qpane.sdk.rendering import SceneCoordinateSystem, ScenePoint
from qpane.sdk.scene import LayerDescriptor, SceneDescriptor

from .clone_model import (
    CloneStampSampleMode,
    CloneStampSource,
)


class CloneStampSourceResolver:
    """Own source-layer identity, availability, and scene-ordered scope."""

    def __init__(
        self,
        *,
        selected_layer: Callable[[], LayerDescriptor | None],
        coordinates: SceneCoordinateSystem,
    ) -> None:
        """Bind selection observation and authoritative scene coordinates."""
        self._selected_layer = selected_layer
        self._coordinates = coordinates

    def create(
        self,
        scene: SceneDescriptor,
        scene_point: ScenePoint,
        mode: CloneStampSampleMode,
        *,
        preferred_layer_id: uuid.UUID | None = None,
        allow_selected_fallback: bool = True,
    ) -> CloneStampSource | None:
        """Create one source with optional rendered-layer identity."""
        if scene_point.scene_id != scene.scene_id:
            return None
        layer = self._layer_by_id(scene, preferred_layer_id)
        if layer is None and allow_selected_fallback:
            selected = self._selected_layer()
            layer = (
                selected
                if selected is not None and selected.scene_id == scene.scene_id
                else None
            )
        if mode is not CloneStampSampleMode.VISIBLE_COMPOSITE and (
            layer is None or not layer.visible or layer.opacity <= 0.0
        ):
            return None
        layer_point = (
            None
            if layer is None
            else self._coordinates.scene_to_layer_source(
                scene_point,
                layer.layer_id,
            )
        )
        if (
            mode is not CloneStampSampleMode.VISIBLE_COMPOSITE
            and layer is not None
            and layer_point is None
        ):
            return None
        if layer_point is None:
            layer = None
        return CloneStampSource(
            scene.scene_id,
            (scene_point.x, scene_point.y),
            None if layer is None else layer.layer_id,
            None if layer_point is None else (layer_point.x, layer_point.y),
        )

    def for_mode(
        self,
        source: CloneStampSource | None,
        scene: SceneDescriptor | None,
        mode: CloneStampSampleMode,
    ) -> CloneStampSource | None:
        """Retain a canvas anchor while resolving required layer identity."""
        if source is None or scene is None or source.scene_id != scene.scene_id:
            return None
        return self.create(
            scene,
            ScenePoint.from_qt(scene.scene_id, source.scene_point()),
            mode,
            preferred_layer_id=source.layer_id,
            allow_selected_fallback=False,
        )

    def is_valid(
        self,
        source: CloneStampSource | None,
        scene: SceneDescriptor,
        mode: CloneStampSampleMode,
    ) -> bool:
        """Return whether the active scene can still produce this source."""
        if source is None or source.scene_id != scene.scene_id:
            return False
        if mode is CloneStampSampleMode.VISIBLE_COMPOSITE:
            return True
        layer = self._layer_by_id(scene, source.layer_id)
        return layer is not None and layer.visible and layer.opacity > 0.0

    @staticmethod
    def layer_scope(
        scene: SceneDescriptor,
        source: CloneStampSource,
        mode: CloneStampSampleMode,
    ) -> frozenset[uuid.UUID] | None:
        """Return the scene-ordered layer range sampled by one stroke."""
        if mode is CloneStampSampleMode.VISIBLE_COMPOSITE:
            return None
        if source.layer_id is None:
            return frozenset()
        if mode is CloneStampSampleMode.ANCHORED_LAYER:
            return frozenset({source.layer_id})
        layer_ids: list[uuid.UUID] = []
        for layer in scene.layers:
            layer_ids.append(layer.layer_id)
            if layer.layer_id == source.layer_id:
                return frozenset(layer_ids)
        return frozenset()

    @staticmethod
    def _layer_by_id(
        scene: SceneDescriptor,
        layer_id: uuid.UUID | None,
    ) -> LayerDescriptor | None:
        """Return one exact layer descriptor from an immutable scene."""
        if layer_id is None:
            return None
        return next(
            (layer for layer in scene.layers if layer.layer_id == layer_id),
            None,
        )
