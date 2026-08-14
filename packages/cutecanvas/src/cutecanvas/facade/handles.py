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
"""Typed host contract consumed by CuteCanvas editor handles."""

from __future__ import annotations

import uuid
from typing import Protocol

from PySide6.QtCore import QPointF, QRectF, QSize
from PySide6.QtGui import QTransform

from qpane import LayerMapping, LayerPresentationEffect, LayerPresentationStyle

from ..composition.geometry_policy import LayerGeometryPolicy
from ..document import CanvasAnchor, CanvasResamplingMode
from ..types import (
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

    def resizeCanvasBounds(
        self,
        composition_id: uuid.UUID,
        size: QSize,
        *,
        anchor: CanvasAnchor = CanvasAnchor.CENTER,
    ) -> bool:
        """Resize canvas bounds without resampling content."""
        ...

    def requestCanvasResampling(
        self,
        composition_id: uuid.UUID,
        size: QSize,
        *,
        mode: CanvasResamplingMode = CanvasResamplingMode.SMOOTH,
    ) -> uuid.UUID:
        """Begin source-aware whole-canvas resampling."""
        ...

    def cropLayersToCanvas(self, composition_id: uuid.UUID) -> bool:
        """Clip every layer to the current canvas."""
        ...

    def setSelectedLayer(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Select one active-scene layer."""
        ...

    def setLayerTransform(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        transform: QTransform | LayerMapping,
    ) -> bool:
        """Replace one layer's complete local-to-scene mapping."""
        ...

    def setLayerVisible(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        visible: bool,
    ) -> bool:
        """Set one layer instance's composition-local visibility."""
        ...

    def setLayerOpacity(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        opacity: float,
    ) -> bool:
        """Set one layer instance's visual-only presentation multiplier."""
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


__all__ = ["EditorHandleHost"]
