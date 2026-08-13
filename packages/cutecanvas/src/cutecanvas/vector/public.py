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
"""Detached vector-authoring session values."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from PySide6.QtCore import QRectF
from PySide6.QtGui import QTransform

from qpane.sdk.vector import (
    VectorNodeRole,
    VectorObjectKind,
    VectorPathCommand,
    VectorShapeKind,
    VectorStyle,
    VectorTextContent,
)


@dataclass(frozen=True, slots=True)
class VectorObjectSnapshot:
    """Expose one detached semantic vector object snapshot."""

    object_id: uuid.UUID
    kind: VectorObjectKind
    bounds: QRectF
    transform: QTransform
    style: VectorStyle
    shape_kind: VectorShapeKind | None = None
    path: tuple[VectorPathCommand, ...] = ()
    text: VectorTextContent | None = None

    def __post_init__(self) -> None:
        """Detach mutable Qt values and normalize enum fields."""
        object.__setattr__(self, "kind", VectorObjectKind(self.kind))
        object.__setattr__(self, "bounds", QRectF(self.bounds))
        object.__setattr__(self, "transform", QTransform(self.transform))
        object.__setattr__(
            self,
            "style",
            VectorStyle(
                fill=self.style.fill,
                stroke=self.style.stroke,
                stroke_width=self.style.stroke_width,
                opacity=self.style.opacity,
                join=self.style.join,
                cap=self.style.cap,
                dash_pattern=self.style.dash_pattern,
                fill_rule=self.style.fill_rule,
            ),
        )
        if self.shape_kind is not None:
            object.__setattr__(self, "shape_kind", VectorShapeKind(self.shape_kind))
        object.__setattr__(self, "path", tuple(self.path))
        if self.text is not None:
            object.__setattr__(
                self,
                "text",
                VectorTextContent(
                    self.text.text,
                    self.text.style,
                    self.text.spans,
                    self.text.paragraph,
                ),
            )


@dataclass(frozen=True, slots=True)
class VectorDocumentSnapshot:
    """Expose one detached ordered vector-document snapshot."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    vector_id: uuid.UUID
    revision: int
    objects: tuple[VectorObjectSnapshot, ...]


@dataclass(frozen=True, slots=True)
class VectorTextEditSnapshot:
    """Expose one active in-place semantic text session."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    object_id: uuid.UUID
    text: str
    cursor: int
    is_new: bool


@dataclass(frozen=True, slots=True)
class VectorSelectionSnapshot:
    """Expose composition-local vector object selection independently."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    object_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class VectorMaskSnapshot:
    """Expose one composition layer's editable semantic vector mask."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    vector_id: uuid.UUID
    object_ids: tuple[uuid.UUID, ...]
    transform: QTransform
    inverted: bool

    def __post_init__(self) -> None:
        """Detach mutable transform state and normalize object identity order."""
        object.__setattr__(self, "object_ids", tuple(self.object_ids))
        object.__setattr__(self, "transform", QTransform(self.transform))


@dataclass(frozen=True, slots=True)
class VectorNodeSelectionSnapshot:
    """Expose the selected control point independently of object selection."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    object_id: uuid.UUID
    node_index: int
    role: VectorNodeRole

    def __post_init__(self) -> None:
        """Normalize detached node identity values."""
        if self.node_index < 0:
            raise ValueError("vector node index must be non-negative")
        object.__setattr__(self, "role", VectorNodeRole(self.role))
