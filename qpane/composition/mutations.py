#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Scene mutation ownership for composition-managed layer instances."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from ..scene.model import (
    LayerDescriptor,
    LayerInteractionPolicy,
    LayerPlacement,
    SceneDescriptor,
)
from ..scene.mutations import (
    BaseSceneMutationOwner,
    SceneMutationResult,
    SceneMutationStatus,
)
from ..scene.raster import LayerTransform
from ..scene.sources import CatalogImageSource, MaskLayerSource
from .layers import ImageSceneLayerStore
from .service import CompositionService


class ImageSceneMaskMutationOwner(BaseSceneMutationOwner):
    """Apply mask-source mutations to default image-scene layer state."""

    name = "image-scene-mask"

    def __init__(
        self,
        layers: ImageSceneLayerStore,
        current_image_id: Callable[[], uuid.UUID | None],
        *,
        remove_mask: Callable[[uuid.UUID, uuid.UUID], bool],
        notify_mask_opacity: Callable[[uuid.UUID], None],
        request_mask_revision: Callable[[uuid.UUID, str], bool],
    ) -> None:
        """Bind composition state and mask asset lifecycle callbacks."""
        self._layers = layers
        self._current_image_id = current_image_id
        self._remove_mask = remove_mask
        self._notify_mask_opacity = notify_mask_opacity
        self._request_mask_revision = request_mask_revision

    def supports_layer(self, scene: SceneDescriptor, layer: LayerDescriptor) -> bool:
        """Return True for composition-backed mask instances."""
        return isinstance(layer.source, MaskLayerSource)

    def remove_layer(
        self, scene: SceneDescriptor, layer: LayerDescriptor
    ) -> SceneMutationResult:
        """Remove one layer instance and let its source owner prune orphans."""
        image_id = self._current_image_id()
        source = layer.source
        changed = bool(
            image_id is not None
            and isinstance(source, MaskLayerSource)
            and self._remove_mask(image_id, source.mask_id)
        )
        return _mutation_result(self.name, scene, layer, changed, "layer removed")

    def reorder_layer(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        target_index: int,
    ) -> SceneMutationResult:
        """Move one instance to an exact cross-kind scene index."""
        image_id = self._current_image_id()
        changed = bool(
            image_id is not None
            and self._layers.reorder_layer(image_id, layer.layer_id, target_index)
        )
        return _mutation_result(self.name, scene, layer, changed, "layer reordered")

    def set_opacity(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        opacity: float,
    ) -> SceneMutationResult:
        """Update composition-owned opacity for one instance."""
        image_id = self._current_image_id()
        changed = bool(
            image_id is not None
            and self._layers.update_presentation(
                image_id,
                layer.layer_id,
                opacity=opacity,
            )
        )
        if changed and isinstance(layer.source, MaskLayerSource):
            self._notify_mask_opacity(layer.source.mask_id)
        return _mutation_result(
            self.name, scene, layer, changed, "layer opacity updated"
        )

    def set_interaction(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        interaction: LayerInteractionPolicy,
    ) -> SceneMutationResult:
        """Update direct-interaction permissions for one mask instance."""
        image_id = self._current_image_id()
        changed = bool(
            image_id is not None
            and self._layers.update_interaction(
                image_id,
                layer.layer_id,
                interaction,
            )
        )
        return _mutation_result(
            self.name, scene, layer, changed, "layer interaction updated"
        )

    def set_placement(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        placement: LayerPlacement,
    ) -> SceneMutationResult:
        """Update scene-space placement for one mask instance."""
        image_id = self._current_image_id()
        changed = bool(
            image_id is not None
            and layer.raster_bounds is not None
            and self._layers.update_transform(
                image_id,
                layer.layer_id,
                LayerTransform.from_placement(layer.raster_bounds, placement),
            )
        )
        return _mutation_result(
            self.name, scene, layer, changed, "layer placement updated"
        )

    def request_source_revision(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        reason: str,
    ) -> SceneMutationResult:
        """Route source invalidation without transferring structure ownership."""
        source = layer.source
        changed = isinstance(source, MaskLayerSource) and self._request_mask_revision(
            source.mask_id,
            reason,
        )
        return _mutation_result(
            self.name, scene, layer, changed, "source revision requested"
        )


