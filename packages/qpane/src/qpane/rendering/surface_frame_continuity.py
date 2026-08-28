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
"""Retain and restore the last completed native surface frame."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QPainter, QPixmap, QRegion

from .storage_allocation import (
    RenderStorageAllocationError,
    RenderStorageAllocator,
    checked_painter,
)
from .wrapped_geometry import wrapped_rect_segments

StoragePatches = dict[tuple[int, int, int, int], QPixmap]


class SurfaceFrameContinuity:
    """Own the rollback journal for fallible native frame mutations."""

    def __init__(self, allocator: RenderStorageAllocator) -> None:
        """Create an empty journal using the surface allocation boundary."""
        self._allocator = allocator
        self._replacement_pixmap = QPixmap()
        self._replacement_origin = QPoint()
        self._storage_patches: StoragePatches = {}
        self._linear_scroll_rollback: tuple[int, int, StoragePatches] | None = None
        self._update_origin: QPoint | None = None

    @property
    def has_replacement(self) -> bool:
        """Return whether a resized candidate still depends on its predecessor."""
        return not self._replacement_pixmap.isNull()

    def set_allocator(self, allocator: RenderStorageAllocator) -> None:
        """Replace the allocation boundary for subsequent journal entries."""
        self._allocator = allocator

    def retain_replacement(self, pixmap: QPixmap, storage_origin: QPoint) -> None:
        """Retain the completed frame before publishing resized candidate storage."""
        if pixmap.isNull() or self.has_replacement:
            return
        retained = self._allocator.copy_pixmap(pixmap)
        self._require_pixmap(retained, "render frame retention")
        self._replacement_pixmap = retained
        self._replacement_origin = QPoint(storage_origin)

    def begin(
        self,
        pixmap: QPixmap,
        storage_origin: QPoint,
        protected_region: QRegion,
    ) -> None:
        """Begin a region-scoped mutation journal before native pixels change."""
        if pixmap.isNull() or self.has_replacement or self._update_origin is not None:
            return
        self._update_origin = QPoint(storage_origin)
        try:
            self.protect(pixmap, storage_origin, protected_region)
        except Exception:
            self._storage_patches.clear()
            self._update_origin = None
            raise

    def protect(
        self,
        pixmap: QPixmap,
        storage_origin: QPoint,
        logical_region: QRegion,
    ) -> None:
        """Snapshot storage segments before the active transaction mutates them."""
        if self._update_origin is None or self.has_replacement:
            return
        self._storage_patches.update(
            self._capture_logical_region(pixmap, storage_origin, logical_region)
        )

    def scroll_linear(self, pixmap: QPixmap, dx: int, dy: int) -> QRegion:
        """Scroll native storage while retaining only pixels lost by the move."""
        if self._update_origin is None:
            raise RuntimeError("frame update must begin before transactional scrolling")
        surface_rect = pixmap.rect()
        retained_source = surface_rect.translated(-dx, -dy).intersected(surface_rect)
        lost_source = QRegion(surface_rect).subtracted(QRegion(retained_source))
        lost_patches = self._capture_physical_region(pixmap, lost_source)
        exposed = QRegion()
        pixmap.scroll(dx, dy, surface_rect, exposed)
        self._linear_scroll_rollback = (dx, dy, lost_patches)
        return exposed

    def commit(self) -> None:
        """Accept the current native frame and release its predecessor journal."""
        self.clear()

    def rollback(self, pixmap: QPixmap) -> tuple[QPixmap, QPoint] | None:
        """Restore the journaled completed frame and return its storage identity."""
        if self.has_replacement:
            restored = self._replacement_pixmap
            restored_origin = QPoint(self._replacement_origin)
        else:
            if self._update_origin is None:
                return None
            self._restore_patches(pixmap, self._storage_patches)
            if self._linear_scroll_rollback is not None:
                dx, dy, lost_patches = self._linear_scroll_rollback
                pixmap.scroll(-dx, -dy, pixmap.rect())
                self._restore_patches(pixmap, lost_patches)
            restored = pixmap
            restored_origin = QPoint(self._update_origin)
        self.clear()
        return restored, restored_origin

    def clear(self) -> None:
        """Release all completed-frame retention and in-progress journal state."""
        self._replacement_pixmap = QPixmap()
        self._replacement_origin = QPoint()
        self._storage_patches.clear()
        self._linear_scroll_rollback = None
        self._update_origin = None

    def _capture_logical_region(
        self,
        pixmap: QPixmap,
        storage_origin: QPoint,
        logical_region: QRegion,
    ) -> StoragePatches:
        """Copy physical storage segments representing one logical region."""
        patches: StoragePatches = {}
        for logical_rect in logical_region:
            clipped = logical_rect.intersected(pixmap.rect())
            if clipped.isEmpty():
                continue
            for segment in wrapped_rect_segments(
                clipped,
                surface_size=pixmap.size(),
                storage_origin=storage_origin,
            ):
                rect = segment.storage_rect
                key = (rect.x(), rect.y(), rect.width(), rect.height())
                if key in self._storage_patches or key in patches:
                    continue
                patch = self._allocator.copy_pixmap_region(pixmap, rect)
                self._require_pixmap(patch, "render frame region retention")
                patches[key] = patch
        return patches

    def _capture_physical_region(
        self,
        pixmap: QPixmap,
        region: QRegion,
    ) -> StoragePatches:
        """Copy disjoint physical storage rectangles without logical remapping."""
        patches: StoragePatches = {}
        for rect in region:
            key = (rect.x(), rect.y(), rect.width(), rect.height())
            patch = self._allocator.copy_pixmap_region(pixmap, rect)
            self._require_pixmap(patch, "linear scroll rollback retention")
            patches[key] = patch
        return patches

    @staticmethod
    def _restore_patches(pixmap: QPixmap, patches: StoragePatches) -> None:
        """Restore captured storage patches without changing logical addressing."""
        if not patches:
            return
        painter = checked_painter(pixmap, "render frame rollback")
        device_pixel_ratio = pixmap.devicePixelRatio()
        try:
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            for key, patch in patches.items():
                x, y, _width, _height = key
                painter.drawPixmap(
                    QPointF(x / device_pixel_ratio, y / device_pixel_ratio),
                    patch,
                )
        finally:
            painter.end()

    @staticmethod
    def _require_pixmap(pixmap: QPixmap, operation: str) -> None:
        """Reject a null retained candidate before any front-frame mutation."""
        if pixmap.isNull():
            raise RenderStorageAllocationError(
                f"Native storage unavailable during {operation}"
            )


__all__ = ["SurfaceFrameContinuity"]
