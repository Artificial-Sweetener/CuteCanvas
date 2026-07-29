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
"""Expose renderer-neutral state for CuteCanvas viewport overlays."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import hypot

from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import QImage, QPainter, QTransform
from qpane.sdk.types import OverlayState


@dataclass(frozen=True, slots=True)
class CanvasDisplayScale:
    """Describe physical display pixels occupied by one source pixel."""

    horizontal: float
    vertical: float


@dataclass(frozen=True, slots=True)
class CanvasOverlayState:
    """Describe one CuteCanvas view at the instant a viewport overlay paints."""

    zoom: float
    viewport: QRect
    source_image: QImage
    transform: QTransform
    pan: QPointF
    physical_viewport: QRectF

    @property
    def display_scale(self) -> CanvasDisplayScale:
        """Return the source's physical scale from actual render geometry."""

        logical_width = self.viewport.width()
        logical_height = self.viewport.height()
        if logical_width > 0:
            device_pixel_ratio = self.physical_viewport.width() / logical_width
        elif logical_height > 0:
            device_pixel_ratio = self.physical_viewport.height() / logical_height
        else:
            device_pixel_ratio = 1.0
        device_pixel_ratio = max(0.01, device_pixel_ratio)
        return CanvasDisplayScale(
            hypot(self.transform.m11(), self.transform.m12()) * device_pixel_ratio,
            hypot(self.transform.m21(), self.transform.m22()) * device_pixel_ratio,
        )

    @classmethod
    def from_native(cls, state: OverlayState) -> CanvasOverlayState:
        """Translate QPane's private overlay state at the CuteCanvas boundary."""

        return cls(
            zoom=state.zoom,
            viewport=QRect(state.qpane_rect),
            source_image=state.source_image,
            transform=QTransform(state.transform),
            pan=QPointF(state.current_pan),
            physical_viewport=QRectF(state.physical_viewport_rect),
        )


CanvasOverlayDrawFn = Callable[[QPainter, CanvasOverlayState], None]


__all__ = ["CanvasDisplayScale", "CanvasOverlayDrawFn", "CanvasOverlayState"]
