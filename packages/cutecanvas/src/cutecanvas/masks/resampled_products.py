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

"""Adapt mask cache inputs to exact native resampling products."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage

from qpane.sdk.execution import CancellationToken
from qpane.sdk.raster import numpy_to_qimage_grayscale8

from ..ferrastra import NativeCoverageProjector, NativeRasterProjector


def resample_mask_overlay(
    image: QImage,
    target_size: QSize,
    cancellation: CancellationToken | None = None,
) -> QImage:
    """Return one exact raster overlay at the requested cache dimensions."""
    return NativeRasterProjector().scale(
        image,
        target_size,
        cancellation=cancellation,
    )


def resample_mask_coverage(
    pixels: np.ndarray,
    target_size: QSize,
    cancellation: CancellationToken | None = None,
) -> QImage:
    """Return one exact Coverage8 presentation image at the requested dimensions."""
    return numpy_to_qimage_grayscale8(
        NativeCoverageProjector().scale(
            pixels,
            target_size,
            cancellation=cancellation,
        )
    )


__all__ = ["resample_mask_coverage", "resample_mask_overlay"]
