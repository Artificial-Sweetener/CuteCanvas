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

from dataclasses import dataclass

import numpy as np
from cutecanvas.ferrastra import NativeCoverageProjector
from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QImage
from qpane.sdk.raster import (
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_grayscale8,
)
from qpane.sdk.scene import LayerTransform, RasterBounds

from .surface import CoverageSurface


@dataclass(frozen=True, slots=True)
class CoverageSurfaceSampler:
    """Sample one thread-safe sparse coverage surface on an explicit grid."""

    surface: CoverageSurface

    def sample(self, source_rect: QRectF, pixel_size: QSize) -> QImage:
        """Return one filtered grayscale sample without dense-gap allocation."""
        bounds = RasterBounds.from_qrect(source_rect.toAlignedRect())
        image = coverage_image(
            self.surface.capture_region(bounds),
        )
        return project_coverage_image(
            image,
            bounds,
            source_rect,
            pixel_size,
        )


def project_coverage_image(
    image: QImage,
    image_bounds: RasterBounds,
    source_rect: QRectF,
    pixel_size: QSize,
) -> QImage:
    """Project integer-bounded coverage onto one exact sampling rectangle."""
    exact_rect = QRectF(
        float(image_bounds.x),
        float(image_bounds.y),
        float(image_bounds.width),
        float(image_bounds.height),
    )
    if source_rect == exact_rect and pixel_size == image.size():
        return image
    destination_bounds = RasterBounds(
        0,
        0,
        pixel_size.width(),
        pixel_size.height(),
    )
    pixels = NativeCoverageProjector().project(
        qimage_to_numpy_grayscale8(image),
        source_bounds=image_bounds,
        transform=LayerTransform(
            m11=pixel_size.width() / source_rect.width(),
            m22=pixel_size.height() / source_rect.height(),
            dx=-source_rect.x() * pixel_size.width() / source_rect.width(),
            dy=-source_rect.y() * pixel_size.height() / source_rect.height(),
        ),
        destination_bounds=destination_bounds,
    )
    return numpy_to_qimage_grayscale8(pixels)


def coverage_image(pixels: np.ndarray) -> QImage:
    """Detach contiguous coverage pixels into a grayscale Qt image."""
    return numpy_to_qimage_grayscale8(pixels)
