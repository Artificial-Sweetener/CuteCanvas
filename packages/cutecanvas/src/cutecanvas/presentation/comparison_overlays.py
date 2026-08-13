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

"""Define host-owned artwork that follows a native comparison divider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QLineF, QPointF, QRect
from PySide6.QtGui import QPainter

from qpane.sdk.types import ComparisonOrientation

from ..document import CanvasComparison


@dataclass(frozen=True, slots=True)
class CanvasComparisonDivider:
    """Describe the current physical divider without exposing a renderer widget."""

    enabled: bool
    split_position: float
    orientation: ComparisonOrientation | None
    visible_segment: QLineF | None
    full_segment: QLineF | None

    @classmethod
    def from_comparison_state(cls, state: object) -> CanvasComparisonDivider:
        """Copy the renderer-owned divider snapshot into a CuteCanvas value."""

        visible_segment = getattr(state, "visible_segment", None)
        full_segment = getattr(state, "full_segment", None)
        return cls(
            enabled=bool(getattr(state, "enabled", False)),
            split_position=float(getattr(state, "split_position", 0.5)),
            orientation=getattr(state, "orientation", None),
            visible_segment=(
                QLineF(visible_segment) if isinstance(visible_segment, QLineF) else None
            ),
            full_segment=(
                QLineF(full_segment) if isinstance(full_segment, QLineF) else None
            ),
        )


@dataclass(frozen=True, slots=True)
class CanvasComparisonScale:
    """Describe one compared source's physical display scale per source pixel."""

    horizontal: float
    vertical: float


@dataclass(frozen=True, slots=True)
class CanvasComparisonZoomGesture:
    """Describe one pointer-originated comparison zoom without exposing QPane."""

    position: QPointF
    zoom: float

    def __post_init__(self) -> None:
        """Detach the mutable Qt point supplied by the native event stream."""

        object.__setattr__(self, "position", QPointF(self.position))


@dataclass(frozen=True, slots=True)
class CanvasComparisonOverlayState:
    """Give a comparison overlay the immutable state needed for one paint."""

    comparison: CanvasComparison
    divider: CanvasComparisonDivider
    viewport: QRect
    primary_scale: CanvasComparisonScale
    secondary_scale: CanvasComparisonScale

    def __post_init__(self) -> None:
        """Detach the mutable viewport supplied by the native render snapshot."""

        object.__setattr__(self, "viewport", QRect(self.viewport))


CanvasComparisonOverlayDrawFn = Callable[[QPainter, CanvasComparisonOverlayState], None]
"""Paint host artwork over the current comparison using widget coordinates."""


__all__ = [
    "CanvasComparisonDivider",
    "CanvasComparisonOverlayDrawFn",
    "CanvasComparisonOverlayState",
    "CanvasComparisonScale",
    "CanvasComparisonZoomGesture",
]
