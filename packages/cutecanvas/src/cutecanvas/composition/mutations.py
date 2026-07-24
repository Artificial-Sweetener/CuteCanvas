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
"""Scene mutation ownership for composition-managed layer instances."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from qpane.sdk.scene import (
    LayerDescriptor,
    LayerInteractionPolicy,
    LayerPlacement,
    LayerTransform,
    SceneDescriptor,
)

from ..resources import ProjectResourceReference
from ..scene.mutations import (
    BaseSceneMutationOwner,
    SceneMutationResult,
    SceneMutationStatus,
)
from .layer_edits import CompositionLayerEditService
from .layers import CompositionLayerStore


class MaskSceneMutationOwner(BaseSceneMutationOwner):
    """Apply generic composition mutations to mask layer instances."""

    name = "mask"

    def __init__(
        self,
        layers: CompositionLayerStore,
        layer_edits: CompositionLayerEditService,
        current_composition_id: Callable[[], uuid.UUID | None],
        *,
        is_mask: Callable[[uuid.UUID], bool],
        notify_mask_opacity: Callable[[uuid.UUID], None],
        request_mask_revision: Callable[[uuid.UUID, str], bool],
    ) -> None:
        """Bind composition state and mask asset lifecycle callbacks."""
        self._layers = layers
        self._layer_edits = layer_edits
        self._current_composition_id = current_composition_id
        self._is_mask = is_mask
        self._notify_mask_opacity = notify_mask_opacity
        self._request_mask_revision = request_mask_revision

    def supports_layer(self, scene: SceneDescriptor, layer: LayerDescriptor) -> bool:
        """Return True for composition-backed mask instances."""
        return isinstance(
            layer.source,
            ProjectResourceReference,
        ) and self._is_mask(layer.source.resource_id)

    def remove_layer(
        self, scene: SceneDescriptor, layer: LayerDescriptor
    ) -> SceneMutationResult:
        """Remove one layer instance and let its source owner prune orphans."""
        composition_id = self._current_composition_id()
        changed = bool(
            composition_id is not None
            and self._layer_edits.remove(composition_id, layer.layer_id)
        )
        return _mutation_result(self.name, scene, layer, changed, "layer removed")

    def reorder_layer(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        target_index: int,
    ) -> SceneMutationResult:
        """Move one instance to an exact cross-kind scene index."""
        composition_id = self._current_composition_id()
        changed = bool(
            composition_id is not None
            and self._layers.reorder_layer(composition_id, layer.layer_id, target_index)
        )
        return _mutation_result(self.name, scene, layer, changed, "layer reordered")

    def set_opacity(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        opacity: float,
    ) -> SceneMutationResult:
        """Update composition-owned opacity for one instance."""
        composition_id = self._current_composition_id()
        changed = bool(
            composition_id is not None
            and self._layers.update_presentation(
                composition_id,
                layer.layer_id,
                opacity=opacity,
            )
        )
        if changed and isinstance(layer.source, ProjectResourceReference):
            self._notify_mask_opacity(layer.source.resource_id)
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
        composition_id = self._current_composition_id()
        changed = bool(
            composition_id is not None
            and self._layers.update_interaction(
                composition_id,
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
        return _mutation_result(
            self.name, scene, layer, changed, "layer placement updated"
        )

    def set_transform(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        transform: LayerTransform,
    ) -> SceneMutationResult:
        """Update exact composition-owned geometry for one mask instance."""
        composition_id = self._current_composition_id()
        changed = bool(
            composition_id is not None
            and self._layers.update_transform(
                composition_id,
                layer.layer_id,
                transform,
            )
        )
        return _mutation_result(
            self.name, scene, layer, changed, "layer transform updated"
        )

    def request_source_revision(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        reason: str,
    ) -> SceneMutationResult:
        """Route source invalidation without transferring structure ownership."""
        source = layer.source
        changed = (
            isinstance(source, ProjectResourceReference)
            and self._is_mask(source.resource_id)
            and self._request_mask_revision(
                source.resource_id,
                reason,
            )
        )
        return _mutation_result(
            self.name, scene, layer, changed, "source revision requested"
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
