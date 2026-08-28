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
"""Allocate fallible Qt render storage without publishing partial state."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QImage, QPaintDevice, QPainter, QPixmap

logger = logging.getLogger(__name__)

MemoryRelief = Callable[[int, str], int]
QtStorage = TypeVar("QtStorage", QImage, QPixmap)


class RenderStorageAllocationError(MemoryError):
    """Report that native render storage remained unavailable after relief."""


class RenderStorageAllocator:
    """Own checked native image allocation and one synchronous relief retry."""

    _BYTES_PER_PIXEL = 4

    def __init__(self, relieve: MemoryRelief | None = None) -> None:
        """Capture an optional derived-resource relief boundary."""
        self._relieve = relieve

    def create_image(
        self,
        physical_size: QSize,
        device_pixel_ratio: float,
    ) -> QImage:
        """Allocate one transparent-capable image, retrying after safe relief."""
        return self._with_relief_retry(
            physical_size,
            "render_image",
            lambda: self._new_image(physical_size, device_pixel_ratio),
        )

    def create_pixmap(
        self,
        physical_size: QSize,
        device_pixel_ratio: float,
    ) -> QPixmap:
        """Allocate one native pixmap, retrying after safe relief."""
        return self._with_relief_retry(
            physical_size,
            "render_pixmap",
            lambda: self._new_pixmap(physical_size, device_pixel_ratio),
        )

    def create_pixmap_from_image(self, image: QImage) -> QPixmap:
        """Create one native presentation candidate without changing its owner."""
        return self._with_relief_retry(
            image.size(),
            "render_publication",
            lambda: QPixmap.fromImage(image),
        )

    def copy_pixmap(self, pixmap: QPixmap) -> QPixmap:
        """Retain one native frame copy, retrying after safe relief."""
        return self._with_relief_retry(
            pixmap.size(),
            "render_frame_retention",
            lambda: QPixmap(pixmap),
        )

    def copy_pixmap_region(self, pixmap: QPixmap, rect: QRect) -> QPixmap:
        """Copy one rollback patch, retrying after safe relief."""
        return self._with_relief_retry(
            rect.size(),
            "render_frame_region_retention",
            lambda: pixmap.copy(rect),
        )

    @classmethod
    def estimated_bytes(cls, physical_size: QSize) -> int:
        """Return the conservative byte requirement for one ARGB surface."""
        return (
            max(0, physical_size.width())
            * max(0, physical_size.height())
            * cls._BYTES_PER_PIXEL
        )

    def _with_relief_retry(
        self,
        size: QSize,
        operation: str,
        allocate: Callable[[], QtStorage],
    ) -> QtStorage:
        """Retry one null allocation after reclaiming only safe resources."""
        candidate = allocate()
        if not candidate.isNull() or size.isEmpty() or self._relieve is None:
            return candidate
        requested_bytes = self.estimated_bytes(size)
        freed_bytes = self._relieve(requested_bytes, operation)
        logger.warning(
            "Native render allocation required memory relief | operation=%s | "
            "requested_bytes=%d | freed_bytes=%d",
            operation,
            requested_bytes,
            freed_bytes,
            extra={
                "memory_pressure": {
                    "operation": operation,
                    "requested_bytes": requested_bytes,
                    "freed_bytes": freed_bytes,
                }
            },
        )
        return allocate()

    @staticmethod
    def _new_image(physical_size: QSize, device_pixel_ratio: float) -> QImage:
        """Construct one ARGB image candidate with the requested DPR."""
        image = QImage(
            physical_size,
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        if not image.isNull():
            image.setDevicePixelRatio(device_pixel_ratio)
        return image

    @staticmethod
    def _new_pixmap(physical_size: QSize, device_pixel_ratio: float) -> QPixmap:
        """Construct one native pixmap candidate with the requested DPR."""
        pixmap = QPixmap(physical_size)
        if not pixmap.isNull():
            pixmap.setDevicePixelRatio(device_pixel_ratio)
        return pixmap


def checked_argb_image(
    physical_size: QSize,
    *,
    device_pixel_ratio: float = 1.0,
) -> QImage:
    """Return valid ARGB storage or raise a recoverable allocation error."""
    image = RenderStorageAllocator().create_image(
        physical_size,
        device_pixel_ratio,
    )
    if image.isNull():
        raise RenderStorageAllocationError(
            "Native ARGB image storage could not be allocated"
        )
    return image


def checked_pixmap(physical_size: QSize) -> QPixmap:
    """Return valid native pixmap storage or raise an allocation error."""
    pixmap = RenderStorageAllocator().create_pixmap(physical_size, 1.0)
    if pixmap.isNull():
        raise RenderStorageAllocationError(
            "Native pixmap storage could not be allocated"
        )
    return pixmap


def require_image(image: QImage, operation: str) -> QImage:
    """Return a valid image product or translate null into memory contention."""
    if image.isNull():
        raise RenderStorageAllocationError(
            f"Native image storage unavailable during {operation}"
        )
    return image


def checked_painter(device: QPaintDevice, operation: str) -> QPainter:
    """Begin an active painter or translate native rejection into contention."""
    painter = QPainter(device)
    if painter.isActive():
        return painter
    painter.end()
    raise RenderStorageAllocationError(
        f"Native painter activation unavailable during {operation}"
    )


def presentation_painter(device: QPaintDevice, operation: str) -> QPainter:
    """Begin a best-effort OS presentation painter without mutating retained state."""
    painter = QPainter(device)
    if not painter.isActive():
        logger.warning(
            "Native presentation target unavailable; retaining completed frame | "
            "operation=%s",
            operation,
            extra={"memory_pressure": {"operation": operation}},
        )
    return painter


__all__ = [
    "MemoryRelief",
    "RenderStorageAllocationError",
    "RenderStorageAllocator",
    "checked_argb_image",
    "checked_painter",
    "checked_pixmap",
    "presentation_painter",
    "require_image",
]
