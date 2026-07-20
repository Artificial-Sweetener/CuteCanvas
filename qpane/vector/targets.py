#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Resolve vector documents authored as layers or composition effects."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF
from PySide6.QtGui import QTransform

from ..composition.layers import CompositionLayerStore
from ..scene.affine import LayerTransform
from ..scene.model import SceneDescriptor
from .effects import VectorMaskEffect
from .source_reference import VectorDocumentReference
from .store import VectorAssetStore


@dataclass(frozen=True, slots=True)
class VectorAuthoringTarget:
    """Identify one live vector document and its mapping into a selected layer."""

    composition_id: uuid.UUID
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    vector_id: uuid.UUID
    document_to_layer: LayerTransform
    is_mask: bool


class VectorAuthoringTargetResolver:
    """Resolve one vector authority regardless of its composition role."""

    def __init__(
        self,
        *,
        assets: VectorAssetStore,
        layers: CompositionLayerStore,
        current_composition_id: Callable[[], uuid.UUID | None],
        current_scene: Callable[[], SceneDescriptor | None],
        panel_to_source: Callable[[uuid.UUID, uuid.UUID, QPointF], QPointF | None],
        source_to_panel: Callable[[uuid.UUID, uuid.UUID, QPointF], QPointF | None],
    ) -> None:
        """Bind composition, scene, coordinate, and vector owners."""
        self._assets = assets
        self._layers = layers
        self._current_composition_id = current_composition_id
        self._current_scene = current_scene
        self._panel_to_source = panel_to_source
        self._source_to_panel = source_to_panel

    def resolve(self, layer_id: uuid.UUID) -> VectorAuthoringTarget | None:
        """Resolve a direct vector layer or a layer carrying a vector mask."""
        composition_id = self._current_composition_id()
        scene = self._current_scene()
        if composition_id is None or scene is None:
            return None
        instance = self._layers.layer(composition_id, layer_id)
        if instance is None:
            return None
        if isinstance(instance.source, VectorDocumentReference):
            source = instance.source
            mapping = LayerTransform()
            is_mask = False
        else:
            effect = next(
                (
                    candidate
                    for candidate in instance.effects
                    if isinstance(candidate, VectorMaskEffect)
                ),
                None,
            )
            if effect is None:
                return None
            source = effect.source
            mapping = effect.transform
            is_mask = True
        if self._assets.get(source.vector_id) is None:
            return None
        return VectorAuthoringTarget(
            composition_id,
            scene.scene_id,
            layer_id,
            source.vector_id,
            mapping,
            is_mask,
        )

    def panel_to_document(
        self,
        target: VectorAuthoringTarget,
        panel_point: QPointF,
    ) -> QPointF | None:
        """Map panel input through the selected layer into vector document space."""
        layer_point = self._panel_to_source(
            target.scene_id,
            target.layer_id,
            panel_point,
        )
        return (
            None
            if layer_point is None
            else target.document_to_layer.inverse_map(layer_point)
        )

    def document_to_panel(
        self,
        target: VectorAuthoringTarget,
        document_point: QPointF,
    ) -> QPointF | None:
        """Map one vector-document point through its selected layer to panel space."""
        return self._source_to_panel(
            target.scene_id,
            target.layer_id,
            target.document_to_layer.map_point(document_point),
        )

    def document_to_panel_transform(
        self,
        target: VectorAuthoringTarget,
    ) -> QTransform | None:
        """Derive the exact affine document-to-panel transform for overlays."""
        origin = self.document_to_panel(target, QPointF())
        axis_x = self.document_to_panel(target, QPointF(1.0, 0.0))
        axis_y = self.document_to_panel(target, QPointF(0.0, 1.0))
        if origin is None or axis_x is None or axis_y is None:
            return None
        return QTransform(
            axis_x.x() - origin.x(),
            axis_x.y() - origin.y(),
            axis_y.x() - origin.x(),
            axis_y.y() - origin.y(),
            origin.x(),
            origin.y(),
        )
