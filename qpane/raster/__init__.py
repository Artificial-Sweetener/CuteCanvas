#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Neutral raster storage and image conversion infrastructure."""

from .image_conversion import (
    images_differ,
    numpy_to_qimage_argb32,
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_argb32,
    qimage_to_numpy_grayscale8,
    qimage_to_numpy_view_argb32,
    qimage_to_numpy_view_grayscale8,
)

__all__ = [
    "images_differ",
    "numpy_to_qimage_argb32",
    "numpy_to_qimage_grayscale8",
    "qimage_to_numpy_argb32",
    "qimage_to_numpy_grayscale8",
    "qimage_to_numpy_view_argb32",
    "qimage_to_numpy_view_grayscale8",
]
