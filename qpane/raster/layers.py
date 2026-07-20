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

from ..composition.layer_edits import CompositionLayerEditService
from ..composition.layers import (
    CompositionLayerInstance,
    CompositionLayerStore,
)
from ..scene.affine import LayerTransform
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
from ..scene.raster import RasterExtentPolicy
from .assets import EditableRasterAssetStore
from .source_reference import EditableRasterReference


class EditableRasterLayerController:
    """Own editable raster asset and composition-instance lifecycle."""

    def __init__(
        self,
        *,
        assets: EditableRasterAssetStore,
        layers: CompositionLayerStore,
        layer_edits: CompositionLayerEditService,
        current_composition_id: Callable[[], uuid.UUID | None],
        is_generated_default: Callable[[uuid.UUID], bool],
    ) -> None:
        """Bind raster assets and the active composition document."""
        self.assets = assets
        self._layers = layers
        self._layer_edits = layer_edits
        self._current_composition_id = current_composition_id
        self._is_generated_default = is_generated_default

    def add(
        self,
        image: QImage,
        *,
        placement: QRectF | None,
        interaction: LayerInteractionPolicy,
        label: str | None,
        extent_policy: RasterExtentPolicy,
    ) -> uuid.UUID | None:
        """Create and attach one editable raster to the active composition."""
        composition_id = self._current_composition_id()
        if composition_id is None:
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
            layer_id=uuid.uuid4(),
            source=EditableRasterReference(asset.raster_id),
            transform=LayerTransform.from_placement(bounds, destination),
            interaction=interaction,
            role="raster",
            label=label,
        )
        added = (
            self._layers.add_layer(composition_id, instance)
            if self._is_generated_default(composition_id)
            else self._layer_edits.add(composition_id, instance)
        )
        if added:
            return instance.layer_id
        self.assets.remove(asset.raster_id)
        return None

    def remove(self, composition_id: uuid.UUID, raster_id: uuid.UUID) -> bool:
        """Remove one instance and delete an orphaned editable raster asset."""
        instance = self._layers.layer_for_source(
            composition_id,
            EditableRasterReference(raster_id),
        )
        return instance is not None and self._layer_edits.remove(
            composition_id,
            instance.layer_id,
        )


class EditableRasterSceneMutationOwner(BaseSceneMutationOwner):
    """Apply generic scene mutations to editable raster instances."""

    name = "editable-raster"

    def __init__(
        self,
        layers: CompositionLayerStore,
        current_composition_id: Callable[[], uuid.UUID | None],
    ) -> None:
        """Bind composition placement for editable raster instances."""
        self._layers = layers
        self._current_composition_id = current_composition_id

    def supports_layer(self, scene: SceneDescriptor, layer: LayerDescriptor) -> bool:
        """Return whether ``layer`` references an editable raster."""
        return isinstance(layer.source, EditableRasterReference)

    def remove_layer(
        self, scene: SceneDescriptor, layer: LayerDescriptor
    ) -> SceneMutationResult:
        """Remove one editable raster instance and orphaned source asset."""
        composition_id = self._current_composition_id()
        source = layer.source
        changed = bool(
            composition_id is not None
            and isinstance(source, EditableRasterReference)
            and self._layers.remove_layer(composition_id, layer.layer_id)
        )
        return _result(self.name, scene, layer, changed)

    def reorder_layer(
        self, scene: SceneDescriptor, layer: LayerDescriptor, target_index: int
    ) -> SceneMutationResult:
        """Move one editable raster to an exact scene z-order index."""
        composition_id = self._current_composition_id()
        changed = bool(
            composition_id is not None
            and self._layers.reorder_layer(composition_id, layer.layer_id, target_index)
        )
        return _result(self.name, scene, layer, changed)

    def set_opacity(
        self, scene: SceneDescriptor, layer: LayerDescriptor, opacity: float
    ) -> SceneMutationResult:
        """Update composition-owned raster opacity."""
        composition_id = self._current_composition_id()
        changed = bool(
            composition_id is not None
            and self._layers.update_presentation(
                composition_id, layer.layer_id, opacity=opacity
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
        composition_id = self._current_composition_id()
        changed = bool(
            composition_id is not None
            and self._layers.update_interaction(
                composition_id, layer.layer_id, interaction
            )
        )
        return _result(self.name, scene, layer, changed)

    def set_placement(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        placement: LayerPlacement,
    ) -> SceneMutationResult:
        """Update composition-owned raster transform."""
        composition_id = self._current_composition_id()
        changed = bool(
            composition_id is not None
            and layer.raster_bounds is not None
            and self._layers.update_transform(
                composition_id,
                layer.layer_id,
                LayerTransform.from_placement(layer.raster_bounds, placement),
            )
        )
        return _result(self.name, scene, layer, changed)

    def set_transform(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        transform: LayerTransform,
    ) -> SceneMutationResult:
        """Update exact composition-owned raster geometry."""
        composition_id = self._current_composition_id()
        changed = bool(
            composition_id is not None
            and self._layers.update_transform(
                composition_id,
                layer.layer_id,
                transform,
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
