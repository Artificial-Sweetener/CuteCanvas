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
"""Final-release routing for stable project-resource references."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from qpane.sdk.scene import LayerSourceReference

from .model import ProjectResourceKind, ProjectResourceReference
from .store import ProjectResourceStore


class ProjectResourceLifecycleOwner:
    """Release payloads according to a resource's authoritative current kind."""

    source_type = ProjectResourceReference

    def __init__(self, resources: ProjectResourceStore) -> None:
        """Bind the resource graph and initialize payload release routes."""
        self._resources = resources
        self._release: dict[ProjectResourceKind, Callable[[uuid.UUID], bool]] = {}

    def register(
        self,
        kind: ProjectResourceKind,
        release: Callable[[uuid.UUID], bool],
    ) -> None:
        """Register the sole payload release owner for one resource kind."""
        existing = self._release.get(kind)
        if existing is not None and existing != release:
            raise ValueError(f"lifecycle owner already registered for {kind.value}")
        self._release[kind] = release

    def unregister(
        self,
        kind: ProjectResourceKind,
        release: Callable[[uuid.UUID], bool],
    ) -> None:
        """Remove a matching payload release owner."""
        if self._release.get(kind) == release:
            self._release.pop(kind, None)

    def release_unreachable(self, source: LayerSourceReference) -> None:
        """Release an unreachable payload through its current domain owner."""
        if not isinstance(source, ProjectResourceReference):
            return
        record = self._resources.resolve(source)
        release = None if record is None else self._release.get(record.kind)
        if release is not None:
            release(source.resource_id)
