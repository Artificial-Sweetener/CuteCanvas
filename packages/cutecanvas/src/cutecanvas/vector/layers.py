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
"""Composition instance lifecycle and generic mutations for vector layers."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from qpane.sdk.scene import (
    LayerDescriptor,
    LayerInteractionPolicy,
    LayerMapping,
    LayerPlacement,
    LayerTransform,
    RasterBounds,
    SceneDescriptor,
)

from ..composition.layer_edits import CompositionLayerEditService
from ..composition.layers import CompositionLayerInstance, CompositionLayerStore
from ..resources import ProjectResourceReference
from ..scene.mutations import (
    BaseSceneMutationOwner,
    SceneMutationResult,
    SceneMutationStatus,
)
from .store import VectorAssetStore


class VectorLayerController:
    """Own vector-document creation and composition-instance attachment."""

    def __init__(
        self,
        *,
        assets: VectorAssetStore,
        layers: CompositionLayerStore,
        layer_edits: CompositionLayerEditService,
        current_composition_id: Callable[[], uuid.UUID | None],
        current_history_scope_id: Callable[[], uuid.UUID | None],
    ) -> None:
        """Bind vector resources and the active composition document."""
        self.assets = assets
        self._layers = layers
        self._layer_edits = layer_edits
        self._current_composition_id = current_composition_id
        self._current_history_scope_id = current_history_scope_id

    def create(
        self,
        bounds: RasterBounds,
        *,
        label: str,
        interaction: LayerInteractionPolicy,
        placement: LayerPlacement,
    ) -> tuple[uuid.UUID, uuid.UUID] | None:
        """Create an empty vector document and attach one live instance."""
        composition_id = self._current_composition_id()
        if composition_id is None:
            return None
        document = self.assets.create(bounds)
        layer_id = uuid.uuid4()
        instance = CompositionLayerInstance(
            layer_id=layer_id,
            source=ProjectResourceReference(document.vector_id),
            transform=LayerTransform.from_placement(bounds, placement),
            interaction=interaction,
            role="vector",
            label=label,
        )
        if self._layer_edits.add(
            composition_id,
            instance,
            history_scope_id=self._current_history_scope_id(),
        ):
            return layer_id, document.vector_id
        self.assets.remove(document.vector_id)
        return None


class VectorSceneMutationOwner(BaseSceneMutationOwner):
    """Apply source-neutral layer mutations to vector instances."""

    name = "vector"

    def __init__(
        self,
        assets: VectorAssetStore,
        layers: CompositionLayerStore,
        current_composition_id: Callable[[], uuid.UUID | None],
    ) -> None:
        """Bind the unified composition instance store."""
        self._assets = assets
        self._layers = layers
        self._current_composition_id = current_composition_id

    def supports_layer(self, scene: SceneDescriptor, layer: LayerDescriptor) -> bool:
        """Return whether this owner handles the layer's typed source."""
        return (
            isinstance(layer.source, ProjectResourceReference)
            and self._assets.get(layer.source.resource_id) is not None
        )

    def remove_layer(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
    ) -> SceneMutationResult:
        """Remove one vector instance without bypassing resource leases."""
        composition_id = self._current_composition_id()
        changed = bool(
            composition_id is not None
            and self._layers.remove_layer(composition_id, layer.layer_id)
        )
        return _result(scene, layer, changed)

    def reorder_layer(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        target_index: int,
    ) -> SceneMutationResult:
        """Move one vector instance within cross-kind z-order."""
        composition_id = self._current_composition_id()
        changed = bool(
            composition_id is not None
            and self._layers.reorder_layer(
                composition_id,
                layer.layer_id,
                target_index,
            )
        )
        return _result(scene, layer, changed)

    def set_opacity(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        opacity: float,
    ) -> SceneMutationResult:
        """Update vector instance opacity."""
        composition_id = self._current_composition_id()
        changed = bool(
            composition_id is not None
            and self._layers.update_presentation(
                composition_id,
                layer.layer_id,
                opacity=opacity,
            )
        )
        return _result(scene, layer, changed)

    def set_interaction(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        interaction: LayerInteractionPolicy,
    ) -> SceneMutationResult:
        """Update vector instance interaction policy."""
        composition_id = self._current_composition_id()
        changed = bool(
            composition_id is not None
            and self._layers.update_interaction(
                composition_id,
                layer.layer_id,
                interaction,
            )
        )
        return _result(scene, layer, changed)

    def set_placement(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        placement: LayerPlacement,
    ) -> SceneMutationResult:
        """Replace vector instance geometry from a rectangle placement."""
        composition_id = self._current_composition_id()
        changed = bool(
            composition_id is not None
            and layer.raster_bounds is not None
            and self._layers.update_mapping(
                composition_id,
                layer.layer_id,
                LayerTransform.from_placement(layer.raster_bounds, placement),
            )
        )
        return _result(scene, layer, changed)

    def set_transform(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        transform: LayerMapping,
    ) -> SceneMutationResult:
        """Replace the exact vector instance affine transform."""
        composition_id = self._current_composition_id()
        changed = bool(
            composition_id is not None
            and self._layers.update_mapping(
                composition_id,
                layer.layer_id,
                transform,
            )
        )
        return _result(scene, layer, changed)


def _result(
    scene: SceneDescriptor,
    layer: LayerDescriptor,
    changed: bool,
) -> SceneMutationResult:
    """Build one normalized vector scene-mutation result."""
    return SceneMutationResult(
        SceneMutationStatus.APPLIED if changed else SceneMutationStatus.UNCHANGED,
        scene.scene_id,
        layer.layer_id,
        VectorSceneMutationOwner.name,
    )
