#    QPane - High-performance PySide6 image viewer
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
"""Immutable authoritative vector document and object values."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field, replace

from ..scene.affine import LayerTransform
from ..scene.raster import RasterBounds
from .public import (
    VectorObjectKind,
    VectorPathCommand,
    VectorPathCommandKind,
    VectorShapeKind,
    VectorStyle,
    VectorTextContent,
)


@dataclass(frozen=True, slots=True)
class VectorObject:
    """Retain one semantic object's authoritative geometry and style."""

    object_id: uuid.UUID
    kind: VectorObjectKind
    local_bounds: tuple[float, float, float, float]
    transform: LayerTransform
    style: VectorStyle
    shape_kind: VectorShapeKind | None = None
    path: tuple[VectorPathCommand, ...] = ()
    text: VectorTextContent | None = None

    def __post_init__(self) -> None:
        """Validate semantic geometry and detach mutable style values."""
        kind = VectorObjectKind(self.kind)
        bounds = tuple(float(value) for value in self.local_bounds)
        if len(bounds) != 4 or not all(math.isfinite(value) for value in bounds):
            raise ValueError("vector object bounds must contain four finite values")
        if bounds[2] < 0.0 or bounds[3] < 0.0:
            raise ValueError("vector object bounds dimensions must be non-negative")
        shape_kind = (
            None if self.shape_kind is None else VectorShapeKind(self.shape_kind)
        )
        path = tuple(self.path)
        if kind is VectorObjectKind.SHAPE and shape_kind is None:
            raise ValueError("shape objects require a parametric shape kind")
        if kind is not VectorObjectKind.SHAPE and shape_kind is not None:
            raise ValueError("only shape objects may have a parametric shape kind")
        if kind is VectorObjectKind.PATH:
            if not path or path[0].kind is not VectorPathCommandKind.MOVE:
                raise ValueError("path objects must begin with a move command")
        elif path:
            raise ValueError("only path objects may contain path commands")
        text = self.text
        if kind is VectorObjectKind.TEXT:
            if text is None:
                raise ValueError("text objects require semantic text content")
        elif text is not None:
            raise ValueError("only text objects may contain semantic text content")
        style = VectorStyle(
            fill=self.style.fill,
            stroke=self.style.stroke,
            stroke_width=self.style.stroke_width,
            opacity=self.style.opacity,
            join=self.style.join,
            cap=self.style.cap,
            dash_pattern=self.style.dash_pattern,
            fill_rule=self.style.fill_rule,
        )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "local_bounds", bounds)
        object.__setattr__(self, "style", style)
        object.__setattr__(self, "shape_kind", shape_kind)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "text", text)


@dataclass(frozen=True, slots=True)
class VectorDocument:
    """Own ordered stable vector objects at one immutable revision."""

    vector_id: uuid.UUID
    bounds: RasterBounds
    objects: tuple[VectorObject, ...] = ()
    revision: int = 0
    retained_bytes: int = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate one immutable ordered document revision."""
        objects = tuple(self.objects)
        object_ids = tuple(item.object_id for item in objects)
        if len(set(object_ids)) != len(object_ids):
            raise ValueError("vector object IDs must be unique within a document")
        if self.revision < 0:
            raise ValueError("vector document revision must be non-negative")
        object.__setattr__(self, "objects", objects)
        point_count = sum(
            len(command.points) for item in objects for command in item.path
        )
        text_bytes = sum(
            len(item.text.text.encode("utf-8")) + len(item.text.spans) * 192
            for item in objects
            if item.text is not None
        )
        object.__setattr__(
            self,
            "retained_bytes",
            len(objects) * 384 + point_count * 32 + text_bytes,
        )

    def object(self, object_id: uuid.UUID) -> VectorObject | None:
        """Return one object by stable identity."""
        return next(
            (item for item in self.objects if item.object_id == object_id),
            None,
        )

    def add(self, item: VectorObject, index: int | None = None) -> VectorDocument:
        """Return a new revision with ``item`` inserted once."""
        if self.object(item.object_id) is not None:
            raise ValueError("vector object ID already exists")
        objects = list(self.objects)
        target = len(objects) if index is None else max(0, min(index, len(objects)))
        objects.insert(target, item)
        return replace(self, objects=tuple(objects), revision=self.revision + 1)

    def replace_object(self, item: VectorObject) -> VectorDocument:
        """Return a new revision replacing one existing object."""
        objects = tuple(
            item if candidate.object_id == item.object_id else candidate
            for candidate in self.objects
        )
        if objects == self.objects:
            return self
        if self.object(item.object_id) is None:
            raise KeyError(item.object_id)
        return replace(self, objects=objects, revision=self.revision + 1)

    def remove(self, object_id: uuid.UUID) -> VectorDocument:
        """Return a new revision without ``object_id``."""
        objects = tuple(item for item in self.objects if item.object_id != object_id)
        return (
            self
            if len(objects) == len(self.objects)
            else replace(self, objects=objects, revision=self.revision + 1)
        )

    def reorder(self, object_id: uuid.UUID, index: int) -> VectorDocument:
        """Return a new revision with one object at a clamped order index."""
        item = self.object(object_id)
        if item is None:
            return self
        objects = [candidate for candidate in self.objects if candidate != item]
        objects.insert(max(0, min(int(index), len(objects))), item)
        ordered = tuple(objects)
        return (
            self
            if ordered == self.objects
            else replace(self, objects=ordered, revision=self.revision + 1)
        )
