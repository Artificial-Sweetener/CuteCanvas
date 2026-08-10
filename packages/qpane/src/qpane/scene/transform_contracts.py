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
"""Immutable contracts for affine transform-box interaction."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QPointF


class TransformHandle(str, Enum):
    """Identify one transform-box edit point."""

    TOP_LEFT = "top-left"
    TOP = "top"
    TOP_RIGHT = "top-right"
    RIGHT = "right"
    BOTTOM_RIGHT = "bottom-right"
    BOTTOM = "bottom"
    BOTTOM_LEFT = "bottom-left"
    LEFT = "left"


class TransformOperationKind(str, Enum):
    """Describe the affine operation selected by transform hit testing."""

    MOVE = "move"
    SCALE = "scale"
    ROTATE = "rotate"
    SKEW = "skew"


@dataclass(frozen=True, slots=True)
class TransformOperation:
    """Pair one transform operation with its optional box handle."""

    kind: TransformOperationKind
    handle: TransformHandle | None = None

    def __post_init__(self) -> None:
        """Require handles exactly for scale and skew operations."""
        requires_handle = self.kind in {
            TransformOperationKind.SCALE,
            TransformOperationKind.SKEW,
        }
        if requires_handle != (self.handle is not None):
            raise ValueError("scale and skew operations require one transform handle")


@dataclass(frozen=True, slots=True)
class TransformModifiers:
    """Describe the constraint policy active for one pointer update."""

    proportional: bool = True
    about_center: bool = False
    snap_rotation: bool = False


@dataclass(frozen=True, slots=True)
class TransformLocalBounds:
    """Store positive source-local content bounds without mutable Qt state."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        """Reject unusable transform target geometry."""
        values = (self.x, self.y, self.width, self.height)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("transform bounds must be finite")
        if self.width <= 0.0 or self.height <= 0.0:
            raise ValueError("transform bounds must have positive dimensions")

    @property
    def center(self) -> QPointF:
        """Return the detached local center point."""
        return QPointF(self.x + self.width * 0.5, self.y + self.height * 0.5)

    def point(self, handle: TransformHandle) -> QPointF:
        """Return the local corner or side midpoint for ``handle``."""
        left = self.x
        center_x = self.x + self.width * 0.5
        right = self.x + self.width
        top = self.y
        center_y = self.y + self.height * 0.5
        bottom = self.y + self.height
        return {
            TransformHandle.TOP_LEFT: QPointF(left, top),
            TransformHandle.TOP: QPointF(center_x, top),
            TransformHandle.TOP_RIGHT: QPointF(right, top),
            TransformHandle.RIGHT: QPointF(right, center_y),
            TransformHandle.BOTTOM_RIGHT: QPointF(right, bottom),
            TransformHandle.BOTTOM: QPointF(center_x, bottom),
            TransformHandle.BOTTOM_LEFT: QPointF(left, bottom),
            TransformHandle.LEFT: QPointF(left, center_y),
        }[handle]

    def opposite(self, handle: TransformHandle) -> QPointF:
        """Return the fixed opposite point for one scale handle."""
        opposite = {
            TransformHandle.TOP_LEFT: TransformHandle.BOTTOM_RIGHT,
            TransformHandle.TOP: TransformHandle.BOTTOM,
            TransformHandle.TOP_RIGHT: TransformHandle.BOTTOM_LEFT,
            TransformHandle.RIGHT: TransformHandle.LEFT,
            TransformHandle.BOTTOM_RIGHT: TransformHandle.TOP_LEFT,
            TransformHandle.BOTTOM: TransformHandle.TOP,
            TransformHandle.BOTTOM_LEFT: TransformHandle.TOP_RIGHT,
            TransformHandle.LEFT: TransformHandle.RIGHT,
        }
        return self.point(opposite[handle])


__all__ = [
    "TransformHandle",
    "TransformLocalBounds",
    "TransformModifiers",
    "TransformOperation",
    "TransformOperationKind",
]
