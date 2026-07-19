#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Composition instance lifecycle and scene mutations for editable rasters."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage

from ..composition.layers import (
    CompositionLayerInstance,
    CompositionLayerSourceKind,
    ImageSceneLayerStore,
)
from ..scene.identity import default_scene_id, editable_raster_layer_id
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
from ..scene.raster import LayerTransform, RasterExtentPolicy
from ..scene.sources import EditableRasterSource
from .assets import EditableRasterAssetStore


class EditableRasterLayerController:
    """Own editable raster asset and composition-instance lifecycle."""

    def __init__(
        self,
        *,
        assets: EditableRasterAssetStore,
        layers: ImageSceneLayerStore,
        current_image_id: Callable[[], uuid.UUID | None],
    ) -> None:
        """Bind raster assets, composition order, and active image identity."""
        self.assets = assets
        self._layers = layers
        self._current_image_id = current_image_id

    def add(
        self,
        image: QImage,
        *,
        placement: QRectF | None,
        interaction: LayerInteractionPolicy,
        label: str | None,
        extent_policy: RasterExtentPolicy,
    ) -> uuid.UUID | None:
        """Create and attach one editable raster to the active image scene."""
        image_id = self._current_image_id()
        if image_id is None:
            return None
        asset = self.assets.create(image, extent_policy=extent_policy)
        bounds = asset.surface.bounds
        destination = (
            LayerPlacement(
                float(bounds.x),
                float(bounds.y),
                float(bounds.width),
                float(bounds.height),
            )
            if placement is None
            else LayerPlacement(
                placement.x(),
                placement.y(),
                placement.width(),
                placement.height(),
            )
        )
        instance = CompositionLayerInstance(
            layer_id=editable_raster_layer_id(
                default_scene_id(image_id), asset.raster_id
            ),
            source_kind=CompositionLayerSourceKind.RASTER,
            source_id=asset.raster_id,
            transform=LayerTransform.from_placement(bounds, destination),
            interaction=interaction,
            role="raster",
            label=label,
        )
        if self._layers.add_layer(image_id, instance):
            return instance.layer_id
        self.assets.remove(asset.raster_id)
        return None

    def remove(self, image_id: uuid.UUID, raster_id: uuid.UUID) -> bool:
        """Remove one instance and delete an orphaned editable raster asset."""
        instance = self._layers.layer_for_source(
            image_id,
            CompositionLayerSourceKind.RASTER,
            raster_id,
        )
        if instance is None or not self._layers.remove_layer(
            image_id, instance.layer_id
        ):
            return False
        if not self._layers.image_ids_for_source(
            CompositionLayerSourceKind.RASTER,
            raster_id,
        ):
            self.assets.remove(raster_id)
        return True

    def prune_orphaned_assets(self) -> None:
        """Delete assets no longer referenced by any composition layer instance."""
        for raster_id in self.assets.ids():
            if not self._layers.image_ids_for_source(
                CompositionLayerSourceKind.RASTER,
                raster_id,
            ):
                self.assets.remove(raster_id)


class EditableRasterSceneMutationOwner(BaseSceneMutationOwner):
    """Apply generic scene mutations to editable raster instances."""

    name = "editable-raster"

    def __init__(
        self,
        layers: ImageSceneLayerStore,
        assets: EditableRasterAssetStore,
        current_image_id: Callable[[], uuid.UUID | None],
    ) -> None:
        """Bind composition placement and raster asset lifecycle."""
        self._layers = layers
        self._assets = assets
        self._current_image_id = current_image_id

    def supports_layer(self, scene: SceneDescriptor, layer: LayerDescriptor) -> bool:
        """Return whether ``layer`` references an editable raster."""
        return isinstance(layer.source, EditableRasterSource)

    def remove_layer(
        self, scene: SceneDescriptor, layer: LayerDescriptor
    ) -> SceneMutationResult:
        """Remove one editable raster instance and orphaned source asset."""
        image_id = self._current_image_id()
        source = layer.source
        changed = bool(
            image_id is not None
            and isinstance(source, EditableRasterSource)
            and self._layers.remove_layer(image_id, layer.layer_id)
        )
        if (
            changed
            and isinstance(source, EditableRasterSource)
            and not self._layers.image_ids_for_source(
                CompositionLayerSourceKind.RASTER,
                source.raster_id,
            )
        ):
            self._assets.remove(source.raster_id)
        return _result(self.name, scene, layer, changed)

    def reorder_layer(
        self, scene: SceneDescriptor, layer: LayerDescriptor, target_index: int
    ) -> SceneMutationResult:
        """Move one editable raster to an exact scene z-order index."""
        image_id = self._current_image_id()
        changed = bool(
            image_id is not None
            and self._layers.reorder_layer(image_id, layer.layer_id, target_index)
        )
        return _result(self.name, scene, layer, changed)

    def set_opacity(
        self, scene: SceneDescriptor, layer: LayerDescriptor, opacity: float
    ) -> SceneMutationResult:
        """Update composition-owned raster opacity."""
        image_id = self._current_image_id()
        changed = bool(
            image_id is not None
            and self._layers.update_presentation(
                image_id, layer.layer_id, opacity=opacity
            )
        )
        return _result(self.name, scene, layer, changed)

    def set_interaction(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        interaction: LayerInteractionPolicy,
    ) -> SceneMutationResult:
        """Update composition-owned raster interaction policy."""
        image_id = self._current_image_id()
        changed = bool(
            image_id is not None
            and self._layers.update_interaction(image_id, layer.layer_id, interaction)
        )
        return _result(self.name, scene, layer, changed)

    def set_placement(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        placement: LayerPlacement,
    ) -> SceneMutationResult:
        """Update composition-owned raster transform."""
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
        return _result(self.name, scene, layer, changed)


def _result(
    owner: str,
    scene: SceneDescriptor,
    layer: LayerDescriptor,
    changed: bool,
) -> SceneMutationResult:
    """Build a normalized scene mutation result."""
    return SceneMutationResult(
        SceneMutationStatus.APPLIED if changed else SceneMutationStatus.UNCHANGED,
        scene.scene_id,
        layer.layer_id,
        owner,
    )
