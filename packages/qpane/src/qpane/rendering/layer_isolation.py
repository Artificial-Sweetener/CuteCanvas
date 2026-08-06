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
"""Composite one mutable layer surface independently from its backdrop."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QImage, QPainter


class LayerIsolationCompositor:
    """Own the reusable transparent surface used for one-layer replacement."""

    def __init__(self) -> None:
        """Create an isolation owner without allocating a frame-sized image."""
        self._buffer: QImage | None = None

    def composite(
        self,
        painter: QPainter,
        *,
        opacity: float,
        paint_layer: Callable[[QPainter], None],
    ) -> None:
        """Render a complete layer independently, then blend it over the backdrop."""
        buffer = self._prepare_buffer(painter)
        layer_painter = QPainter(buffer)
        try:
            layer_painter.setWorldTransform(painter.worldTransform())
            if painter.hasClipping():
                layer_painter.setClipRegion(painter.clipRegion())
            paint_layer(layer_painter)
        finally:
            layer_painter.end()
        painter.save()
        try:
            painter.resetTransform()
            painter.setOpacity(opacity)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.drawImage(QPointF(), buffer)
        finally:
            painter.restore()

    def _prepare_buffer(self, painter: QPainter) -> QImage:
        """Return a cleared reusable surface matching the current paint device."""
        device = painter.device()
        size = QSize(device.width(), device.height())
        dpr = float(device.devicePixelRatioF())
        buffer = self._buffer
        if (
            buffer is None
            or buffer.size() != size
            or abs(buffer.devicePixelRatioF() - dpr) > 1e-6
        ):
            buffer = QImage(size, QImage.Format_ARGB32_Premultiplied)
            buffer.setDevicePixelRatio(dpr)
            self._buffer = buffer
            buffer.fill(Qt.transparent)
        elif painter.hasClipping():
            clear = QPainter(buffer)
            try:
                clear.setWorldTransform(painter.worldTransform())
                clear.setClipRegion(painter.clipRegion())
                clear.setCompositionMode(QPainter.CompositionMode_Source)
                clear.fillRect(painter.clipBoundingRect(), Qt.transparent)
            finally:
                clear.end()
        else:
            buffer.fill(Qt.transparent)
        return buffer


__all__ = ["LayerIsolationCompositor"]
