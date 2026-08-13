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

"""Build bounded mask approximations for immediate presentation."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from qpane.sdk.raster import (
    numpy_to_qimage_argb32,
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_argb32,
)

from ..raster.preview_sampling import sample_coverage_preview


def preview_mask_overlay(image: QImage, target_size: QSize) -> QImage:
    """Return a bounded colorized approximation while exact work settles."""
    pixels = qimage_to_numpy_argb32(image)
    channels = tuple(
        sample_coverage_preview(pixels[:, :, channel], target_size)
        for channel in range(4)
    )
    return numpy_to_qimage_argb32(np.stack(channels, axis=2))


def preview_mask_coverage(pixels: np.ndarray, target_size: QSize) -> QImage:
    """Return a bounded scalar approximation for immediate mask presentation."""
    return numpy_to_qimage_grayscale8(sample_coverage_preview(pixels, target_size))


__all__ = ["preview_mask_coverage", "preview_mask_overlay"]
