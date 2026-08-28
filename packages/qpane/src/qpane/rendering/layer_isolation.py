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
from PySide6.QtGui import QImage, QPainter, QPainterPath

from .storage_allocation import (
    RenderStorageAllocationError,
    RenderStorageAllocator,
    checked_painter,
)


class LayerIsolationCompositor:
    """Own the reusable transparent surface used for one-layer replacement."""

    def __init__(self, allocator: RenderStorageAllocator | None = None) -> None:
        """Create an isolation owner without allocating a frame-sized image."""
        self._allocator = allocator or RenderStorageAllocator()
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
        logical_clip = painter.clipPath() if painter.hasClipping() else None
        composite_clip = (
            painter.worldTransform().map(logical_clip)
            if logical_clip is not None
            else None
        )
        depth = self._depth
        self._depth += 1
        try:
            buffer = self._prepare_buffer(
                painter,
                depth=depth,
                logical_clip=logical_clip,
            )
            layer_painter = checked_painter(buffer, "layer isolation")
            try:
                layer_painter.setWorldTransform(painter.worldTransform())
                if logical_clip is not None:
                    layer_painter.setClipPath(logical_clip)
                paint_layer(layer_painter)
            finally:
                layer_painter.end()
            painter.save()
            try:
                painter.resetTransform()
                if composite_clip is not None:
                    painter.setClipPath(
                        composite_clip,
                        Qt.ClipOperation.ReplaceClip,
                    )
                painter.setOpacity(opacity)
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
                painter.drawImage(QPointF(), buffer)
            finally:
                painter.restore()
        finally:
            self._depth -= 1

    def _prepare_buffer(
        self,
        painter: QPainter,
        *,
        depth: int,
        logical_clip: QPainterPath | None,
    ) -> QImage:
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
            buffer = self._allocator.create_image(size, dpr)
            if buffer.isNull():
                raise RenderStorageAllocationError(
                    "Native storage unavailable for isolated layer"
                )
            self._set_buffer_at_depth(depth, buffer)
            buffer.fill(Qt.transparent)
        elif logical_clip is not None:
            clear = checked_painter(buffer, "layer isolation clear")
            try:
                clear.setWorldTransform(painter.worldTransform())
                clear.setClipPath(logical_clip)
                clear.setCompositionMode(QPainter.CompositionMode_Source)
                clear.fillRect(logical_clip.boundingRect(), Qt.transparent)
            finally:
                clear.end()
        else:
            buffer.fill(Qt.transparent)
        return buffer

    def release_idle_storage(self) -> int:
        """Release reusable isolation buffers when no composite is active."""
        if self._depth > 0:
            return 0
        buffers = tuple(
            buffer
            for buffer in (self._buffer, *self._nested_buffers)
            if buffer is not None and not buffer.isNull()
        )
        released = sum(
            RenderStorageAllocator.estimated_bytes(buffer.size()) for buffer in buffers
        )
        self._buffer = None
        self._nested_buffers.clear()
        return released

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
