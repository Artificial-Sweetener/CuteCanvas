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
"""Serializable stable references to document content subjects."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum


class CanvasContentKind(str, Enum):
    """Name the durable document subject addressed by one reference."""

    COMPOSITION = "composition"
    LAYER = "layer"
    RESOURCE = "resource"


@dataclass(frozen=True, slots=True)
class CanvasContentReference:
    """Identify content plus observed instance and resource revisions."""

    document_id: uuid.UUID
    kind: CanvasContentKind
    composition_id: uuid.UUID | None = None
    layer_id: uuid.UUID | None = None
    resource_id: uuid.UUID | None = None
    instance_revision: int = 0
    resource_revision: int = 0

    def __post_init__(self) -> None:
        """Reject structurally inconsistent or negative reference values."""
        if not isinstance(self.document_id, uuid.UUID):
            raise TypeError("document_id must be a UUID")
        object.__setattr__(self, "kind", CanvasContentKind(self.kind))
        if self.instance_revision < 0 or self.resource_revision < 0:
            raise ValueError("content revisions must not be negative")
        if self.kind is CanvasContentKind.COMPOSITION:
            if self.composition_id is None:
                raise ValueError("composition reference requires composition_id")
            if self.layer_id is not None or self.resource_id is not None:
                raise ValueError("composition reference cannot identify a child")
        elif self.kind is CanvasContentKind.LAYER:
            if (
                self.composition_id is None
                or self.layer_id is None
                or self.resource_id is None
            ):
                raise ValueError(
                    "layer reference requires composition, layer, resource"
                )
        elif self.resource_id is None:
            raise ValueError("resource reference requires resource_id")


@dataclass(frozen=True, slots=True)
class ResolvedCanvasContent:
    """Return current identities and whether an observed revision is still current."""

    reference: CanvasContentReference
    current: CanvasContentReference

    @property
    def stale(self) -> bool:
        """Return whether content changed after the observed reference was made."""
        return self.reference != self.current
