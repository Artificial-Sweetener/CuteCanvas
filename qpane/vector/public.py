#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Detached public vector values used by QPane's additive editor facade."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QTransform


class VectorObjectKind(str, Enum):
    """Identify semantic vector object categories."""

    PATH = "path"
    SHAPE = "shape"
    TEXT = "text"


class VectorShapeKind(str, Enum):
    """Identify parametric shapes that retain editable parameters."""

    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"


class VectorPathCommandKind(str, Enum):
    """Identify serializable path command operations."""

    MOVE = "move"
    LINE = "line"
    QUADRATIC = "quadratic"
    CUBIC = "cubic"
    CLOSE = "close"


class VectorFillRule(str, Enum):
    """Identify vector fill winding behavior."""

    WINDING = "winding"
    EVEN_ODD = "even-odd"


class VectorStrokeJoin(str, Enum):
    """Identify line-join rendering behavior."""

    MITER = "miter"
    ROUND = "round"
    BEVEL = "bevel"


class VectorStrokeCap(str, Enum):
    """Identify line-cap rendering behavior."""

    FLAT = "flat"
    ROUND = "round"
    SQUARE = "square"


class VectorNodeRole(str, Enum):
    """Identify the semantic role of one editable vector handle."""

    ANCHOR = "anchor"
    CONTROL = "control"
    BOUNDS = "bounds"


class VectorTextAlignment(str, Enum):
    """Identify paragraph alignment inside a semantic text box."""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"


class VectorTextDirection(str, Enum):
    """Identify requested paragraph direction and automatic resolution."""

    AUTO = "auto"
    LEFT_TO_RIGHT = "left-to-right"
    RIGHT_TO_LEFT = "right-to-left"


@dataclass(frozen=True, slots=True)
class VectorPathCommand:
    """Describe one durable path command and its ordered control points."""

    kind: VectorPathCommandKind
    points: tuple[QPointF, ...] = ()

    def __post_init__(self) -> None:
        """Normalize the kind and detach finite point values."""
        kind = VectorPathCommandKind(self.kind)
        points = tuple(QPointF(point) for point in self.points)
        expected = {
            VectorPathCommandKind.MOVE: 1,
            VectorPathCommandKind.LINE: 1,
            VectorPathCommandKind.QUADRATIC: 2,
            VectorPathCommandKind.CUBIC: 3,
            VectorPathCommandKind.CLOSE: 0,
        }[kind]
        if len(points) != expected:
            raise ValueError(f"{kind.value} requires {expected} points")
        if any(
            not math.isfinite(point.x()) or not math.isfinite(point.y())
            for point in points
        ):
            raise ValueError("vector path points must be finite")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "points", points)

    @classmethod
    def _from_finite_points(
        cls,
        kind: VectorPathCommandKind,
        points: tuple[QPointF, ...],
    ) -> VectorPathCommand:
        """Build from owner-validated detached finite points without rechecking."""
        command = object.__new__(cls)
        object.__setattr__(command, "kind", kind)
        object.__setattr__(command, "points", points)
        return command


@dataclass(frozen=True, slots=True)
class VectorStyle:
    """Describe detached fill, stroke, opacity, and stroke geometry."""

    fill: QColor | None = field(default_factory=lambda: QColor(70, 150, 240, 180))
    stroke: QColor | None = field(default_factory=lambda: QColor(35, 80, 150, 255))
    stroke_width: float = 2.0
    opacity: float = 1.0
    join: VectorStrokeJoin = VectorStrokeJoin.ROUND
    cap: VectorStrokeCap = VectorStrokeCap.ROUND
    dash_pattern: tuple[float, ...] = ()
    fill_rule: VectorFillRule = VectorFillRule.WINDING

    def __post_init__(self) -> None:
        """Detach colors and validate finite non-negative style values."""
        fill = None if self.fill is None else QColor(self.fill)
        stroke = None if self.stroke is None else QColor(self.stroke)
        if fill is not None and not fill.isValid():
            raise ValueError("vector fill must be a valid QColor or None")
        if stroke is not None and not stroke.isValid():
            raise ValueError("vector stroke must be a valid QColor or None")
        if not math.isfinite(self.stroke_width) or self.stroke_width < 0.0:
            raise ValueError("vector stroke width must be finite and non-negative")
        if not math.isfinite(self.opacity) or not 0.0 <= self.opacity <= 1.0:
            raise ValueError("vector opacity must be finite and between 0 and 1")
        dashes = tuple(float(value) for value in self.dash_pattern)
        if any(not math.isfinite(value) or value <= 0.0 for value in dashes):
            raise ValueError("vector dash lengths must be finite and positive")
        object.__setattr__(self, "fill", fill)
        object.__setattr__(self, "stroke", stroke)
        object.__setattr__(self, "join", VectorStrokeJoin(self.join))
        object.__setattr__(self, "cap", VectorStrokeCap(self.cap))
        object.__setattr__(self, "dash_pattern", dashes)
        object.__setattr__(self, "fill_rule", VectorFillRule(self.fill_rule))


