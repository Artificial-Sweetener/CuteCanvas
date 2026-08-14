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
"""Build the polished starter document shown by the CuteCanvas demo."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen

from cutecanvas import (
    CuteCanvas,
    LayerPolicy,
    RasterExtentPolicy,
    VectorShapeKind,
    VectorStyle,
)


def seed_welcome_document(canvas: CuteCanvas) -> None:
    """Create a layered starter composition through the public editor facade."""
    image = _background_image(QSize(1600, 1000))
    canvas.createCompositionFromImage(
        image,
        title="Welcome",
        label="Background",
        interaction=LayerPolicy(
            selectable=True,
            movable=True,
            pixel_editable=False,
            reorderable=True,
            removable=True,
        ),
    )
    scene = canvas.currentScene()
    if scene is None:
        return
    canvas.createPaintLayer(
        label="Paint",
        extent_policy=RasterExtentPolicy.UNBOUNDED,
    )
    vector_layer_id = canvas.createVectorLayer(label="Welcome shapes")
    if vector_layer_id is None:
        return
    canvas.addVectorShape(
        scene.scene_id,
        vector_layer_id,
        VectorShapeKind.RECTANGLE,
        QRectF(360.0, 260.0, 880.0, 480.0),
        VectorStyle(
            fill=QColor(242, 247, 255, 218),
            stroke=QColor(255, 255, 255, 245),
            stroke_width=8.0,
        ),
    )
    canvas.addVectorShape(
        scene.scene_id,
        vector_layer_id,
        VectorShapeKind.ELLIPSE,
        QRectF(555.0, 345.0, 490.0, 310.0),
        VectorStyle(
            fill=QColor(83, 165, 230, 225),
            stroke=QColor(30, 88, 150, 255),
            stroke_width=12.0,
        ),
    )
    canvas.setSelectedLayer(scene.scene_id, vector_layer_id)
    canvas.setZoomFit()


def _background_image(size: QSize) -> QImage:
    """Return a restrained large raster that makes layer editing immediately visible."""
    image = QImage(size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    gradient = QLinearGradient(0.0, 0.0, float(size.width()), float(size.height()))
    gradient.setColorAt(0.0, QColor(18, 31, 55))
    gradient.setColorAt(0.55, QColor(40, 92, 124))
    gradient.setColorAt(1.0, QColor(208, 137, 99))
    painter.fillRect(image.rect(), gradient)
    painter.setPen(QPen(QColor(255, 255, 255, 22), 1.0))
    for x in range(0, size.width(), 80):
        painter.drawLine(x, 0, x, size.height())
    for y in range(0, size.height(), 80):
        painter.drawLine(0, y, size.width(), y)
    painter.end()
    return image
