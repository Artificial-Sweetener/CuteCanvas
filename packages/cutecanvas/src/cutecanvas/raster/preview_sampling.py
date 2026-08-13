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

"""Bound transient raster previews independently from exact native products."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage

from qpane.sdk.raster import numpy_to_qimage_argb32


def sample_argb32_preview(
    pixels: npt.NDArray[np.uint8],
    target_size: QSize,
) -> QImage:
    """Return a nearest display approximation for a latency-sensitive frame."""
    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 4:
        raise TypeError("preview pixels must be uint8 with shape (height, width, 4)")
    return numpy_to_qimage_argb32(_nearest_preview(pixels, target_size))


def sample_coverage_preview(
    pixels: npt.NDArray[np.uint8],
    target_size: QSize,
) -> npt.NDArray[np.uint8]:
    """Return a conservative scalar approximation for a latency-sensitive frame."""
    if pixels.dtype != np.uint8 or pixels.ndim != 2:
        raise TypeError("preview coverage must be a two-dimensional uint8 array")
    return _maximum_preview(pixels, target_size)


def _maximum_preview(
    pixels: npt.NDArray[np.uint8],
    target_size: QSize,
) -> npt.NDArray[np.uint8]:
    """Preserve covered samples while reducing each display-pixel footprint."""
    if target_size.isEmpty() or pixels.shape[0] <= 0 or pixels.shape[1] <= 0:
        raise ValueError("preview source and target dimensions must be positive")
    result = pixels
    target_width = target_size.width()
    target_height = target_size.height()
    if target_width < result.shape[1]:
        columns = (
            np.arange(target_width, dtype=np.int64) * result.shape[1] // target_width
        )
        result = np.maximum.reduceat(result, columns, axis=1)[:, :target_width]
    elif target_width > result.shape[1]:
        columns = np.minimum(
            np.arange(target_width, dtype=np.int64) * result.shape[1] // target_width,
            result.shape[1] - 1,
        )
        result = result[:, columns]
    if target_height < result.shape[0]:
        rows = (
            np.arange(target_height, dtype=np.int64) * result.shape[0] // target_height
        )
        result = np.maximum.reduceat(result, rows, axis=0)[:target_height]
    elif target_height > result.shape[0]:
        rows = np.minimum(
            np.arange(target_height, dtype=np.int64) * result.shape[0] // target_height,
            result.shape[0] - 1,
        )
        result = result[rows]
    return np.ascontiguousarray(result)


def _nearest_preview(
    pixels: npt.NDArray[np.uint8],
    target_size: QSize,
) -> npt.NDArray[np.uint8]:
    """Sample bounded integer indices without invoking settled resampling."""
    if target_size.isEmpty() or pixels.shape[0] <= 0 or pixels.shape[1] <= 0:
        raise ValueError("preview source and target dimensions must be positive")
    target_width = target_size.width()
    target_height = target_size.height()
    if pixels.shape[:2] == (target_height, target_width):
        return np.ascontiguousarray(pixels)
    columns = np.minimum(
        np.arange(target_width, dtype=np.int64) * pixels.shape[1] // target_width,
        pixels.shape[1] - 1,
    )
    rows = np.minimum(
        np.arange(target_height, dtype=np.int64) * pixels.shape[0] // target_height,
        pixels.shape[0] - 1,
    )
    return np.ascontiguousarray(pixels[rows[:, None], columns])


__all__ = ["sample_argb32_preview", "sample_coverage_preview"]
