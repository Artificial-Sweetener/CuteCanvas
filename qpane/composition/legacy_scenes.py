#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Adapt legacy catalog-scene requests into composition documents."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping

from PySide6.QtCore import QRectF

from ..scene.affine import LayerTransform
from ..scene.model import ClipCoordinateSpace, LayerClip, LayerPlacement
from ..scene.raster import RasterBounds
from ..scene.source_references import LayerSourceReference
from ..types import (
    QPaneCatalogImageLayerRequest,
    QPaneSceneClip,
    QPaneSceneRequest,
    QPaneSceneTemplate,
    QPaneSceneTemplateBindings,
)
from .layers import CompositionLayerInstance
from .model import (
    CompositionDocumentPolicy,
    CompositionOrigin,
    CompositionRecord,
)
from .public_policy import internal_layer_policy, public_layer_policy

_VALID_CLIP_SPACES = {
    "scene",
    "normalized-scene",
    "viewport",
    "normalized-viewport",
}


class LegacySceneCompositionAdapter:
    """Validate public scene values and project them into one document model."""

    def __init__(
        self,
        *,
        catalog_bounds: Callable[[uuid.UUID], RasterBounds],
        catalog_source: Callable[[uuid.UUID], LayerSourceReference],
    ) -> None:
        """Bind catalog capability lookups used by legacy scene requests."""
        self._catalog_bounds = catalog_bounds
        self._catalog_source = catalog_source

    def document_from_request(
        self,
        request: QPaneSceneRequest,
        *,
        catalog_contains: Callable[[uuid.UUID], bool],
    ) -> tuple[CompositionRecord, tuple[CompositionLayerInstance, ...]]:
        """Validate one request and return its document and ordinary layers."""
        if not isinstance(request, QPaneSceneRequest):
            raise TypeError("request must be a QPaneSceneRequest")
        if request.composition_id is not None and not isinstance(
            request.composition_id, uuid.UUID
        ):
            raise TypeError("composition_id must be a UUID")
        if request.title is not None and not isinstance(request.title, str):
            raise TypeError("title must be a string")
        if request.bounds.width() <= 0.0 or request.bounds.height() <= 0.0:
            raise ValueError("scene bounds must be positive")
        if not request.layers:
            raise ValueError("scene layers must not be empty")
        layer_ids: set[uuid.UUID] = set()
        layers: list[CompositionLayerInstance] = []
        visible_positive = False
        for layer in request.layers:
            normalized = self._normalize_layer(
                layer,
                catalog_contains=catalog_contains,
            )
            if normalized.layer_id in layer_ids:
                raise ValueError("scene layer IDs must be unique")
            layer_ids.add(normalized.layer_id)
            placement = normalized.transform.map_bounds(
                self._catalog_bounds(normalized.source.resource_id)
            )
            visible_positive = visible_positive or (
                normalized.visible and placement.width > 0.0 and placement.height > 0.0
            )
            layers.append(normalized)
        if not visible_positive:
            raise ValueError("scene requests require a visible positive-area layer")
        record = CompositionRecord(
            composition_id=request.composition_id or uuid.uuid4(),
            origin=CompositionOrigin.LAYERED_SCENE,
            title=(
                request.title.strip()
                if request.title and request.title.strip()
                else "Scene"
            ),
            canvas_bounds=QRectF(request.bounds),
            policy=CompositionDocumentPolicy(
                comparison_enabled=False,
                remove_if_catalog_resource_missing=True,
            ),
        )
        return record, tuple(layers)

    def request_from_template(
        self,
        template: QPaneSceneTemplate,
        bindings: QPaneSceneTemplateBindings,
    ) -> QPaneSceneRequest:
        """Validate a legacy template and expand it into one scene request."""
        if not isinstance(template, QPaneSceneTemplate):
            raise TypeError("template must be a QPaneSceneTemplate")
        if not isinstance(bindings, QPaneSceneTemplateBindings):
            raise TypeError("bindings must be a QPaneSceneTemplateBindings")
        if not isinstance(template.template_id, uuid.UUID):
            raise TypeError("template_id must be a UUID")
        if bindings.composition_id is not None and not isinstance(
            bindings.composition_id, uuid.UUID
        ):
            raise TypeError("composition_id must be a UUID")
        if template.bounds.width() <= 0.0 or template.bounds.height() <= 0.0:
            raise ValueError("template bounds must be positive")
        if not template.layers:
            raise ValueError("template layers must not be empty")
        layer_ids: set[uuid.UUID] = set()
        request_layers: list[QPaneCatalogImageLayerRequest] = []
        for layer in template.layers:
            if not isinstance(layer.layer_id, uuid.UUID):
                raise TypeError("template layer_id must be a UUID")
            if layer.layer_id in layer_ids:
                raise ValueError("template layer IDs must be unique")
            layer_ids.add(layer.layer_id)
            if not isinstance(layer.source_slot, str) or not layer.source_slot:
                raise ValueError("template source_slot must be a non-empty string")
            if layer.source_slot not in bindings.catalog_images:
                raise ValueError("template source_slot is missing a catalog binding")
            image_id = bindings.catalog_images[layer.source_slot]
            if not isinstance(image_id, uuid.UUID):
                raise TypeError("bound catalog image IDs must be UUIDs")
            binding_metadata = bindings.metadata.get(layer.source_slot, {})
            if not isinstance(binding_metadata, Mapping):
                raise TypeError("template binding metadata values must be mappings")
            metadata = dict(layer.metadata)
            metadata.update(dict(binding_metadata))
            request_layers.append(
                QPaneCatalogImageLayerRequest(
                    layer_id=layer.layer_id,
                    image_id=image_id,
                    placement=QRectF(layer.placement),
                    visible=layer.visible,
                    opacity=layer.opacity,
                    clip=_copy_scene_clip(layer.clip),
                    hit_test=layer.hit_test,
                    interaction=public_layer_policy(layer.interaction),
                    role=layer.role,
                    metadata=metadata,
                )
            )
        return QPaneSceneRequest(
            composition_id=bindings.composition_id,
            title=bindings.title if bindings.title is not None else template.title,
            bounds=QRectF(template.bounds),
            layers=tuple(request_layers),
        )

    def _normalize_layer(
        self,
        layer: QPaneCatalogImageLayerRequest,
        *,
        catalog_contains: Callable[[uuid.UUID], bool],
    ) -> CompositionLayerInstance:
        """Validate one catalog layer and return its ordinary instance value."""
        if not isinstance(layer, QPaneCatalogImageLayerRequest):
            raise TypeError(
                "scene layers must be QPaneCatalogImageLayerRequest instances"
            )
        if not isinstance(layer.layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not isinstance(layer.image_id, uuid.UUID):
            raise TypeError("image_id must be a UUID")
        if not catalog_contains(layer.image_id):
            raise KeyError("scene layer image_id must exist in the catalog")
        if layer.placement.width() < 0.0 or layer.placement.height() < 0.0:
            raise ValueError("layer placement dimensions must be non-negative")
        if not 0.0 <= layer.opacity <= 1.0:
            raise ValueError("layer opacity must be between 0.0 and 1.0")
        if not isinstance(layer.role, str):
            raise TypeError("layer role must be a string")
        _validate_clip(layer.clip)
        bounds = self._catalog_bounds(layer.image_id)
        placement = LayerPlacement(
            layer.placement.x(),
            layer.placement.y(),
            layer.placement.width(),
            layer.placement.height(),
        )
        return CompositionLayerInstance(
            layer_id=layer.layer_id,
            source=self._catalog_source(layer.image_id),
            transform=LayerTransform.from_placement(bounds, placement),
            visible=bool(layer.visible),
            opacity=float(layer.opacity),
            hit_test=bool(layer.hit_test),
            interaction=internal_layer_policy(layer.interaction),
            role=layer.role,
            metadata=dict(layer.metadata),
            clip=_internal_clip(layer.clip),
        )


def _validate_clip(clip: QPaneSceneClip | None) -> None:
    """Validate clip geometry used by a legacy public scene layer."""
    if clip is None:
        return
    if clip.coordinate_space not in _VALID_CLIP_SPACES:
        raise ValueError(
            f"unsupported scene clip coordinate space: {clip.coordinate_space}"
        )
    if clip.rect.width() < 0.0 or clip.rect.height() < 0.0:
        raise ValueError("layer clip dimensions must be non-negative")


def _copy_scene_clip(clip: QPaneSceneClip | None) -> QPaneSceneClip | None:
    """Return a detached copy of a public scene clip."""
    if clip is None:
        return None
    return QPaneSceneClip(
        coordinate_space=clip.coordinate_space,
        rect=QRectF(clip.rect),
    )


def _internal_clip(clip: QPaneSceneClip | None) -> LayerClip | None:
    """Convert detached public clip geometry into internal scene values."""
    if clip is None:
        return None
    return LayerClip(
        coordinate_space=ClipCoordinateSpace(clip.coordinate_space),
        x=clip.rect.x(),
        y=clip.rect.y(),
        width=clip.rect.width(),
        height=clip.rect.height(),
    )
