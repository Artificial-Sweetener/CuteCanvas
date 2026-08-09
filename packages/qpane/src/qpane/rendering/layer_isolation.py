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
        self._nested_buffers: list[QImage | None] = []
        self._depth = 0

    def composite(
        self,
        painter: QPainter,
        *,
        opacity: float,
        paint_layer: Callable[[QPainter], None],
    ) -> None:
        """Render a complete layer independently, then blend it over the backdrop."""
        depth = self._depth
        self._depth += 1
        try:
            buffer = self._prepare_buffer(painter, depth=depth)
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
        finally:
            self._depth -= 1

    def _prepare_buffer(self, painter: QPainter, *, depth: int) -> QImage:
        """Return a cleared reusable surface matching the current paint device."""
        device = painter.device()
        size = QSize(device.width(), device.height())
        dpr = float(device.devicePixelRatioF())
        buffer = self._buffer_at_depth(depth)
        if (
            buffer is None
            or buffer.size() != size
            or abs(buffer.devicePixelRatioF() - dpr) > 1e-6
        ):
            buffer = QImage(size, QImage.Format_ARGB32_Premultiplied)
            buffer.setDevicePixelRatio(dpr)
            self._set_buffer_at_depth(depth, buffer)
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

    def _buffer_at_depth(self, depth: int) -> QImage | None:
        """Return the reusable surface assigned to one nesting depth."""
        if depth == 0:
            return self._buffer
        index = depth - 1
        return (
            self._nested_buffers[index] if index < len(self._nested_buffers) else None
        )

    def _set_buffer_at_depth(self, depth: int, buffer: QImage) -> None:
        """Retain one reusable surface at its independent nesting depth."""
        if depth == 0:
            self._buffer = buffer
            return
        index = depth - 1
        while len(self._nested_buffers) <= index:
            self._nested_buffers.append(None)
        self._nested_buffers[index] = buffer


__all__ = ["LayerIsolationCompositor"]
