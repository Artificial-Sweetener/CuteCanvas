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

"""Qt presentation proof for reusable isolated layer surfaces."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from qpane.rendering.layer_isolation import LayerIsolationCompositor


def test_nested_layer_isolation_keeps_outer_surface_intact(qapp) -> None:
    """Nested sampled work must not clear its enclosing piecewise layer."""
    del qapp
    output = QImage(16, 16, QImage.Format.Format_ARGB32_Premultiplied)
    output.fill(Qt.GlobalColor.transparent)
    isolation = LayerIsolationCompositor()
    painter = QPainter(output)
    try:

        def paint_outer(outer: QPainter) -> None:
            """Paint the outer contribution around one nested isolation."""
            outer.fillRect(QRectF(0.0, 0.0, 16.0, 16.0), QColor("red"))
            isolation.composite(
                outer,
                opacity=1.0,
                paint_layer=lambda inner: inner.fillRect(
                    QRectF(4.0, 4.0, 8.0, 8.0),
                    QColor("blue"),
                ),
            )

        isolation.composite(
            painter,
            opacity=1.0,
            paint_layer=paint_outer,
        )
    finally:
        painter.end()

    assert output.pixelColor(2, 2) == QColor("red")
    assert output.pixelColor(8, 8) == QColor("blue")
