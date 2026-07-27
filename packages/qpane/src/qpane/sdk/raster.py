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
"""Supported raster conversion and affine resampling primitives."""

from ..hybrid.presentation import present_hybrid_pixels, present_hybrid_sample
from ..raster.affine_resampling import AffineImageResampler
from ..raster.image_conversion import (
    numpy_to_qimage_argb32,
    numpy_to_qimage_argb32_at_size,
    numpy_to_qimage_grayscale8,
    numpy_to_qimage_grayscale8_at_size,
    qimage_to_numpy_argb32,
    qimage_to_numpy_const_view_argb32,
    qimage_to_numpy_const_view_bgra32,
    qimage_to_numpy_grayscale8,
    qimage_to_numpy_view_argb32,
    qimage_to_numpy_view_grayscale8,
)

__all__ = (
    "AffineImageResampler",
    "numpy_to_qimage_argb32",
    "numpy_to_qimage_argb32_at_size",
    "numpy_to_qimage_grayscale8",
    "numpy_to_qimage_grayscale8_at_size",
    "present_hybrid_pixels",
    "present_hybrid_sample",
    "qimage_to_numpy_argb32",
    "qimage_to_numpy_const_view_argb32",
    "qimage_to_numpy_const_view_bgra32",
    "qimage_to_numpy_grayscale8",
    "qimage_to_numpy_view_argb32",
    "qimage_to_numpy_view_grayscale8",
)
