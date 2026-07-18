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

"""Shared helpers for converting between QImage and NumPy arrays."""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage

__all__ = [
    "images_differ",
    "numpy_to_qimage_argb32",
    "numpy_to_qimage_grayscale8",
    "qimage_to_numpy_grayscale8",
    "qimage_to_numpy_view_grayscale8",
]


def images_differ(existing: QImage | None, updated: QImage) -> bool:
    """Return True when ``updated`` differs from ``existing`` or replaces a null value."""
    if updated.isNull():
        return False
    if existing is None or existing.isNull():
        return True
    if existing.cacheKey() == updated.cacheKey():
        return False
    return not (
        existing.size() == updated.size()
        and existing.format() == updated.format()
        and existing == updated
    )


def _prepare_grayscale_bits(image: QImage) -> tuple[QImage, object]:
    """Normalize ``image`` to grayscale and expose its read-only buffer."""
    if image.isNull():
        raise ValueError("QImage must not be null")
    if image.format() != QImage.Format_Grayscale8:
        image = image.convertToFormat(QImage.Format_Grayscale8)
    ptr = image.constBits()
    setsize = getattr(ptr, "setsize", None)
    if callable(setsize):
        setsize(image.sizeInBytes())
    return image, ptr


def qimage_to_numpy_grayscale8(image: QImage) -> np.ndarray:
    """Return a contiguous uint8 array representing ``image`` in Format_Grayscale8.

    Args:
        image: Source image that will be converted to ``Format_Grayscale8``.

    Returns:
        Copy of the grayscale pixels shaped ``(height, width)``.

    Raises:
        ValueError: If ``image`` is null.
    """
    image, ptr = _prepare_grayscale_bits(image)
    return np.ndarray(
        (image.height(), image.width()),
        dtype=np.uint8,
        buffer=ptr,
        strides=(image.bytesPerLine(), 1),
    ).copy()


def qimage_to_numpy_view_grayscale8(image: QImage) -> tuple[np.ndarray, QImage]:
    """Return a zero-copy view of the grayscale pixels and the backing image.

    Args:
        image: Source image that will be converted to ``Format_Grayscale8`` if needed.

    Returns:
        View onto the grayscale pixels and the possibly converted QImage that owns
        the memory.

    Raises:
        ValueError: If ``image`` is null.
    """
    image, ptr = _prepare_grayscale_bits(image)
    array = np.ndarray(
        (image.height(), image.width()),
        dtype=np.uint8,
        buffer=ptr,
        strides=(image.bytesPerLine(), 1),
    )
    return array, image


def numpy_to_qimage_grayscale8(array: np.ndarray) -> QImage:
    """Create a grayscale QImage copy from a contiguous ``(H, W)`` array.

    Args:
        array: ``(height, width)`` array with ``dtype=uint8`` (copied if needed).

    Returns:
        Copy of ``array`` stored as ``Format_Grayscale8``.

    Raises:
        ValueError: If ``array`` is not two-dimensional or does not use ``uint8``.
    """
    if array.ndim != 2:
        raise ValueError("NumPy array must have shape (height, width)")
    if array.dtype != np.uint8:
        raise ValueError("NumPy array must have dtype uint8 for grayscale images")
    if not array.flags.c_contiguous:
        array = np.ascontiguousarray(array)
    height, width = array.shape
    bytes_per_line = array.strides[0]
    return QImage(
        array.data, width, height, bytes_per_line, QImage.Format_Grayscale8
    ).copy()


def numpy_to_qimage_argb32(array: np.ndarray) -> QImage:
    """Create a premultiplied ARGB QImage from a contiguous ``(H, W, 4)`` array.

    Args:
        array: ``(height, width, 4)`` array of uint8 values (copied if needed).

    Returns:
        Copy of ``array`` stored as ``Format_ARGB32_Premultiplied``.

    Raises:
        ValueError: If ``array`` is not three-dimensional, lacks four channels, or does
            not use ``uint8``.
    """
    if array.ndim != 3 or array.shape[2] != 4:
        raise ValueError("NumPy array must have shape (height, width, 4)")
    if array.dtype != np.uint8:
        raise ValueError("NumPy array must have dtype uint8 for ARGB images")
    array = np.ascontiguousarray(array)
    height, width, channels = array.shape
    bytes_per_line = channels * width
    return QImage(
        array.data, width, height, bytes_per_line, QImage.Format_ARGB32_Premultiplied
    ).copy()
