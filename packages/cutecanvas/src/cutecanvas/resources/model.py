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
"""Immutable identities and records for CuteCanvas project resources."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum


class ProjectResourceKind(str, Enum):
    """Identify the authoritative content domain of a project resource."""

    RASTER = "raster"
    IMPORTED_RASTER = "imported-raster"
    LINKED_RASTER = "linked-raster"
    VECTOR = "vector"
    COVERAGE = "coverage"
    COMPOSITION = "composition"


@dataclass(frozen=True, slots=True)
class ProjectResourceReference:
    """Reference one reusable project resource from any layer instance."""

    resource_id: uuid.UUID

    def __post_init__(self) -> None:
        """Validate stable resource identity."""
        if not isinstance(self.resource_id, uuid.UUID):
            raise TypeError("resource_id must be a UUID")

    @property
    def kind(self) -> str:
        """Return the stable persistence and routing kind."""
        return "project-resource"


@dataclass(frozen=True, slots=True)
class ProjectResourceRecord:
    """Describe one resource's kind, editability, revision, and dependencies."""

    resource_id: uuid.UUID
    kind: ProjectResourceKind
    editable: bool
    revision: int = 0
    dependencies: frozenset[uuid.UUID] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        """Reject invalid identities, revisions, and dependency values."""
        if not isinstance(self.resource_id, uuid.UUID):
            raise TypeError("resource_id must be a UUID")
        if not isinstance(self.kind, ProjectResourceKind):
            raise TypeError("kind must be ProjectResourceKind")
        if not isinstance(self.editable, bool):
            raise TypeError("editable must be a bool")
        if self.revision < 0:
            raise ValueError("revision must not be negative")
        dependencies = frozenset(self.dependencies)
        if not all(isinstance(item, uuid.UUID) for item in dependencies):
            raise TypeError("resource dependencies must be UUIDs")
        if self.resource_id in dependencies:
            raise ValueError("a resource cannot depend on itself")
        object.__setattr__(self, "dependencies", dependencies)

    @property
    def reference(self) -> ProjectResourceReference:
        """Return the layer-safe reference to this resource."""
        return ProjectResourceReference(self.resource_id)
