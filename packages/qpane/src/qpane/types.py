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
"""Public viewer and rendering value types."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from PySide6.QtCore import QLineF, QPointF, QRect, QRectF, QSize
from PySide6.QtGui import QImage, QTransform

__all__ = [
    "CacheMode",
    "CatalogEntry",
    "ComparisonDividerState",
    "ComparisonOrientation",
    "ComparisonState",
    "DiagnosticRecord",
    "DiagnosticsDomain",
    "LinkedGroup",
    "OverlayState",
    "PlaceholderScaleMode",
    "SceneSnapshotOverlayLayer",
    "SceneSnapshotOverlayState",
    "ZoomMode",
]


class CacheMode(str, Enum):
    """Cache budgeting strategy."""

    AUTO = "auto"
    HARD = "hard"


class PlaceholderScaleMode(str, Enum):
    """Scaling rule applied to placeholder assets."""

    AUTO = "auto"
    LOGICAL_FIT = "logical_fit"
    PHYSICAL_FIT = "physical_fit"
    RELATIVE_FIT = "relative_fit"


class ZoomMode(str, Enum):
    """Zoom policy used by placeholder rendering."""

    FIT = "fit"
    LOCKED_ZOOM = "locked_zoom"
    LOCKED_SIZE = "locked_size"


class DiagnosticsDomain(str, Enum):
    """Diagnostics categories exposed through the facade."""

    CACHE = "cache"
    SWAP = "swap"
    RENDER = "render"
    EXECUTOR = "executor"
    RETRY = "retry"


class ComparisonOrientation(str, Enum):
    """Comparison split orientations supported by the facade."""

    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """Structured catalog entry containing image data and an optional path."""

    image: QImage
    path: Path | None


@dataclass(frozen=True, slots=True)
class LinkedGroup:
    """Linked-view group descriptor with a stable identifier."""

    group_id: uuid.UUID
    members: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class ComparisonState:
    """Public snapshot of the active comparison setup."""

    enabled: bool
    source_id: uuid.UUID | None
    source_path: Path | None
    source_kind: str | None
    split_position: float
    orientation: ComparisonOrientation


@dataclass(frozen=True, slots=True)
class ComparisonDividerState:
    """Public snapshot of comparison divider interaction geometry."""

    enabled: bool = False
    interactive: bool = False
    hovered: bool = False
    dragging: bool = False
    orientation: ComparisonOrientation = ComparisonOrientation.VERTICAL
    hit_width: float = 0.0
    full_segment: QLineF | None = None
    visible_segment: QLineF | None = None

    def __post_init__(self) -> None:
        """Detach mutable Qt line values from internal geometry."""
        if self.full_segment is not None:
            object.__setattr__(self, "full_segment", QLineF(self.full_segment))
        if self.visible_segment is not None:
            object.__setattr__(
                self,
                "visible_segment",
                QLineF(self.visible_segment),
            )


@dataclass(frozen=True, slots=True)
class DiagnosticRecord:
    """Single name/value diagnostic entry shown in overlays."""

    label: str
    value: str

    def formatted(self) -> str:
        """Return a human-friendly string for display."""
        if not self.label:
            return self.value
        return f"{self.label}: {self.value}"

    def __str__(self) -> str:  # pragma: no cover - formatting helper
        """Return the formatted representation for inline rendering."""
        return self.formatted()


@dataclass(frozen=True, slots=True)
class OverlayState:
    """Stable overlay context describing the current view and render snapshot."""

    zoom: float
    qpane_rect: QRect
    source_image: QImage
    transform: QTransform
    current_pan: QPointF
    physical_viewport_rect: QRectF


@dataclass(frozen=True, slots=True)
class SceneSnapshotOverlayLayer:
    """Source-neutral overlay geometry for one rendered scene layer."""

    layer_id: uuid.UUID
    source_id: uuid.UUID | None
    role: str
    label: str | None
    metadata: Mapping[str, object]
    placement: QRectF
    source_size: QSize
    transform: QTransform
    panel_bounds: QRectF
    visible: bool

    def __post_init__(self) -> None:
        """Detach mutable overlay geometry and protect metadata from mutation."""
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        object.__setattr__(self, "placement", QRectF(self.placement))
        object.__setattr__(self, "source_size", QSize(self.source_size))
        object.__setattr__(self, "transform", QTransform(self.transform))
        object.__setattr__(self, "panel_bounds", QRectF(self.panel_bounds))


@dataclass(frozen=True, slots=True)
class SceneSnapshotOverlayState:
    """Stable overlay context for host chrome drawn relative to scene layers."""

    zoom: float
    qpane_rect: QRect
    physical_viewport_rect: QRectF
    scene_id: uuid.UUID
    scene_bounds: QRectF
    layers: tuple[SceneSnapshotOverlayLayer, ...]

    def __post_init__(self) -> None:
        """Detach mutable Qt values from internal render-plan state."""
        object.__setattr__(self, "qpane_rect", QRect(self.qpane_rect))
        object.__setattr__(
            self,
            "physical_viewport_rect",
            QRectF(self.physical_viewport_rect),
        )
        object.__setattr__(self, "scene_bounds", QRectF(self.scene_bounds))
        object.__setattr__(self, "layers", tuple(self.layers))


def __getattr__(name: str) -> Any:
    """Resolve catalog mutation values lazily to avoid a catalog cycle."""
    if name == "CatalogMutationEvent":
        from .catalog.catalog import CatalogMutationEvent

        return CatalogMutationEvent
    raise AttributeError(f"module {__name__!s} has no attribute {name}")
