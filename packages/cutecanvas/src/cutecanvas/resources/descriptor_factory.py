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
"""Single scene-descriptor route for every CuteCanvas project resource."""

from __future__ import annotations

from typing import Protocol

from qpane.sdk.scene import LayerDescriptor, SceneDescriptor

from ..composition.layers import CompositionLayerInstance
from .model import (
    ProjectResourceKind,
    ProjectResourceRecord,
    ProjectResourceReference,
)
from .store import ProjectResourceStore


class ProjectResourceDescriptorOwner(Protocol):
    """Resolve descriptors for one authoritative project-resource kind."""

    def descriptor(
        self,
        scene: SceneDescriptor,
        instance: CompositionLayerInstance,
        resource: ProjectResourceRecord,
    ) -> LayerDescriptor | None:
        """Resolve one layer instance through its domain payload owner."""
        ...


class ProjectResourceLayerDescriptorFactory:
    """Route one stable layer reference through the resource's current kind."""

    source_type = ProjectResourceReference

    def __init__(self, resources: ProjectResourceStore) -> None:
        """Bind the authoritative graph without owning domain payloads."""
        self._resources = resources
        self._owners: dict[ProjectResourceKind, ProjectResourceDescriptorOwner] = {}

    def register(
        self,
        kind: ProjectResourceKind,
        owner: ProjectResourceDescriptorOwner,
    ) -> None:
        """Register the sole descriptor owner for one resource kind."""
        existing = self._owners.get(kind)
        if existing is not None and existing is not owner:
            raise ValueError(f"descriptor owner already registered for {kind.value}")
        self._owners[kind] = owner

    def unregister(
        self,
        kind: ProjectResourceKind,
        owner: ProjectResourceDescriptorOwner,
    ) -> None:
        """Remove a matching descriptor owner."""
        if self._owners.get(kind) is owner:
            self._owners.pop(kind, None)

    def revision(self) -> object:
        """Return the authoritative resource graph revision."""
        return self._resources.revision

    def descriptor(
        self,
        scene: SceneDescriptor,
        instance: CompositionLayerInstance,
    ) -> LayerDescriptor | None:
        """Resolve one project-resource layer through its current domain."""
        source = instance.source
        if not isinstance(source, ProjectResourceReference):
            return None
        resource = self._resources.resolve(source)
        if resource is None:
            return None
        owner = self._owners.get(resource.kind)
        return None if owner is None else owner.descriptor(scene, instance, resource)
