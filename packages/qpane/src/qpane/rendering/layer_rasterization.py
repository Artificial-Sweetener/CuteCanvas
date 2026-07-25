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

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QImage, QPainter

from ..execution import CancellationToken
from .render_tile_types import RegionSampleSource


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


def rasterize_layer(
    source: QImage,
    pixel_size: QSize,
    cancellation: CancellationToken,
) -> QImage:
    """Rasterize one detached render product cooperatively."""

    if cancellation.is_cancelled:
        raise RuntimeError(cancellation.reason or "layer rasterization cancelled")
    return LayerRasterizer.rasterize(QImage(source), QSize(pixel_size))


def rasterize_region(
    source: RegionSampleSource,
    source_rect: QRectF,
    pixel_size: QSize,
    cancellation: CancellationToken,
) -> QImage:
    """Sample one immutable bounded source region cooperatively."""

    if source_rect.isEmpty():
        raise ValueError("rasterization source rectangle must be positive")
    if pixel_size.isEmpty():
        raise ValueError("rasterization pixel size must be positive")
    if cancellation.is_cancelled:
        raise RuntimeError(cancellation.reason or "region rasterization cancelled")
    result = source.sample(QRectF(source_rect), QSize(pixel_size))
    if result.isNull():
        raise RuntimeError("region rasterization produced no image")
    if result.size() != pixel_size:
        raise RuntimeError("region rasterization produced unexpected dimensions")
    return QImage(result)
