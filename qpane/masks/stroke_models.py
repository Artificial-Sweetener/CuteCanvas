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

"""Immutable payload models exchanged by the mask stroke pipeline."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage


@dataclass(frozen=True, slots=True)
class MaskStrokeSegmentPayload:
    """Describe one fixed- or variable-width mask stroke segment."""

    start: tuple[float, float]
    end: tuple[float, float]
    start_diameter: float
    end_diameter: float
    erase: bool

    @classmethod
    def fixed(
        cls,
        start: tuple[float, float],
        end: tuple[float, float],
        diameter: float,
        erase: bool,
    ) -> "MaskStrokeSegmentPayload":
        """Create a constant-width segment."""
        return cls(
            start=start,
            end=end,
            start_diameter=diameter,
            end_diameter=diameter,
            erase=erase,
        )

    @property
    def maximum_diameter(self) -> float:
        """Return the widest endpoint diameter."""
        return max(1.0, float(self.start_diameter), float(self.end_diameter))


@dataclass(frozen=True, slots=True)
class MaskStrokePayload:
    """Bundle stroke segments and stride metadata for worker replays."""

    segments: tuple[MaskStrokeSegmentPayload, ...]
    stride: int = 1
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MaskStrokeJobSpec:
    """Describe a mask stroke job prepared on the UI thread."""

    mask_id: uuid.UUID
    generation: int
    dirty_rect: QRect
    before: np.ndarray
    payload: MaskStrokePayload | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MaskStrokeJobResult:
    """Capture the outcome of a mask stroke ready for main-thread merging."""

    mask_id: uuid.UUID
    generation: int
    dirty_rect: QRect
    before: np.ndarray
    after: np.ndarray
    preview_image: QImage | None = None
    payload: MaskStrokePayload | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
