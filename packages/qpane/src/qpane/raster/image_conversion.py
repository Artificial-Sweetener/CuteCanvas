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
"""Conversions between detached Qt images and NumPy raster storage."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage


def images_differ(existing: QImage | None, updated: QImage) -> bool:
    """Return whether ``updated`` differs from an existing non-null image."""
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


def qimage_to_numpy_grayscale8(image: QImage) -> np.ndarray:
    """Return a detached contiguous grayscale array for ``image``."""
    normalized, pointer = _prepare_grayscale_bits(image)
    return np.ndarray(
        (normalized.height(), normalized.width()),
        dtype=np.uint8,
        buffer=pointer,
        strides=(normalized.bytesPerLine(), 1),
    ).copy()


def qimage_to_numpy_view_grayscale8(image: QImage) -> tuple[np.ndarray, QImage]:
    """Return a read-only grayscale view and its normalized backing image."""
    normalized, pointer = _prepare_grayscale_bits(image)
    array = np.ndarray(
        (normalized.height(), normalized.width()),
        dtype=np.uint8,
        buffer=pointer,
        strides=(normalized.bytesPerLine(), 1),
    )
    array.flags.writeable = False
    return array, normalized


def qimage_to_numpy_writable_view_grayscale8(
    image: QImage,
) -> tuple[np.ndarray, QImage]:
    """Return a writable grayscale view and its normalized backing image."""
    return _qimage_to_numpy_writable_view_grayscale8(image)


def qimage_to_numpy_argb32(image: QImage) -> np.ndarray:
    """Return detached BGRA memory-order pixels for a premultiplied ARGB image."""
    array, _backing = qimage_to_numpy_const_view_argb32(image)
    return np.array(array, copy=True, order="C")


def qimage_to_numpy_view_argb32(image: QImage) -> tuple[np.ndarray, QImage]:
    """Return a writable BGRA view and its premultiplied-ARGB backing image."""
    if image.isNull():
        raise ValueError("QImage must not be null")
    normalized = (
        image
        if image.format() == QImage.Format_ARGB32_Premultiplied
        else image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    )
    pointer = normalized.bits()
    set_size = getattr(pointer, "setsize", None)
    if callable(set_size):
        set_size(normalized.sizeInBytes())
    array = np.ndarray(
        (normalized.height(), normalized.width(), 4),
        dtype=np.uint8,
        buffer=pointer,
        strides=(normalized.bytesPerLine(), 4, 1),
    )
    return array, normalized


def qimage_to_numpy_const_view_argb32(image: QImage) -> tuple[np.ndarray, QImage]:
    """Return a read-only BGRA view and its premultiplied-ARGB backing image."""
    if image.isNull():
        raise ValueError("QImage must not be null")
    normalized = (
        image
        if image.format() == QImage.Format_ARGB32_Premultiplied
        else image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    )
    pointer = normalized.constBits()
    set_size = getattr(pointer, "setsize", None)
    if callable(set_size):
        set_size(normalized.sizeInBytes())
    array = np.ndarray(
        (normalized.height(), normalized.width(), 4),
        dtype=np.uint8,
        buffer=pointer,
        strides=(normalized.bytesPerLine(), 4, 1),
    )
    array.flags.writeable = False
    return array, normalized


def qimage_to_numpy_const_view_bgra32(image: QImage) -> tuple[np.ndarray, QImage]:
    """Return a read-only BGRA storage view without converting compatible images."""
    if image.isNull():
        raise ValueError("QImage must not be null")
    compatible_formats = {
        QImage.Format_ARGB32,
        QImage.Format_ARGB32_Premultiplied,
        QImage.Format_RGB32,
    }
    normalized = (
        image
        if image.format() in compatible_formats
        else image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    )
    pointer = normalized.constBits()
    set_size = getattr(pointer, "setsize", None)
    if callable(set_size):
        set_size(normalized.sizeInBytes())
    array = np.ndarray(
        (normalized.height(), normalized.width(), 4),
        dtype=np.uint8,
        buffer=pointer,
        strides=(normalized.bytesPerLine(), 4, 1),
    )
    array.flags.writeable = False
    return array, normalized


def numpy_to_qimage_grayscale8(array: np.ndarray) -> QImage:
    """Return a detached grayscale QImage copied from a uint8 2-D array."""
    if array.ndim != 2:
        raise ValueError("NumPy array must have shape (height, width)")
    if array.dtype != np.uint8:
        raise ValueError("NumPy array must have dtype uint8 for grayscale images")
    contiguous = np.ascontiguousarray(array)
    height, width = contiguous.shape
    image = QImage(width, height, QImage.Format_Grayscale8)
    target, backing = _qimage_to_numpy_writable_view_grayscale8(image)
    np.copyto(target, contiguous)
    return backing


def numpy_to_qimage_argb32(array: np.ndarray) -> QImage:
    """Return a detached premultiplied-ARGB QImage from a uint8 4-channel array."""
    if array.ndim != 3 or array.shape[2] != 4:
        raise ValueError("NumPy array must have shape (height, width, 4)")
    if array.dtype != np.uint8:
        raise ValueError("NumPy array must have dtype uint8 for ARGB images")
    contiguous = np.ascontiguousarray(array)
    height, width, _channels = contiguous.shape
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    target, backing = qimage_to_numpy_view_argb32(image)
    np.copyto(target, contiguous)
    return backing


def numpy_to_qimage_argb32_at_size(array: np.ndarray, size: QSize) -> QImage:
    """Sample canonical BGRA pixels directly into a detached target image."""
    if array.ndim != 3 or array.shape[2] != 4 or array.dtype != np.uint8:
        raise ValueError("NumPy array must be uint8 with shape (height, width, 4)")
    if size.isEmpty():
        raise ValueError("target size must be positive")
    contiguous = np.ascontiguousarray(array)
    height, width, channels = contiguous.shape
    borrowed = QImage(
        contiguous.data,
        width,
        height,
        channels * width,
        QImage.Format_ARGB32_Premultiplied,
    )
    if borrowed.size() == size:
        return borrowed.copy()
    return borrowed.scaled(
        size,
        Qt.IgnoreAspectRatio,
        Qt.SmoothTransformation,
    )


def numpy_to_qimage_grayscale8_at_size(array: np.ndarray, size: QSize) -> QImage:
    """Sample canonical grayscale pixels directly into a detached target image."""
    if array.ndim != 2 or array.dtype != np.uint8:
        raise ValueError("NumPy array must be uint8 with shape (height, width)")
    if size.isEmpty():
        raise ValueError("target size must be positive")
    contiguous = np.ascontiguousarray(array)
    height, width = contiguous.shape
    borrowed = QImage(
        contiguous.data,
        width,
        height,
        int(contiguous.strides[0]),
        QImage.Format_Grayscale8,
    )
    if borrowed.size() == size:
        return borrowed.copy()
    return borrowed.scaled(
        size,
        Qt.IgnoreAspectRatio,
        Qt.SmoothTransformation,
    )


def _prepare_grayscale_bits(image: QImage) -> tuple[QImage, object]:
    """Normalize ``image`` to grayscale and expose its read-only buffer."""
    if image.isNull():
        raise ValueError("QImage must not be null")
    normalized = (
        image
        if image.format() == QImage.Format_Grayscale8
        else image.convertToFormat(QImage.Format_Grayscale8)
    )
    pointer = normalized.constBits()
    set_size = getattr(pointer, "setsize", None)
    if callable(set_size):
        set_size(normalized.sizeInBytes())
    return normalized, pointer


def _qimage_to_numpy_writable_view_grayscale8(
    image: QImage,
) -> tuple[np.ndarray, QImage]:
    """Return a writable grayscale view for populating an owned image."""
    if image.isNull():
        raise ValueError("QImage must not be null")
    normalized = (
        image
        if image.format() == QImage.Format_Grayscale8
        else image.convertToFormat(QImage.Format_Grayscale8)
    )
    pointer = normalized.bits()
    set_size = getattr(pointer, "setsize", None)
    if callable(set_size):
        set_size(normalized.sizeInBytes())
    array = np.ndarray(
        (normalized.height(), normalized.width()),
        dtype=np.uint8,
        buffer=pointer,
        strides=(normalized.bytesPerLine(), 1),
    )
    return array, normalized
