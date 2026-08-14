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
"""Antialiased rasterization of scene-space selection geometry."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPolygonF

from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.types import RasterExtentPolicy
from qpane.sdk.raster import qimage_to_numpy_grayscale8
from qpane.sdk.scene import RasterBounds


class SelectionGeometryRasterizer:
    """Convert vector selection geometry into scene-aligned soft coverage."""

    def rectangle(self, rectangle: QRectF) -> CoverageSnapshot:
        """Rasterize an axis-aligned rectangle in scene coordinates."""
        normalized = rectangle.normalized()
        return self._rasterize(
            normalized,
            lambda painter, offset: painter.drawRect(normalized.translated(offset)),
        )

    def ellipse(self, rectangle: QRectF) -> CoverageSnapshot:
        """Rasterize an ellipse inscribed in a scene-space rectangle."""
        normalized = rectangle.normalized()
        return self._rasterize(
            normalized,
            lambda painter, offset: painter.drawEllipse(normalized.translated(offset)),
        )

    def lasso(self, points: Sequence[QPointF]) -> CoverageSnapshot:
        """Rasterize a closed freeform polygon in scene coordinates."""
        if len(points) < 3:
            raise ValueError("lasso selections require at least three points")
        polygon = QPolygonF(points)
        bounds = polygon.boundingRect()

        def draw(painter: QPainter, offset: QPointF) -> None:
            """Close and paint the translated polygon path."""
            path = QPainterPath()
            path.addPolygon(polygon.translated(offset))
            path.closeSubpath()
            painter.drawPath(path)

        return self._rasterize(bounds, draw)

    @staticmethod
    def _rasterize(
        scene_bounds: QRectF,
        draw: Callable[[QPainter, QPointF], None],
    ) -> CoverageSnapshot:
        """Render one vector primitive into minimal scene-aligned storage."""
        if not scene_bounds.isValid() or scene_bounds.isEmpty():
            raise ValueError("selection geometry must have positive area")
        left = math.floor(scene_bounds.left())
        top = math.floor(scene_bounds.top())
        right = math.ceil(scene_bounds.right())
        bottom = math.ceil(scene_bounds.bottom())
        bounds = RasterBounds(left, top, right - left, bottom - top)
        image = QImage(bounds.width, bounds.height, QImage.Format_Grayscale8)
        image.fill(0)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        draw(painter, QPointF(-left, -top))
        painter.end()
        return CoverageSnapshot(
            bounds=bounds,
            extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
            pixels=qimage_to_numpy_grayscale8(image),
        )
