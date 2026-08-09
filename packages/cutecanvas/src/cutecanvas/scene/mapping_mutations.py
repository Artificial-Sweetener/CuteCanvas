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

"""Atomic durable mutation boundary for exact layer-mapping sets."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from qpane.sdk.scene import LayerMapping, SceneDescriptor

from ..composition.edit_controller import CompositionEditController
from ..composition.layers import CompositionLayerStore
from .mapping_edit import LayerMappingEdit, LayerMappingTransition
from .mutations import SceneMutationResult, SceneMutationStatus


@dataclass(frozen=True, slots=True)
class LayerMappingValue:
    """Identify one requested exact layer mapping."""

    layer_id: uuid.UUID
    mapping: LayerMapping


class LayerMappingMutationOwner:
    """Validate and atomically commit one exact layer-mapping set."""

    def __init__(
        self,
        *,
        scene_provider: Callable[[], SceneDescriptor | None],
        composition_id: Callable[[], uuid.UUID | None],
        layers: CompositionLayerStore,
        edits: CompositionEditController,
    ) -> None:
        """Bind active scene, composition store, and chronological history."""
        self._scene_provider = scene_provider
        self._composition_id = composition_id
        self._layers = layers
        self._edits = edits

    def commit(
        self,
        scene_id: uuid.UUID,
        values: tuple[LayerMappingValue, ...],
    ) -> SceneMutationResult:
        """Apply valid changed mappings in one publication and history edit."""
        scene = self._scene_provider()
        if scene is None:
            return SceneMutationResult(SceneMutationStatus.NO_SCENE, scene_id=scene_id)
        if scene.scene_id != scene_id:
            return SceneMutationResult(
                SceneMutationStatus.SCENE_MISMATCH,
                scene_id=scene_id,
            )
        requested = {value.layer_id: value.mapping for value in values}
        if not requested or len(requested) != len(values):
            return SceneMutationResult(
                SceneMutationStatus.INVALID_REQUEST,
                scene_id=scene_id,
                message="mapping values must be non-empty and unique",
            )
        descriptors = {
            layer.layer_id: layer
            for layer in scene.layers
            if layer.layer_id in requested
        }
        if descriptors.keys() != requested.keys():
            return SceneMutationResult(
                SceneMutationStatus.LAYER_NOT_FOUND,
                scene_id=scene_id,
            )
        if any(
            not layer.interaction.movable or layer.transform is None
            for layer in descriptors.values()
        ):
            return SceneMutationResult(
                SceneMutationStatus.POLICY_DENIED,
                scene_id=scene_id,
            )
        composition_id = self._composition_id()
        durable = {
            layer_id: (
                None
                if composition_id is None
                else self._layers.layer(composition_id, layer_id)
            )
            for layer_id in requested
        }
        if any(instance is None for instance in durable.values()):
            return SceneMutationResult(
                SceneMutationStatus.LAYER_NOT_FOUND,
                scene_id=scene_id,
            )
        transitions = tuple(
            LayerMappingTransition(
                layer_id,
                durable[layer_id].transform,
                mapping,
            )
            for layer_id, mapping in requested.items()
            if durable[layer_id] is not None and durable[layer_id].transform != mapping
        )
        if not transitions:
            return SceneMutationResult(
                SceneMutationStatus.UNCHANGED,
                scene_id=scene_id,
            )
        changed = bool(
            composition_id is not None
            and self._layers.update_mappings(
                composition_id,
                tuple(
                    (transition.layer_id, transition.after)
                    for transition in transitions
                ),
            )
        )
        if not changed:
            return SceneMutationResult(
                SceneMutationStatus.UNSUPPORTED,
                scene_id=scene_id,
                message="active composition rejected layer mappings",
            )
        self._edits.record_applied(LayerMappingEdit(scene_id, transitions))
        return SceneMutationResult(
            SceneMutationStatus.APPLIED,
            scene_id=scene_id,
            layer_id=transitions[-1].layer_id,
            owner="layer-mapping-set",
        )


__all__ = ["LayerMappingMutationOwner", "LayerMappingValue"]
