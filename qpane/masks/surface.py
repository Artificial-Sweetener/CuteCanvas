#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Thread-safe authoritative pixel surfaces for mask assets."""

from __future__ import annotations

import threading
from collections.abc import Callable

import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage

from ..catalog.image_utils import qimage_to_numpy_view_grayscale8


def normalize_mask_array(array: np.ndarray | None) -> np.ndarray:
    """Return a detached contiguous uint8 mask array."""
    if array is None:
        return np.zeros((0, 0), dtype=np.uint8)
    mask = np.asarray(array)
    if mask.ndim != 2:
        raise ValueError("Mask arrays must be two-dimensional (H, W).")
    if mask.size == 0:
        return np.zeros(mask.shape, dtype=np.uint8)
    if mask.dtype == np.bool_:
        mask = mask.astype(np.uint8) * 255
    elif np.issubdtype(mask.dtype, np.floating):
        safe = np.nan_to_num(mask, nan=0.0, posinf=255.0, neginf=0.0)
        maximum = float(safe.max()) if safe.size else 0.0
        safe = (
            np.clip(safe, 0.0, 1.0) * 255.0
            if maximum <= 1.0
            else np.clip(safe, 0.0, 255.0)
        )
        mask = safe.astype(np.uint8)
    elif mask.dtype != np.uint8:
        mask = np.clip(mask, 0, 255).astype(np.uint8)
    result = np.empty(mask.shape, dtype=np.uint8, order="C")
    np.copyto(result, mask)
    return result


class MaskSurface:
    """Own synchronized grayscale pixels and detached snapshots."""

    def __init__(self, buffer: np.ndarray | None = None) -> None:
        """Initialize normalized pixels and their zero-copy Qt view."""
        self._lock = threading.RLock()
        self._buffer = normalize_mask_array(buffer)
        self._image = self._wrap_buffer(self._buffer)
        self._snapshot_cache: QImage | None = None
        self._snapshot_generation = -1
        self.generation = 0

    @classmethod
    def from_qimage(cls, image: QImage) -> MaskSurface:
        """Build a surface from a detached image snapshot."""
        if image.isNull():
            return cls()
        grayscale = (
            image
            if image.format() == QImage.Format_Grayscale8
            else image.convertToFormat(QImage.Format_Grayscale8)
        )
        view, _ = qimage_to_numpy_view_grayscale8(grayscale)
        return cls(view)

    @classmethod
    def blank(cls, size: QSize) -> MaskSurface:
        """Create a zero-filled surface of ``size``."""
        if not size.isValid():
            return cls()
        return cls(np.zeros((size.height(), size.width()), dtype=np.uint8))

    def is_null(self) -> bool:
        """Return whether the surface has no pixels."""
        return self._buffer.size == 0

    def snapshot_qimage(self) -> QImage:
        """Return a detached, thread-safe image snapshot."""
        with self._lock:
            if self.is_null():
                return QImage()
            if (
                self._snapshot_cache is None
                or self._snapshot_generation != self.generation
            ):
                self._snapshot_cache = self._image.copy()
                self._snapshot_generation = self.generation
            return self._snapshot_cache.copy()

    def snapshot_array(self) -> np.ndarray:
        """Return a detached NumPy snapshot."""
        with self._lock:
            return np.array(self._buffer, copy=True)

    def replace_with_array(self, array: np.ndarray) -> None:
        """Replace authoritative pixels and advance content revision."""
        with self._lock:
            self._buffer = normalize_mask_array(array)
            self._image = self._wrap_buffer(self._buffer)
            self._mark_changed()

    def replace_with_qimage(self, image: QImage) -> None:
        """Replace authoritative pixels from a QImage."""
        if image.isNull():
            self.replace_with_array(np.zeros((0, 0), dtype=np.uint8))
            return
        grayscale = (
            image
            if image.format() == QImage.Format_Grayscale8
            else image.convertToFormat(QImage.Format_Grayscale8)
        )
        view, _ = qimage_to_numpy_view_grayscale8(grayscale)
        self.replace_with_array(view)

    def mutate(self, mutator: Callable[[np.ndarray, QImage], None]) -> None:
        """Run one controlled in-place mutation and advance revision."""
        with self._lock:
            mutator(self._buffer, self._image)
            self._mark_changed()

    def fill(self, value: int) -> None:
        """Fill the surface through the controlled mutation boundary."""
        normalized = QColor(value).red() if isinstance(value, Qt.GlobalColor) else value

        def apply(buffer: np.ndarray, _image: QImage) -> None:
            """Fill the writable canonical buffer with the normalized value."""
            buffer.fill(normalized)

        self.mutate(apply)

    def _mark_changed(self) -> None:
        """Invalidate snapshots and advance authoritative content revision."""
        self._snapshot_cache = None
        self._snapshot_generation = -1
        self.generation += 1

    @staticmethod
    def _wrap_buffer(buffer: np.ndarray) -> QImage:
        """Create a private QImage view over owned pixels."""
        if buffer.size == 0:
            return QImage()
        height, width = buffer.shape
        image = QImage(
            buffer.data, width, height, int(buffer.strides[0]), QImage.Format_Grayscale8
        )
        if image.isNull():
            raise RuntimeError("Failed to wrap mask buffer into QImage.")
        return image
