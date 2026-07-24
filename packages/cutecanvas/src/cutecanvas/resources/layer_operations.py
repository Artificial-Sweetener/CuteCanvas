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

"""Share and fork layer resources through one source-neutral workflow."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from qpane.sdk.scene import LayerInteractionPolicy, LayerTransform

from ..composition.layer_edits import CompositionLayerEditService
from ..composition.layers import CompositionLayerInstance, CompositionLayerStore
from .model import ProjectResourceKind, ProjectResourceReference
from .store import ProjectResourceStore


@dataclass(frozen=True, slots=True)
class ResourceForkOwner:
    """Define payload cloning and rollback for one project resource kind."""

    fork: Callable[[uuid.UUID], uuid.UUID | None]
    remove: Callable[[uuid.UUID], bool]


class LayerResourceOperations:
    """Apply source-neutral sharing and payload-aware forking to layers."""

    def __init__(
        self,
        *,
        resources: ProjectResourceStore,
        layers: CompositionLayerStore,
        edits: CompositionLayerEditService,
    ) -> None:
        """Bind authoritative resource, instance, and history owners."""
        self._resources = resources
        self._layers = layers
        self._edits = edits
        self._fork_owners: dict[ProjectResourceKind, ResourceForkOwner] = {}

    def register_fork_owner(
        self,
        kind: ProjectResourceKind,
        owner: ResourceForkOwner,
    ) -> None:
        """Register the sole payload fork owner for one resource kind."""
        existing = self._fork_owners.get(kind)
        if existing is not None and existing != owner:
            raise ValueError(f"fork owner already registered for {kind.value}")
        self._fork_owners[kind] = owner

    def unregister_fork_owner(
        self,
        kind: ProjectResourceKind,
        owner: ResourceForkOwner,
    ) -> None:
        """Remove a matching payload fork owner."""
        if self._fork_owners.get(kind) == owner:
            self._fork_owners.pop(kind, None)

    def duplicate_layer(
        self,
        composition_id: uuid.UUID,
        layer_id: uuid.UUID,
        *,
        history_scope_id: uuid.UUID | None = None,
    ) -> uuid.UUID | None:
        """Create an independent instance that shares the original resource."""
        duplicate = self._edits.duplicate(
            composition_id,
            layer_id,
            uuid.uuid4(),
            history_scope_id=history_scope_id,
        )
        return None if duplicate is None else duplicate.layer_id

    def place_resource(
        self,
        composition_id: uuid.UUID,
        resource_id: uuid.UUID,
        *,
        transform: LayerTransform,
        interaction: LayerInteractionPolicy,
        label: str | None = None,
        history_scope_id: uuid.UUID | None = None,
    ) -> uuid.UUID | None:
        """Place one retained resource as an ordinary undoable layer instance."""
        if self._resources.get(resource_id) is None:
            raise KeyError(f"unknown project resource: {resource_id}")
        instance = CompositionLayerInstance(
            layer_id=uuid.uuid4(),
            source=ProjectResourceReference(resource_id),
            transform=transform,
            interaction=interaction,
            role="content",
            label=label,
        )
        return (
            instance.layer_id
            if self._edits.add(
                composition_id,
                instance,
                history_scope_id=history_scope_id,
            )
            else None
        )

    def fork_layer_resource(
        self,
        composition_id: uuid.UUID,
        layer_id: uuid.UUID,
        *,
        history_scope_id: uuid.UUID | None = None,
    ) -> uuid.UUID | None:
        """Redirect one layer to an independent copy of its current resource."""
        layer = self._layers.layer(composition_id, layer_id)
        source = None if layer is None else layer.source
        if not isinstance(source, ProjectResourceReference):
            return None
        record = self._resources.resolve(source)
        owner = None if record is None else self._fork_owners.get(record.kind)
        if owner is None:
            return None
        fork_id = owner.fork(source.resource_id)
        if fork_id is None:
            return None
        changed = self._edits.replace_source(
            composition_id,
            layer_id,
            ProjectResourceReference(fork_id),
            history_scope_id=history_scope_id,
        )
        if changed:
            return fork_id
        owner.remove(fork_id)
        return None
