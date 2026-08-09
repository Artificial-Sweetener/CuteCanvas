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
"""Typed handles for composition layer workflows."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QTransform
from qpane import LayerMapping, LayerPresentationStyle

from ..composition.geometry_policy import LayerGeometryPolicy
from ..types import CompositionLayerEntry, LayerPolicy
from .effect_handles import LayerEffectHandle
from .handles import EditorHandleHost


class LayerHandle:
    """Identify one composition layer and route edits through the active scene."""

    def __init__(
        self,
        host: EditorHandleHost,
        composition_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> None:
        """Bind stable composition and layer identities without caching state."""
        self._host = host
        self._composition_id = composition_id
        self._layer_id = layer_id

    @property
    def id(self) -> uuid.UUID:
        """Return stable layer-instance identity."""
        return self._layer_id

    @property
    def composition_id(self) -> uuid.UUID:
        """Return the composition containing this layer instance."""
        return self._composition_id

    @property
    def resource_id(self) -> uuid.UUID:
        """Return the project resource referenced by this layer."""
        return self.state.source_id

    @property
    def scene_id(self) -> uuid.UUID:
        """Return the active render-scene identity for this open layer."""
        return self._scene_id()

    @property
    def state(self) -> CompositionLayerEntry:
        """Return the latest detached layer state or fail after removal."""
        composition = self._host.getCompositionSnapshot().compositions.get(
            self._composition_id
        )
        entry = (
            None
            if composition is None
            else next(
                (
                    layer
                    for layer in composition.layers
                    if layer.layer_id == self._layer_id
                ),
                None,
            )
        )
        if entry is None:
            raise LookupError(f"layer {self._layer_id} no longer exists")
        return entry

    def select(self) -> bool:
        """Select this layer in its open composition."""
        return self._host.setSelectedLayer(self._scene_id(), self._layer_id)

    def set_transform(self, transform: QTransform | LayerMapping) -> bool:
        """Replace this layer's exact mapping as one history edit."""
        return self._host.setLayerTransform(
            self._scene_id(),
            self._layer_id,
            transform,
        )

    def set_visible(self, visible: bool) -> bool:
        """Set whether this layer renders and hit-tests in its composition."""
        return self._host.setLayerVisible(
            self._scene_id(),
            self._layer_id,
            visible,
        )

    def set_opacity(self, opacity: float) -> bool:
        """Set this layer's visual-only presentation multiplier."""
        return self._host.setLayerOpacity(
            self._scene_id(),
            self._layer_id,
            opacity,
        )

    def translate(self, offset: QPointF) -> bool:
        """Translate this layer by one scene-coordinate displacement."""
        return self._host.translateLayer(
            self._scene_id(),
            self._layer_id,
            offset,
        )

    def center(
        self,
        *,
        horizontally: bool = True,
        vertically: bool = True,
    ) -> bool:
        """Center this layer on selected axes of its composition canvas."""
        return self._host.centerLayer(
            self._scene_id(),
            self._layer_id,
            horizontally=horizontally,
            vertically=vertically,
        )

    def move_to(self, index: int) -> bool:
        """Move this layer to ``index`` in the open composition stack."""
        return self._host.setLayerIndex(self._scene_id(), self._layer_id, index)

    def set_policy(self, policy: LayerPolicy) -> bool:
        """Replace this layer's user-facing interaction policy."""
        return self._host.setLayerInteractionPolicy(
            self._scene_id(),
            self._layer_id,
            policy,
        )

    def set_geometry(self, policy: LayerGeometryPolicy) -> bool:
        """Replace manipulation bounds through the authoritative host facade."""
        return self._host.setLayerGeometryPolicy(
            self._scene_id(),
            self._layer_id,
            policy,
        )

    def remove(self) -> bool:
        """Remove this layer from its open composition as one history edit."""
        return self._host.removeLayer(self._scene_id(), self._layer_id)

    def duplicate(self) -> LayerHandle | None:
        """Create another layer instance sharing this layer's resource."""
        layer_id = self._host.duplicateLayer(self._scene_id(), self._layer_id)
        return (
            None
            if layer_id is None
            else LayerHandle(self._host, self._composition_id, layer_id)
        )

    def fork_resource(self) -> uuid.UUID | None:
        """Redirect this layer to an independent copy of its resource."""
        return self._host.forkLayerResource(self._scene_id(), self._layer_id)

    def rasterize(self, pixel_size: QSize | None = None) -> uuid.UUID | None:
        """Convert this layer's renderable resource into editable pixels."""
        return self._host.rasterizeLayer(
            self._scene_id(),
            self._layer_id,
            pixel_size,
        )

    def add_effect(self, style: LayerPresentationStyle) -> LayerEffectHandle:
        """Add a transient visual treatment without changing composition content."""
        effect_id = self._host.addLayerPresentationEffect(
            self._scene_id(),
            self._layer_id,
            style,
        )
        return LayerEffectHandle(self._host, effect_id)

    def _scene_id(self) -> uuid.UUID:
        """Return the active scene ID and reject edits to an inactive composition."""
        if self._host.currentCompositionID() != self._composition_id:
            raise RuntimeError("open the layer's composition before editing it")
        return self._composition_id


__all__ = ["LayerHandle"]
