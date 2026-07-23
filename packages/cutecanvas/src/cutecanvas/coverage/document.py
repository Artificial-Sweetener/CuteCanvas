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
"""Immutable authored values for hybrid raster and vector coverage."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, TypeAlias

from qpane.sdk.scene import LayerTransform
from qpane.sdk.vector import VectorObject

from .operations import CoverageCombineMode
from .surface import CoverageSnapshot

if TYPE_CHECKING:
    from cutecanvas.painting.model import BrushStrokeSegment


@dataclass(frozen=True, slots=True)
class RasterCoverageItem:
    """Retain one immutable raster contribution in document coordinates."""

    item_id: uuid.UUID
    coverage: CoverageSnapshot
    combine_mode: CoverageCombineMode = CoverageCombineMode.ADD
    transform: LayerTransform = field(default_factory=LayerTransform)

    def __post_init__(self) -> None:
        """Normalize the combine operation."""
        object.__setattr__(self, "combine_mode", CoverageCombineMode(self.combine_mode))


@dataclass(frozen=True, slots=True)
class VectorCoverageItem:
    """Retain one semantic QPane vector object as authored coverage."""

    item_id: uuid.UUID
    geometry: VectorObject
    combine_mode: CoverageCombineMode = CoverageCombineMode.ADD
    transform: LayerTransform = field(default_factory=LayerTransform)
    feather_radius: float = 0.0

    def __post_init__(self) -> None:
        """Validate coverage-specific presentation values."""
        radius = float(self.feather_radius)
        if not math.isfinite(radius) or radius < 0.0:
            raise ValueError("coverage feather radius must be finite and non-negative")
        object.__setattr__(self, "combine_mode", CoverageCombineMode(self.combine_mode))
        object.__setattr__(self, "feather_radius", radius)


@dataclass(frozen=True, slots=True)
class StrokeCoverageItem:
    """Retain deterministic brush segments without flattening their authorship."""

    item_id: uuid.UUID
    segments: tuple[BrushStrokeSegment, ...]
    combine_mode: CoverageCombineMode = CoverageCombineMode.ADD
    transform: LayerTransform = field(default_factory=LayerTransform)

    def __post_init__(self) -> None:
        """Detach ordered stroke segments and normalize the combine operation."""
        segments = tuple(self.segments)
        if not segments:
            raise ValueError("coverage stroke items require at least one segment")
        object.__setattr__(self, "segments", segments)
        object.__setattr__(self, "combine_mode", CoverageCombineMode(self.combine_mode))


CoverageItem: TypeAlias = RasterCoverageItem | VectorCoverageItem | StrokeCoverageItem


@dataclass(frozen=True, slots=True)
class CoverageDocument:
    """Own one ordered, immutable hybrid coverage expression."""

    document_id: uuid.UUID = field(default_factory=uuid.uuid4)
    items: tuple[CoverageItem, ...] = ()
    revision: int = 0
    evaluation_token: uuid.UUID = field(
        default_factory=uuid.uuid4,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        """Validate stable item identity and revision state."""
        items = tuple(self.items)
        item_ids = tuple(item.item_id for item in items)
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("coverage item IDs must be unique within a document")
        if self.revision < 0:
            raise ValueError("coverage document revision must be non-negative")
        object.__setattr__(self, "items", items)

    def item(self, item_id: uuid.UUID) -> CoverageItem | None:
        """Return one authored item by stable identity."""
        return next((item for item in self.items if item.item_id == item_id), None)

    def add(self, item: CoverageItem, index: int | None = None) -> CoverageDocument:
        """Return a new revision with ``item`` inserted once."""
        if self.item(item.item_id) is not None:
            raise ValueError("coverage item ID already exists")
        items = list(self.items)
        target = len(items) if index is None else max(0, min(int(index), len(items)))
        items.insert(target, item)
        return replace(
            self,
            items=tuple(items),
            revision=self.revision + 1,
            evaluation_token=uuid.uuid4(),
        )

    def replace_item(self, item: CoverageItem) -> CoverageDocument:
        """Return a new revision replacing an existing authored item."""
        if self.item(item.item_id) is None:
            raise KeyError(item.item_id)
        items = tuple(
            item if candidate.item_id == item.item_id else candidate
            for candidate in self.items
        )
        return (
            self
            if items == self.items
            else replace(
                self,
                items=items,
                revision=self.revision + 1,
                evaluation_token=uuid.uuid4(),
            )
        )

    def remove(self, item_id: uuid.UUID) -> CoverageDocument:
        """Return a new revision without ``item_id``."""
        items = tuple(item for item in self.items if item.item_id != item_id)
        return (
            self
            if len(items) == len(self.items)
            else replace(
                self,
                items=items,
                revision=self.revision + 1,
                evaluation_token=uuid.uuid4(),
            )
        )

    def clear(self) -> CoverageDocument:
        """Return an empty revision while preserving document identity."""
        return (
            self
            if not self.items
            else replace(
                self,
                items=(),
                revision=self.revision + 1,
                evaluation_token=uuid.uuid4(),
            )
        )

    def replaced_by(self, item: CoverageItem) -> CoverageDocument:
        """Return a new revision containing exactly one authored item."""
        return replace(
            self,
            items=(item,),
            revision=self.revision + 1,
            evaluation_token=uuid.uuid4(),
        )
