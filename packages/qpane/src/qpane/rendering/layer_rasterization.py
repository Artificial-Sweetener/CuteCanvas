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
"""Explicit render-product rasterization for non-destructive layer sources."""

from __future__ import annotations

import logging
import uuid

from PySide6.QtCore import QObject, QRectF, QRunnable, QSize, Signal
from PySide6.QtGui import QImage, QPainter

from ..concurrency import BaseWorker

logger = logging.getLogger(__name__)


class LayerRasterizer:
    """Render one detached source product at an explicit raster specification."""

    @staticmethod
    def rasterize(source: QImage, pixel_size: QSize) -> QImage:
        """Return premultiplied pixels using QPane's smooth raster semantics."""
        if source.isNull():
            raise ValueError("rasterization source must not be null")
        if pixel_size.isEmpty():
            raise ValueError("rasterization pixel size must be positive")
        target = QImage(pixel_size, QImage.Format_ARGB32_Premultiplied)
        if target.isNull():
            raise MemoryError("rasterization target could not be allocated")
        target.fill(0)
        painter = QPainter(target)
        if not painter.isActive():
            raise RuntimeError("rasterization painter could not be activated")
        try:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawImage(
                QRectF(0.0, 0.0, pixel_size.width(), pixel_size.height()), source
            )
        finally:
            painter.end()
        return target


class LayerRasterizationWorker(QObject, QRunnable, BaseWorker):
    """Rasterize a detached render product away from the GUI thread."""

    finished = Signal(object)
    error = Signal(object)

    def __init__(
        self,
        request_id: uuid.UUID,
        source: QImage,
        pixel_size: QSize,
    ) -> None:
        """Capture immutable request inputs."""
        QObject.__init__(self)
        QRunnable.__init__(self)
        BaseWorker.__init__(self, logger=logger)
        self.request_id = request_id
        self.source = QImage(source)
        self.pixel_size = QSize(pixel_size)
        self.result: QImage | None = None
        self.error_message: str | None = None

    def run(self) -> None:
        """Create one output and publish a terminal worker result."""
        try:
            if not self.is_cancelled:
                self.result = LayerRasterizer.rasterize(self.source, self.pixel_size)
        except BaseException as exc:  # pragma: no cover - defensive worker boundary
            self.error_message = str(exc)
            logger.exception("Layer rasterization failed")
        self.emit_finished(
            self.result is not None
            and self.error_message is None
            and not self.is_cancelled,
            payload=self,
        )
