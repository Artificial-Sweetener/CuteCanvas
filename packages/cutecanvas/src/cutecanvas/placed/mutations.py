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
"""Generic scene mutations adapted to placed composition instances."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from qpane.sdk.scene import (
    LayerDescriptor,
    LayerInteractionPolicy,
    LayerMapping,
    LayerPlacement,
    LayerTransform,
    SceneDescriptor,
)

from ..composition.layer_edits import CompositionLayerEditService
from ..composition.layers import CompositionLayerStore
from ..resources import ProjectResourceReference
from ..scene.mutations import (
    BaseSceneMutationOwner,
    SceneMutationResult,
    SceneMutationStatus,
)
from .store import PlacedAssetStore


class PlacedAssetSceneMutationOwner(BaseSceneMutationOwner):
    """Adapt generic layer operations to placed composition instances."""

    name = "placed-asset"

    def __init__(
        self,
        layers: CompositionLayerStore,
        edits: CompositionLayerEditService,
        assets: PlacedAssetStore,
        current_scope_id: Callable[[], uuid.UUID | None],
    ) -> None:
        """Bind authoritative composition instance owners."""
        self._layers = layers
        self._edits = edits
        self._assets = assets
        self._current_scope_id = current_scope_id

    def supports_layer(self, scene: SceneDescriptor, layer: LayerDescriptor) -> bool:
        """Return whether the current composition owns this placed instance."""
        scope_id = self._current_scope_id()
        return bool(
            scope_id is not None
            and isinstance(layer.source, ProjectResourceReference)
            and self._assets.get(layer.source.resource_id) is not None
            and self._layers.layer(scope_id, layer.layer_id) is not None
        )

    def remove_layer(
        self, scene: SceneDescriptor, layer: LayerDescriptor
    ) -> SceneMutationResult:
        """Remove a placed instance through generic undoable lifecycle edits."""
        scope_id = self._current_scope_id()
        changed = bool(
            scope_id is not None
            and self._edits.remove(
                scope_id,
                layer.layer_id,
                history_scope_id=scene.scene_id,
            )
        )
        return _result(self.name, scene, layer, changed)

    def reorder_layer(
        self, scene: SceneDescriptor, layer: LayerDescriptor, target_index: int
    ) -> SceneMutationResult:
        """Move one placed instance to an exact cross-kind stack index."""
        scope_id = self._current_scope_id()
        changed = bool(
            scope_id is not None
            and self._layers.reorder_layer(scope_id, layer.layer_id, target_index)
        )
        return _result(self.name, scene, layer, changed)

    def set_opacity(
        self, scene: SceneDescriptor, layer: LayerDescriptor, opacity: float
    ) -> SceneMutationResult:
        """Replace composition-owned placed opacity."""
        scope_id = self._current_scope_id()
        changed = bool(
            scope_id is not None
            and self._layers.update_presentation(
                scope_id, layer.layer_id, opacity=opacity
            )
        )
        return _result(self.name, scene, layer, changed)

    def set_interaction(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        interaction: LayerInteractionPolicy,
    ) -> SceneMutationResult:
        """Replace composition-owned placed interaction policy."""
        scope_id = self._current_scope_id()
        changed = bool(
            scope_id is not None
            and self._layers.update_interaction(scope_id, layer.layer_id, interaction)
        )
        return _result(self.name, scene, layer, changed)

    def set_placement(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        placement: LayerPlacement,
    ) -> SceneMutationResult:
        """Replace placed geometry using source-local raster bounds."""
        scope_id = self._current_scope_id()
        changed = bool(
            scope_id is not None
            and layer.raster_bounds is not None
            and self._layers.update_mapping(
                scope_id,
                layer.layer_id,
                LayerTransform.from_placement(layer.raster_bounds, placement),
            )
        )
        return _result(self.name, scene, layer, changed)

    def set_transform(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        transform: LayerMapping,
    ) -> SceneMutationResult:
        """Replace exact composition-owned placed geometry."""
        scope_id = self._current_scope_id()
        changed = bool(
            scope_id is not None
            and self._layers.update_mapping(scope_id, layer.layer_id, transform)
        )
        return _result(self.name, scene, layer, changed)


def _result(
    owner: str,
    scene: SceneDescriptor,
    layer: LayerDescriptor,
    changed: bool,
) -> SceneMutationResult:
    """Build one normalized mutation outcome."""
    return SceneMutationResult(
        SceneMutationStatus.APPLIED if changed else SceneMutationStatus.UNCHANGED,
        scene.scene_id,
        layer.layer_id,
        owner,
    )
