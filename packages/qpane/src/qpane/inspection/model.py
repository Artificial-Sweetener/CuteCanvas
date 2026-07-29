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
"""Immutable target and viewport values for normalized inspection."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QPointF, QRectF


class InspectionZoomMode(str, Enum):
    """Target-local zoom modes carried by inspection snapshots."""

    CUSTOM = "custom"
    FIT = "fit"
    ONE_TO_ONE = "one-to-one"


@dataclass(frozen=True, slots=True)
class InspectionTarget:
    """Identify one inspectable coordinate space and its intrinsic bounds."""

    target_id: uuid.UUID
    bounds: QRectF

    def __post_init__(self) -> None:
        """Validate identity and detach mutable Qt geometry."""
        if not isinstance(self.target_id, uuid.UUID):
            raise TypeError("target_id must be a UUID")
        bounds = QRectF(self.bounds)
        if not bounds.isValid() or bounds.width() <= 0.0 or bounds.height() <= 0.0:
            raise ValueError("inspection target bounds must be positive")
        object.__setattr__(self, "bounds", bounds)


@dataclass(frozen=True, slots=True)
class InspectionRegion:
    """Describe normalized center and target span per physical display pixel."""

    center_x: float
    center_y: float
    span_x: float
    span_y: float

    def __post_init__(self) -> None:
        """Reject non-finite centers and non-positive spans."""
        values = (self.center_x, self.center_y, self.span_x, self.span_y)
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("inspection region values must be finite")
        if self.span_x <= 0.0 or self.span_y <= 0.0:
            raise ValueError("inspection region spans must be positive")


@dataclass(frozen=True, slots=True)
class InspectionViewState:
    """Pair normalized inspection geometry with target-local zoom interpretation."""

    region: InspectionRegion
    zoom_mode: InspectionZoomMode = InspectionZoomMode.CUSTOM

    def __post_init__(self) -> None:
        """Normalize enum-like zoom mode values."""
        object.__setattr__(self, "zoom_mode", InspectionZoomMode(self.zoom_mode))


@dataclass(frozen=True, slots=True)
class ProjectedViewport:
    """Describe the viewport transform derived for one inspection target."""

    zoom: float
    pan: QPointF
    zoom_mode: InspectionZoomMode

    def __post_init__(self) -> None:
        """Validate transform values and detach the Qt point."""
        if not math.isfinite(float(self.zoom)) or self.zoom <= 0.0:
            raise ValueError("projected viewport zoom must be positive and finite")
        pan = QPointF(self.pan)
        if not math.isfinite(pan.x()) or not math.isfinite(pan.y()):
            raise ValueError("projected viewport pan must be finite")
        object.__setattr__(self, "pan", pan)
        object.__setattr__(self, "zoom_mode", InspectionZoomMode(self.zoom_mode))


@dataclass(frozen=True, slots=True)
class InspectionUpdate:
    """Announce a linked inspection revision to subscribed target views."""

    generation: int
    source_target_id: uuid.UUID
    target_id: uuid.UUID
    state: InspectionViewState
