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

"""Project-resource graph ownership for composition documents."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from ..composition.layers import CompositionLayerInstance
from ..composition.resource_references import instance_resources
from .model import ProjectResourceKind, ProjectResourceReference
from .store import ProjectResourceStore


class CompositionResourceOwner:
    """Represent every document and its layer dependencies in one resource graph."""

    def __init__(self, resources: ProjectResourceStore) -> None:
        """Bind the authoritative project resource graph."""
        self._resources = resources

    def synchronize(
        self,
        composition_id: uuid.UUID,
        layers: Iterable[CompositionLayerInstance],
    ) -> None:
        """Create or update one composition resource from its layer sources."""
        dependencies = _layer_dependencies(composition_id, layers)
        current = self._resources.get(composition_id)
        if current is None:
            self._resources.create(
                ProjectResourceKind.COMPOSITION,
                editable=True,
                resource_id=composition_id,
                dependencies=dependencies,
            )
            return
        if current.kind is not ProjectResourceKind.COMPOSITION:
            raise ValueError("document identity belongs to a non-composition resource")
        self._resources.set_dependencies(composition_id, dependencies)

    def validate(
        self,
        composition_id: uuid.UUID,
        layers: Iterable[CompositionLayerInstance],
    ) -> None:
        """Reject a proposed document stack before any layer state mutates."""
        self._resources.validate_dependencies(
            composition_id,
            _layer_dependencies(composition_id, layers),
        )

    def remove(self, composition_id: uuid.UUID) -> bool:
        """Remove one composition resource unless another resource depends on it."""
        current = self._resources.get(composition_id)
        if current is None:
            return False
        if current.kind is not ProjectResourceKind.COMPOSITION:
            raise ValueError("document identity belongs to a non-composition resource")
        return self._resources.remove(composition_id)

    def remove_many(self, composition_ids: Iterable[uuid.UUID]) -> None:
        """Remove a complete document set atomically while preserving other resources."""
        removed = frozenset(composition_ids)
        retained = tuple(
            record
            for record in self._resources.records()
            if record.resource_id not in removed
        )
        self._resources.restore_state(retained)


def _layer_dependencies(
    composition_id: uuid.UUID,
    layers: Iterable[CompositionLayerInstance],
) -> frozenset[uuid.UUID]:
    """Return unique resource dependencies retained by one composition stack."""
    return frozenset(
        source.resource_id
        for layer in layers
        for source in instance_resources(layer)
        if isinstance(source, ProjectResourceReference)
        and source.resource_id != composition_id
    )
