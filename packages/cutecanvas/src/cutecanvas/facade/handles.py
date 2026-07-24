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
"""Typed composition and layer handles over CuteCanvas's authoritative facade."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Protocol

from PySide6.QtCore import QPointF, QRectF, QSize
from PySide6.QtGui import QTransform
from qpane import LayerPresentationEffect, LayerPresentationStyle

from ..composition.geometry_policy import LayerGeometryPolicy
from ..types import (
    CompositionEntry,
    CompositionLayerEntry,
    CompositionPolicy,
    CompositionSnapshot,
    LayerPolicy,
    SceneSnapshot,
)


class EditorHandleHost(Protocol):
    """Describe existing facade operations consumed by typed editor handles."""

    def getCompositionSnapshot(self) -> CompositionSnapshot:
        """Return detached composition browser state."""
        ...

    def currentScene(self) -> SceneSnapshot | None:
        """Return the active scene snapshot."""
        ...

    def currentCompositionID(self) -> uuid.UUID | None:
        """Return the active composition identity."""
        ...

    def createComposition(
        self,
        bounds: QRectF,
        *,
        title: str = "Untitled",
        policy: CompositionPolicy | None = None,
        fit_view: bool = True,
    ) -> uuid.UUID:
        """Create one independent composition."""
        ...

    def openComposition(self, composition_id: uuid.UUID) -> None:
        """Open one existing composition."""
        ...

    def removeComposition(self, composition_id: uuid.UUID) -> None:
        """Remove one composition when host policy permits it."""
        ...

    def duplicateLayer(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> uuid.UUID | None:
        """Duplicate one layer instance while sharing its resource."""
        ...

    def forkLayerResource(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> uuid.UUID | None:
        """Redirect one layer to an independent resource copy."""
        ...

    def rasterizeLayer(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        pixel_size: QSize | None = None,
    ) -> uuid.UUID | None:
        """Convert one renderable layer resource into editable pixels."""
        ...

    def placeComposition(
        self,
        composition_id: uuid.UUID,
        *,
        placement: QRectF | None = None,
        label: str | None = None,
        interaction: LayerPolicy | None = None,
    ) -> uuid.UUID | None:
        """Place one composition resource in the active composition."""
        ...

    def setCompositionPolicy(
        self,
        composition_id: uuid.UUID,
        policy: CompositionPolicy,
    ) -> bool:
        """Replace host structural policy for one composition."""
        ...

    def setSelectedLayer(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Select one active-scene layer."""
        ...

    def setLayerTransform(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        transform: QTransform,
    ) -> bool:
        """Replace one layer's affine transform."""
        ...

    def setLayerVisible(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        visible: bool,
    ) -> bool:
        """Set one layer instance's composition-local visibility."""
        ...

    def translateLayer(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        offset: QPointF,
    ) -> bool:
        """Translate one layer by a scene-coordinate displacement."""
        ...

    def centerLayer(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        *,
        horizontally: bool = True,
        vertically: bool = True,
    ) -> bool:
        """Center one layer on selected composition-canvas axes."""
        ...

    def setLayerIndex(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        index: int,
    ) -> bool:
        """Move one layer to an ordered stack index."""
        ...

    def setLayerInteractionPolicy(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        policy: LayerPolicy,
    ) -> bool:
        """Replace user-facing layer interaction policy."""
        ...

    def setLayerGeometryPolicy(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        policy: LayerGeometryPolicy,
    ) -> bool:
        """Replace one layer's manipulation-geometry policy."""
        ...

    def removeLayer(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Remove one active-scene layer."""
        ...

    def addLayerPresentationEffect(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        style: LayerPresentationStyle,
        *,
        effect_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        """Add one transient renderer-owned layer effect."""
        ...

    def updateLayerPresentationEffect(
        self,
        effect_id: uuid.UUID,
        style: LayerPresentationStyle,
    ) -> bool:
        """Replace one transient effect style."""
        ...

    def removeLayerPresentationEffect(self, effect_id: uuid.UUID) -> bool:
        """Remove one transient effect when present."""
        ...

    def clearLayerPresentationEffects(
        self,
        *,
        scene_id: uuid.UUID | None = None,
        layer_id: uuid.UUID | None = None,
    ) -> int:
        """Remove matching transient effects."""
        ...

    def layerPresentationEffects(self) -> tuple[LayerPresentationEffect, ...]:
        """Return registered transient effects in deterministic order."""
        ...


class CompositionCollection:
    """Resolve composition handles without retaining parallel content state."""

    def __init__(self, host: EditorHandleHost) -> None:
        """Bind the authoritative host facade."""
        self._host = host

    def __iter__(self) -> Iterator[CompositionHandle]:
        """Iterate handles in browser order from one detached snapshot."""
        snapshot = self._host.getCompositionSnapshot()
        return iter(CompositionHandle(self._host, value) for value in snapshot.order)

    def __len__(self) -> int:
        """Return the current composition count."""
        return len(self._host.getCompositionSnapshot().order)

    @property
    def current(self) -> CompositionHandle | None:
        """Return the active composition handle, if any."""
        value = self._host.getCompositionSnapshot().current_composition_id
        return None if value is None else CompositionHandle(self._host, value)

    def get(self, composition_id: uuid.UUID) -> CompositionHandle | None:
        """Return a handle only when ``composition_id`` currently exists."""
        snapshot = self._host.getCompositionSnapshot()
        return (
            CompositionHandle(self._host, composition_id)
            if composition_id in snapshot.compositions
            else None
        )

    def create(
        self,
        bounds: QRectF,
        *,
        title: str = "Untitled",
        policy: CompositionPolicy | None = None,
        fit_view: bool = True,
    ) -> CompositionHandle:
        """Create, activate, and return one independent composition handle."""
        composition_id = self._host.createComposition(
            bounds,
            title=title,
            policy=policy,
            fit_view=fit_view,
        )
        return CompositionHandle(self._host, composition_id)


class CompositionHandle:
    """Identify one composition while resolving all state from its sole owner."""

    def __init__(self, host: EditorHandleHost, composition_id: uuid.UUID) -> None:
        """Bind stable composition identity without caching mutable state."""
        self._host = host
        self._composition_id = composition_id

    @property
    def id(self) -> uuid.UUID:
        """Return stable composition identity."""
        return self._composition_id

    @property
    def state(self) -> CompositionEntry:
        """Return current detached composition state or fail after removal."""
        entry = self._host.getCompositionSnapshot().compositions.get(
            self._composition_id
        )
        if entry is None:
            raise LookupError(f"composition {self._composition_id} no longer exists")
        return entry

    @property
    def is_open(self) -> bool:
        """Return whether this composition owns the active scene."""
        return (
            self._host.getCompositionSnapshot().current_composition_id
            == self._composition_id
        )

    @property
    def layers(self) -> tuple[LayerHandle, ...]:
        """Return typed layer handles in bottom-to-top stack order."""
        return tuple(
            LayerHandle(self._host, self._composition_id, layer.layer_id)
            for layer in self.state.layers
        )

    def open(self) -> None:
        """Make this composition active without changing its contents."""
        self._host.openComposition(self._composition_id)

    def remove(self) -> None:
        """Remove this composition when its host policy permits removal."""
        self._host.removeComposition(self._composition_id)

    def set_policy(self, policy: CompositionPolicy) -> bool:
        """Replace host structural policy for this composition."""
        return self._host.setCompositionPolicy(self._composition_id, policy)

    def layer(self, layer_id: uuid.UUID) -> LayerHandle | None:
        """Return a child handle only when the layer currently exists."""
        return next((layer for layer in self.layers if layer.id == layer_id), None)

    def place_composition(
        self,
        source: CompositionHandle,
        *,
        placement: QRectF | None = None,
        label: str | None = None,
        interaction: LayerPolicy | None = None,
    ) -> LayerHandle | None:
        """Place ``source`` as a live layer in this open composition."""
        if not isinstance(source, CompositionHandle):
            raise TypeError("source must be a CompositionHandle")
        if source._host is not self._host:
            raise ValueError("source must belong to the same CuteCanvas")
        if not self.is_open:
            raise RuntimeError(
                "open the destination composition before placing content"
            )
        layer_id = self._host.placeComposition(
            source.id,
            placement=placement,
            label=label,
            interaction=interaction,
        )
        return (
            None
            if layer_id is None
            else LayerHandle(self._host, self._composition_id, layer_id)
        )


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
        composition = CompositionHandle(self._host, self._composition_id).state
        entry = next(
            (layer for layer in composition.layers if layer.layer_id == self._layer_id),
            None,
        )
        if entry is None:
            raise LookupError(f"layer {self._layer_id} no longer exists")
        return entry

    def select(self) -> bool:
        """Select this layer in its open composition."""
        return self._host.setSelectedLayer(self._scene_id(), self._layer_id)

    def set_transform(self, transform: QTransform) -> bool:
        """Replace this layer's affine transform as one history edit."""
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


class LayerEffectHandle:
    """Identify one transient QPane-owned presentation effect."""

    def __init__(self, host: EditorHandleHost, effect_id: uuid.UUID) -> None:
        """Bind stable effect identity without caching renderer state."""
        self._host = host
        self._effect_id = effect_id

    @property
    def id(self) -> uuid.UUID:
        """Return stable transient effect identity."""
        return self._effect_id

    @property
    def state(self) -> LayerPresentationEffect:
        """Return the latest effect snapshot or fail after removal."""
        effect = next(
            (
                value
                for value in self._host.layerPresentationEffects()
                if value.effect_id == self._effect_id
            ),
            None,
        )
        if effect is None:
            raise LookupError(f"effect {self._effect_id} no longer exists")
        return effect

    def update(self, style: LayerPresentationStyle) -> bool:
        """Replace this effect's style while retaining draw order."""
        return self._host.updateLayerPresentationEffect(self._effect_id, style)

    def remove(self) -> bool:
        """Remove this effect when it remains registered."""
        return self._host.removeLayerPresentationEffect(self._effect_id)
