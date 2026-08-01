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
"""Immutable content and interaction policy for one document viewport."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum

from .references import CanvasContentKind, CanvasContentReference


class CanvasViewportInteraction(str, Enum):
    """Name the direct navigation policy of one viewport."""

    INTERACTIVE = "interactive"
    FIT_ONLY = "fit-only"


class CanvasRenderVariant(str, Enum):
    """Name a source-neutral presentation of selected document content."""

    COMPOSITE = "composite"
    MASK_COVERAGE = "mask-coverage"
    MASK_OVERLAY = "mask-overlay"


@dataclass(frozen=True, slots=True)
class CanvasViewportSource:
    """Select one composition, one layer, a layer subset, or one resource."""

    references: tuple[CanvasContentReference, ...]

    def __post_init__(self) -> None:
        """Reject ambiguous selections before a viewport consumes them."""
        references = tuple(self.references)
        if not references:
            raise ValueError("viewport source requires at least one content reference")
        if len({reference.document_id for reference in references}) != 1:
            raise ValueError("viewport source references must belong to one document")
        kinds = {reference.kind for reference in references}
        if len(references) > 1 and kinds != {CanvasContentKind.LAYER}:
            raise ValueError("only layer references may form a viewport subset")
        if kinds == {CanvasContentKind.LAYER}:
            if len({reference.composition_id for reference in references}) != 1:
                raise ValueError("viewport layer subset must belong to one composition")
            layer_ids = tuple(reference.layer_id for reference in references)
            if len(set(layer_ids)) != len(layer_ids):
                raise ValueError("viewport layer subset must not contain duplicates")
        object.__setattr__(self, "references", references)

    @property
    def document_id(self) -> uuid.UUID:
        """Return the selected document identity."""
        return self.references[0].document_id

    @property
    def composition_id(self) -> uuid.UUID | None:
        """Return the selected composition when the source directly names one."""
        return self.references[0].composition_id

    @classmethod
    def content(cls, reference: CanvasContentReference) -> CanvasViewportSource:
        """Select one composition, layer, or resource reference."""
        return cls((reference,))

    @classmethod
    def layer_subset(
        cls,
        *references: CanvasContentReference,
    ) -> CanvasViewportSource:
        """Select an ordered subset of layers from one composition."""
        return cls(tuple(references))


@dataclass(frozen=True, slots=True)
class CanvasViewportSpec:
    """Identify one independently mounted view over selected document content."""

    source: CanvasViewportSource
    viewport_id: uuid.UUID = field(default_factory=uuid.uuid4)
    interaction: CanvasViewportInteraction = CanvasViewportInteraction.INTERACTIVE
    render_variant: CanvasRenderVariant = CanvasRenderVariant.COMPOSITE

    def __post_init__(self) -> None:
        """Normalize enum values and validate stable viewport identity."""
        if not isinstance(self.viewport_id, uuid.UUID):
            raise TypeError("viewport_id must be a UUID")
        object.__setattr__(
            self,
            "interaction",
            CanvasViewportInteraction(self.interaction),
        )
        object.__setattr__(
            self,
            "render_variant",
            CanvasRenderVariant(self.render_variant),
        )


__all__ = [
    "CanvasRenderVariant",
    "CanvasViewportInteraction",
    "CanvasViewportSource",
    "CanvasViewportSpec",
]
