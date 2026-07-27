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
"""Filtered sampling for sparse editable coverage surfaces."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QImage, QPainter
from qpane.sdk.raster import numpy_to_qimage_grayscale8
from qpane.sdk.scene import RasterBounds

from .surface import CoverageSurface


@dataclass(frozen=True, slots=True)
class CoverageSurfaceSampler:
    """Sample one thread-safe sparse coverage surface on an explicit grid."""

    surface: CoverageSurface

    def sample(self, source_rect: QRectF, pixel_size: QSize) -> QImage:
        """Return one filtered grayscale sample without dense-gap allocation."""
        bounds = RasterBounds.from_qrect(source_rect.toAlignedRect())
        stride = _sample_stride(bounds, pixel_size)
        image = coverage_image(
            self.surface.capture_region_strided(bounds, stride),
        )
        return project_coverage_image(
            image,
            bounds,
            source_rect,
            pixel_size,
            sample_stride=stride,
        )


def project_coverage_image(
    image: QImage,
    image_bounds: RasterBounds,
    source_rect: QRectF,
    pixel_size: QSize,
    *,
    sample_stride: int = 1,
) -> QImage:
    """Project integer-bounded coverage onto one exact sampling rectangle."""
    exact_rect = QRectF(
        float(image_bounds.x),
        float(image_bounds.y),
        float(image_bounds.width),
        float(image_bounds.height),
    )
    if sample_stride == 1 and source_rect == exact_rect and pixel_size == image.size():
        return image
    target = QImage(pixel_size, QImage.Format_Grayscale8)
    target.fill(0)
    painter = QPainter(target)
    try:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        source_sample_rect = QRectF(
            (source_rect.x() - image_bounds.x) / sample_stride,
            (source_rect.y() - image_bounds.y) / sample_stride,
            source_rect.width() / sample_stride,
            source_rect.height() / sample_stride,
        )
        painter.drawImage(
            QRectF(0.0, 0.0, float(pixel_size.width()), float(pixel_size.height())),
            image,
            source_sample_rect,
        )
    finally:
        painter.end()
    return target


def coverage_image(pixels: np.ndarray) -> QImage:
    """Detach contiguous coverage pixels into a grayscale Qt image."""
    return numpy_to_qimage_grayscale8(pixels)


def _sample_stride(bounds: RasterBounds, pixel_size: QSize) -> int:
    """Bound sparse reads while retaining two source samples per output pixel."""
    target_width = max(1, pixel_size.width() * 2)
    target_height = max(1, pixel_size.height() * 2)
    return max(
        1,
        math.ceil(bounds.width / target_width),
        math.ceil(bounds.height / target_height),
    )