class DefaultImageLayerMutationOwner(BaseSceneMutationOwner):
    """Apply presentation mutations to default catalog-image layer instances."""

    name = "default-image-layer"

    def __init__(
        self,
        layers: ImageSceneLayerStore,
        current_image_id: Callable[[], uuid.UUID | None],
    ) -> None:
        """Bind default image-scene state and active image identity."""
        self._layers = layers
        self._current_image_id = current_image_id

    def supports_layer(self, scene: SceneDescriptor, layer: LayerDescriptor) -> bool:
        """Return True for the active default catalog-image instance."""
        image_id = self._current_image_id()
        return bool(
            image_id is not None
            and isinstance(layer.source, CatalogImageSource)
            and self._layers.layer(image_id, layer.layer_id) is not None
        )

    def set_interaction(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        interaction: LayerInteractionPolicy,
    ) -> SceneMutationResult:
        """Update direct-interaction permissions for the base image instance."""
        image_id = self._current_image_id()
        changed = bool(
            image_id is not None
            and self._layers.update_interaction(
                image_id,
                layer.layer_id,
                interaction,
            )
        )
        return _mutation_result(
            self.name, scene, layer, changed, "layer interaction updated"
        )

    def set_placement(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        placement: LayerPlacement,
    ) -> SceneMutationResult:
        """Update scene-space placement for the base image instance."""
        image_id = self._current_image_id()
        changed = bool(
            image_id is not None
            and layer.raster_bounds is not None
            and self._layers.update_transform(
                image_id,
                layer.layer_id,
                LayerTransform.from_placement(layer.raster_bounds, placement),
            )
        )
        return _mutation_result(
            self.name, scene, layer, changed, "layer placement updated"
        )


class StoredSceneLayerMutationOwner(BaseSceneMutationOwner):
    """Apply placement and policy changes to host-authored scene records."""

    name = "stored-scene-layer"

    def __init__(self, compositions: CompositionService) -> None:
        """Bind the authoritative stored-composition service."""
        self._compositions = compositions

    def supports_layer(self, scene: SceneDescriptor, layer: LayerDescriptor) -> bool:
        """Return True when the active stored scene contains ``layer``."""
        try:
            record = self._compositions.record(scene.scene_id)
        except (KeyError, TypeError):
            return False
        return bool(
            record.scene is not None
            and any(item.layer_id == layer.layer_id for item in record.scene.layers)
        )

    def set_interaction(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        interaction: LayerInteractionPolicy,
    ) -> SceneMutationResult:
        """Update direct-interaction permissions in one stored scene."""
        changed = self._compositions.update_scene_layer_interaction(
            scene.scene_id,
            layer.layer_id,
            interaction,
        )
        return _mutation_result(
            self.name,
            scene,
            layer,
            changed,
            "layer interaction updated",
        )

    def set_placement(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        placement: LayerPlacement,
    ) -> SceneMutationResult:
        """Update scene-space placement in one stored scene."""
        changed = self._compositions.update_scene_layer_placement(
            scene.scene_id,
            layer.layer_id,
            placement,
        )
        return _mutation_result(
            self.name,
            scene,
            layer,
            changed,
            "layer placement updated",
        )


def _mutation_result(
    owner: str,
    scene: SceneDescriptor,
    layer: LayerDescriptor,
    changed: bool,
    message: str,
) -> SceneMutationResult:
    """Build a normalized mutation-owner result."""
    return SceneMutationResult(
        status=(
            SceneMutationStatus.APPLIED if changed else SceneMutationStatus.UNCHANGED
        ),
        scene_id=scene.scene_id,
        layer_id=layer.layer_id,
        owner=owner,
        message=message,
    )