@dataclass(frozen=True, slots=True)
class VectorTextStyle:
    """Describe requested font, size, emphasis, spacing, and foreground."""

    families: tuple[str, ...] = ("Sans Serif",)
    font_size: float = 32.0
    weight: int = 400
    italic: bool = False
    letter_spacing: float = 0.0
    color: QColor = field(default_factory=lambda: QColor(35, 35, 35, 255))

    def __post_init__(self) -> None:
        """Normalize font requests and validate finite style values."""
        families = tuple(
            family.strip()
            for family in self.families
            if isinstance(family, str) and family.strip()
        )
        if not families:
            raise ValueError("text style requires at least one font family")
        if not math.isfinite(self.font_size) or self.font_size <= 0.0:
            raise ValueError("text font size must be finite and positive")
        if not 1 <= int(self.weight) <= 1000:
            raise ValueError("text font weight must be between 1 and 1000")
        if not math.isfinite(self.letter_spacing):
            raise ValueError("text letter spacing must be finite")
        color = QColor(self.color)
        if not color.isValid():
            raise ValueError("text color must be valid")
        object.__setattr__(self, "families", families)
        object.__setattr__(self, "font_size", float(self.font_size))
        object.__setattr__(self, "weight", int(self.weight))
        object.__setattr__(self, "color", color)


@dataclass(frozen=True, slots=True)
class VectorTextSpan:
    """Apply one semantic character style to a Python-codepoint range."""

    start: int
    length: int
    style: VectorTextStyle

    def __post_init__(self) -> None:
        """Validate a non-empty non-negative character range."""
        if self.start < 0 or self.length <= 0:
            raise ValueError(
                "text spans require non-negative start and positive length"
            )


@dataclass(frozen=True, slots=True)
class VectorParagraphStyle:
    """Describe wrapping alignment, direction, and line-height policy."""

    alignment: VectorTextAlignment = VectorTextAlignment.LEFT
    direction: VectorTextDirection = VectorTextDirection.AUTO
    line_height: float = 1.0

    def __post_init__(self) -> None:
        """Normalize enums and validate the line-height multiplier."""
        if not math.isfinite(self.line_height) or self.line_height <= 0.0:
            raise ValueError("text line height must be finite and positive")
        object.__setattr__(self, "alignment", VectorTextAlignment(self.alignment))
        object.__setattr__(self, "direction", VectorTextDirection(self.direction))


@dataclass(frozen=True, slots=True)
class VectorTextContent:
    """Retain editable Unicode text, styles, and paragraph semantics."""

    text: str
    style: VectorTextStyle = field(default_factory=VectorTextStyle)
    spans: tuple[VectorTextSpan, ...] = ()
    paragraph: VectorParagraphStyle = field(default_factory=VectorParagraphStyle)

    def __post_init__(self) -> None:
        """Validate ordered non-overlapping spans against Unicode codepoints."""
        if not isinstance(self.text, str):
            raise TypeError("vector text content must be a string")
        spans = tuple(self.spans)
        end = 0
        for span in spans:
            if span.start < end or span.start + span.length > len(self.text):
                raise ValueError(
                    "text spans must be ordered, non-overlapping, and in range"
                )
            end = span.start + span.length
        object.__setattr__(self, "spans", spans)


@dataclass(frozen=True, slots=True)
class QPaneTextFontResolution:
    """Expose one requested font chain and the family selected by Qt."""

    requested_families: tuple[str, ...]
    resolved_family: str
    exact_match: bool


@dataclass(frozen=True, slots=True)
class QPaneVectorTextEditState:
    """Expose one active in-place semantic text session."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    object_id: uuid.UUID
    text: str
    cursor: int
    is_new: bool


@dataclass(frozen=True, slots=True)
class QPaneVectorObjectState:
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
            object.__setattr__(
                self,
                "shape_kind",
                VectorShapeKind(self.shape_kind),
            )
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
class QPaneVectorDocumentState:
    """Expose one detached ordered vector-document snapshot."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    vector_id: uuid.UUID
    revision: int
    objects: tuple[QPaneVectorObjectState, ...]


@dataclass(frozen=True, slots=True)
class QPaneVectorSelectionState:
    """Expose composition-local vector object selection independently."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    object_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class QPaneVectorMaskState:
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
class QPaneVectorNodeSelectionState:
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
