#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Vector-mask effect values, rendering, and composition transitions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainterPath

from ..composition.layer_edits import CompositionLayerEditService
from ..composition.layers import CompositionLayerInstance, CompositionLayerStore
from ..scene.affine import LayerTransform
from ..scene.effects import LayerEffectReference
from ..scene.raster import RasterBounds
from ..scene.source_references import LayerSourceReference
from .mask_cache import VectorMaskPathCache
from .projection import VectorDocumentProjection
from .source_reference import VectorDocumentReference
from .store import VectorAssetStore


@dataclass(frozen=True, slots=True)
class VectorMaskEffect:
    """Reference vector geometry mapped into one target layer's local space."""

    source: VectorDocumentReference
    transform: LayerTransform
    object_ids: tuple[uuid.UUID, ...] = ()
    inverted: bool = False

    def __post_init__(self) -> None:
        """Normalize stable unique object identities."""
        object.__setattr__(self, "object_ids", tuple(dict.fromkeys(self.object_ids)))

    @property
    def kind(self) -> str:
        """Return the stable layer-effect kind."""
        return "vector-mask"

    @property
    def retained_sources(self) -> tuple[LayerSourceReference, ...]:
        """Retain the referenced vector document while the effect is reachable."""
        return (self.source,)


class VectorMaskRenderOwner:
    """Derive target-local mask paths from authoritative vector geometry."""

    def __init__(
        self,
        projection: VectorDocumentProjection,
        paths: VectorMaskPathCache,
    ) -> None:
        """Bind the vector document owner."""
        self._projection = projection
        self._paths = paths

    def clip_path(
        self,
        effect: LayerEffectReference,
        target_bounds: RasterBounds,
    ) -> QPainterPath:
        """Return exact filled geometry, optionally inverted inside target bounds."""
        if not isinstance(effect, VectorMaskEffect):
            return QPainterPath()
        document = self._projection.document(effect.source.vector_id)
        if document is None:
            return QPainterPath()
        selected = frozenset(effect.object_ids) if effect.object_ids else None
        document_path = self._paths.path(document, selected)
        target_path = effect.transform.to_qtransform().map(document_path)
        if not effect.inverted:
            return target_path
        canvas = QPainterPath()
        canvas.addRect(QRectF(target_bounds.to_qrect()))
        return canvas.subtracted(target_path)


class VectorMaskController:
    """Own atomic vector-layer promotion into target layer effects."""

    def __init__(
        self,
        *,
        assets: VectorAssetStore,
        layers: CompositionLayerStore,
        layer_edits: CompositionLayerEditService,
    ) -> None:
        """Bind vector authority and the generic composition transition owner."""
        self._assets = assets
        self._layers = layers
        self._layer_edits = layer_edits

    def attach(
        self,
        composition_id: uuid.UUID,
        history_scope_id: uuid.UUID,
        vector_layer_id: uuid.UUID,
        target_layer_id: uuid.UUID,
        object_ids: tuple[uuid.UUID, ...],
        *,
        inverted: bool,
    ) -> bool:
        """Remove one vector instance and attach its source as one atomic mask."""
        if vector_layer_id == target_layer_id:
            return False
        stack = self._layers.layers_for_composition(composition_id)
        vector_layer = _layer(stack, vector_layer_id)
        target = _layer(stack, target_layer_id)
        if (
            vector_layer is None
            or target is None
            or not isinstance(vector_layer.source, VectorDocumentReference)
        ):
            return False
        document = self._assets.get(vector_layer.source.vector_id)
        if document is None or any(
            document.object(object_id) is None for object_id in object_ids
        ):
            return False
        scene_to_target = target.transform.inverted()
        if scene_to_target is None:
            return False
        document_to_target = vector_layer.transform.followed_by(scene_to_target)
        effect = VectorMaskEffect(
            vector_layer.source,
            document_to_target,
            object_ids,
            inverted,
        )
        retained_effects = tuple(
            candidate
            for candidate in target.effects
            if not isinstance(candidate, VectorMaskEffect)
        )
        replacement = replace(target, effects=(*retained_effects, effect))
        after = tuple(
            replacement if item.layer_id == target_layer_id else item
            for item in stack
            if item.layer_id != vector_layer_id
        )
        return self._layer_edits.replace_stack(
            composition_id,
            after,
            history_scope_id=history_scope_id,
        )

    def clear(
        self,
        composition_id: uuid.UUID,
        history_scope_id: uuid.UUID,
        target_layer_id: uuid.UUID,
    ) -> bool:
        """Remove a target's vector mask through one chronological transition."""
        stack = self._layers.layers_for_composition(composition_id)
        target = _layer(stack, target_layer_id)
        if target is None:
            return False
        effects = tuple(
            effect
            for effect in target.effects
            if not isinstance(effect, VectorMaskEffect)
        )
        if effects == target.effects:
            return False
        replacement = replace(target, effects=effects)
        after = tuple(
            replacement if item.layer_id == target_layer_id else item for item in stack
        )
        return self._layer_edits.replace_stack(
            composition_id,
            after,
            history_scope_id=history_scope_id,
        )

    def effect(
        self,
        composition_id: uuid.UUID,
        target_layer_id: uuid.UUID,
    ) -> VectorMaskEffect | None:
        """Return one target's immutable vector mask effect when present."""
        target = self._layers.layer(composition_id, target_layer_id)
        return (
            None
            if target is None
            else next(
                (
                    effect
                    for effect in target.effects
                    if isinstance(effect, VectorMaskEffect)
                ),
                None,
            )
        )


def _layer(
    stack: tuple[CompositionLayerInstance, ...],
    layer_id: uuid.UUID,
) -> CompositionLayerInstance | None:
    """Return one stable instance from an ordered stack snapshot."""
    return next((item for item in stack if item.layer_id == layer_id), None)
