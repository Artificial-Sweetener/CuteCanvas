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
"""Immutable source-neutral values for editor snapping and smart guides."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QPointF, QRectF


class SnapAxis(str, Enum):
    """Identify independently resolved snapping axes."""

    X = "x"
    Y = "y"


class SnapFeatureKind(str, Enum):
    """Identify visible geometry features participating in snapping."""

    START = "start"
    CENTER = "center"
    END = "end"
    GUIDE = "guide"
    GRID = "grid"


@dataclass(frozen=True, slots=True)
class SnapCandidate:
    """Describe one stationary feature in scene coordinates."""

    owner_id: str
    axis: SnapAxis
    position: float
    kind: SnapFeatureKind
    span_start: float
    span_end: float
    priority: int = 0
    accepts_cross_feature: bool = False


@dataclass(frozen=True, slots=True)
class SnapGuide:
    """Describe one smart guide associated with an applied snap."""

    axis: SnapAxis
    position: float
    span_start: float
    span_end: float
    source_owner_id: str
    target_owner_id: str


@dataclass(frozen=True, slots=True)
class SnapResult:
    """Return corrected movement and presentation guides for one update."""

    delta: QPointF
    guides: tuple[SnapGuide, ...] = ()
    snapped_x: bool = False
    snapped_y: bool = False

    def __post_init__(self) -> None:
        """Detach mutable Qt geometry."""
        object.__setattr__(self, "delta", QPointF(self.delta))


@dataclass(frozen=True, slots=True)
class SnapGrid:
    """Describe an infinite regular grid and finite smart-guide span."""

    origin: QPointF
    spacing_x: float
    spacing_y: float
    guide_span: QRectF
    priority: int = 5

    def __post_init__(self) -> None:
        """Detach Qt geometry and require positive grid spacing."""
        if self.spacing_x <= 0.0 or self.spacing_y <= 0.0:
            raise ValueError("grid spacing must be positive")
        object.__setattr__(self, "origin", QPointF(self.origin))
        object.__setattr__(self, "guide_span", QRectF(self.guide_span).normalized())


def bounds_candidates(
    owner_id: str,
    bounds: QRectF,
    *,
    priority: int = 0,
    cross_feature_center: bool = False,
) -> tuple[SnapCandidate, ...]:
    """Return side and center candidates for positive scene bounds."""
    rectangle = bounds.normalized()
    if rectangle.isEmpty():
        return ()
    horizontal = (
        (rectangle.left(), SnapFeatureKind.START),
        (rectangle.center().x(), SnapFeatureKind.CENTER),
        (rectangle.right(), SnapFeatureKind.END),
    )
    vertical = (
        (rectangle.top(), SnapFeatureKind.START),
        (rectangle.center().y(), SnapFeatureKind.CENTER),
        (rectangle.bottom(), SnapFeatureKind.END),
    )
    return (
        *(
            SnapCandidate(
                owner_id,
                SnapAxis.X,
                position,
                kind,
                rectangle.top(),
                rectangle.bottom(),
                priority,
                cross_feature_center and kind is SnapFeatureKind.CENTER,
            )
            for position, kind in horizontal
        ),
        *(
            SnapCandidate(
                owner_id,
                SnapAxis.Y,
                position,
                kind,
                rectangle.left(),
                rectangle.right(),
                priority,
                cross_feature_center and kind is SnapFeatureKind.CENTER,
            )
            for position, kind in vertical
        ),
    )
