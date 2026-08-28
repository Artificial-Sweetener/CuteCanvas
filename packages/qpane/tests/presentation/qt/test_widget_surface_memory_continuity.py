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
"""Prove retained-frame continuity when native storage cannot be allocated."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPixmap, QRegion

from qpane.rendering.storage_allocation import (
    RenderStorageAllocationError,
    RenderStorageAllocator,
)
from qpane.rendering.widget_surface import WidgetRenderSurface


class _RejectingAllocator(RenderStorageAllocator):
    """Reject one selected storage operation after a valid frame exists."""

    def __init__(self, rejected_operation: str) -> None:
        """Retain the operation that should simulate native exhaustion."""
        super().__init__()
        self._rejected_operation = rejected_operation

    def create_image(
        self,
        physical_size: QSize,
        device_pixel_ratio: float,
    ) -> QImage:
        """Return a null image when image allocation is rejected."""
        if self._rejected_operation == "image":
            return QImage()
        return super().create_image(physical_size, device_pixel_ratio)

    def create_pixmap(
        self,
        physical_size: QSize,
        device_pixel_ratio: float,
    ) -> QPixmap:
        """Return a null pixmap when staging allocation is rejected."""
        if self._rejected_operation == "pixmap":
            return QPixmap()
        return super().create_pixmap(physical_size, device_pixel_ratio)

    def create_pixmap_from_image(self, image: QImage) -> QPixmap:
        """Return a null pixmap when publication allocation is rejected."""
        if self._rejected_operation == "publication":
            return QPixmap()
        return super().create_pixmap_from_image(image)

    def copy_pixmap(self, pixmap: QPixmap) -> QPixmap:
        """Return a null pixmap when completed-frame retention is rejected."""
        if self._rejected_operation == "retention":
            return QPixmap()
        return super().copy_pixmap(pixmap)

    def copy_pixmap_region(self, pixmap: QPixmap, rect: QRect) -> QPixmap:
        """Return null when region-scoped frame retention is rejected."""
        if self._rejected_operation == "retention":
            return QPixmap()
        return super().copy_pixmap_region(pixmap, rect)


def _red_surface(allocator: RenderStorageAllocator) -> WidgetRenderSurface:
    """Return one allocated surface containing a recognizable valid frame."""
    surface = WidgetRenderSurface()
    surface.allocate(QSize(12, 8), 1.0)
    surface.pixmap.fill(Qt.GlobalColor.red)
    surface.set_allocator(allocator)
    return surface


def _assert_red_frame_remains(surface: WidgetRenderSurface) -> None:
    """Assert that the previously published frame remains present and intact."""
    assert surface.is_allocated
    assert surface.pixmap.size() == QSize(12, 8)
    assert surface.snapshot().pixelColor(5, 4) == QColor(Qt.GlobalColor.red)


def test_failed_resize_allocation_preserves_last_valid_frame(qapp) -> None:
    """A rejected replacement image must not clear the published frame."""
    surface = _red_surface(_RejectingAllocator("image"))

    with pytest.raises(RenderStorageAllocationError):
        surface.allocate(QSize(24, 16), 1.0)

    _assert_red_frame_remains(surface)


def test_failed_resize_publication_preserves_last_valid_frame(qapp) -> None:
    """A rejected native publication must leave the old frame authoritative."""
    surface = _red_surface(_RejectingAllocator("publication"))

    with pytest.raises(RenderStorageAllocationError):
        surface.allocate(QSize(24, 16), 1.0)

    _assert_red_frame_remains(surface)


def test_failed_staging_allocation_preserves_last_valid_frame(qapp) -> None:
    """A rejected speculative frame must never replace active presentation."""
    surface = _red_surface(_RejectingAllocator("pixmap"))
    surface.release_reclaimable_storage()

    with pytest.raises(RenderStorageAllocationError):
        surface.prepare_staging()

    _assert_red_frame_remains(surface)


def test_explicit_blank_remains_available_under_the_semantic_operation(qapp) -> None:
    """Explicit clearing must remain distinct from allocation failure."""
    surface = _red_surface(RenderStorageAllocator())

    surface.clear_presentation()

    assert not surface.is_allocated


def test_failed_frame_update_rolls_back_every_partial_native_mutation(qapp) -> None:
    """A draw failure after clearing pixels must restore the completed frame."""
    surface = _red_surface(RenderStorageAllocator())
    surface.begin_frame_update()
    surface.pixmap.fill(Qt.GlobalColor.blue)

    assert surface.rollback_frame_update()

    _assert_red_frame_remains(surface)


def test_failed_frame_retention_leaves_the_current_frame_authoritative(qapp) -> None:
    """Failure to retain a rollback frame must occur before any frame mutation."""
    surface = _red_surface(_RejectingAllocator("retention"))

    with pytest.raises(RenderStorageAllocationError):
        surface.begin_frame_update()

    _assert_red_frame_remains(surface)


def test_committed_frame_update_releases_the_previous_frame(qapp) -> None:
    """Successful publication should make the completed replacement authoritative."""
    surface = _red_surface(RenderStorageAllocator())
    surface.begin_frame_update()
    surface.pixmap.fill(Qt.GlobalColor.blue)
    surface.commit_frame_update()

    assert not surface.rollback_frame_update()
    assert surface.snapshot().pixelColor(5, 4) == QColor(Qt.GlobalColor.blue)


def test_linear_scroll_rollback_restores_lost_and_repaired_pixels(qapp) -> None:
    """A failed linear repair must reverse its scroll without a full-frame copy."""
    surface = _red_surface(RenderStorageAllocator())
    original = surface.snapshot()
    surface.begin_frame_update(QRegion())
    exposed = surface.scroll_linear_transactional(3, 0)
    repair_region = exposed.united(QRegion(QRect(3, 0, 2, 8)))
    surface.protect_frame_region(repair_region)
    surface.paint_native(
        lambda painter: painter.fillRect(QRect(0, 0, 5, 8), Qt.GlobalColor.blue),
        logical_region=repair_region,
    )

    assert surface.rollback_frame_update()

    assert surface.snapshot() == original


def test_sustained_contention_preserves_pixels_and_recovers(qapp) -> None:
    """Repeated rejection across critical storage boundaries must never blank."""
    surface = _red_surface(RenderStorageAllocator())

    for _attempt in range(100):
        for operation in ("image", "publication", "pixmap", "retention"):
            surface.set_allocator(_RejectingAllocator(operation))
            with pytest.raises(RenderStorageAllocationError):
                if operation in {"image", "publication"}:
                    surface.allocate(QSize(24, 16), 1.0)
                elif operation == "pixmap":
                    surface.release_reclaimable_storage()
                    surface.prepare_staging()
                else:
                    surface.begin_frame_update()
            _assert_red_frame_remains(surface)

        surface.set_allocator(RenderStorageAllocator())
        surface.begin_frame_update()
        surface.pixmap.fill(Qt.GlobalColor.blue)
        assert surface.rollback_frame_update()
        _assert_red_frame_remains(surface)

    surface.set_allocator(RenderStorageAllocator())
    surface.begin_frame_update()
    surface.pixmap.fill(Qt.GlobalColor.green)
    surface.commit_frame_update()

    assert surface.snapshot().pixelColor(5, 4) == QColor(Qt.GlobalColor.green)
