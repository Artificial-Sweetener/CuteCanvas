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

"""Compute conservative target-local bounds for affine brush tips."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF

from qpane.sdk.scene import RasterBounds

from .model import BrushDab


def brush_dab_bounds(dab: BrushDab) -> RasterBounds:
    """Return antialias-safe target-local bounds for one transformed dab."""

    radius = dab.diameter / 2.0 + 1.0
    if dab.tip_mapping is not None:
        center = dab.tip_mapping.map_point(
            QPointF(float(dab.center[0]), float(dab.center[1]))
        )
        rectangle = dab.tip_mapping.inverse_map_rect(
            QRectF(
                center.x() - radius,
                center.y() - radius,
                radius * 2.0,
                radius * 2.0,
            )
        )
        left = math.floor(rectangle.left())
        top = math.floor(rectangle.top())
        right = math.ceil(rectangle.right())
        bottom = math.ceil(rectangle.bottom())
        return RasterBounds(left, top, max(1, right - left), max(1, bottom - top))
    transform = dab.tip_transform
    extent_x = radius * math.hypot(transform.m11, transform.m21)
    extent_y = radius * math.hypot(transform.m12, transform.m22)
    left = math.floor(dab.center[0] - extent_x)
    top = math.floor(dab.center[1] - extent_y)
    right = math.ceil(dab.center[0] + extent_x)
    bottom = math.ceil(dab.center[1] + extent_y)
    return RasterBounds(left, top, max(1, right - left), max(1, bottom - top))


__all__ = ["brush_dab_bounds"]
