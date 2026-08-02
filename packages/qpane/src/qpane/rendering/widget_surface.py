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
"""Native backing storage for composited widget frames."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap, QRegion

from .wrapped_geometry import wrapped_rect_segments


class WidgetRenderSurface:
    """Own one GUI-thread pixmap that can be scrolled and painted in place."""

    def __init__(self) -> None:
        """Create an unallocated surface."""
        self._pixmap = QPixmap()
        self._image = QImage()
        self._staging_pixmap = QPixmap()
        self._spare_pixmap = QPixmap()
        self._image_current = False
        self._storage_origin = QPoint()

    @property
    def pixmap(self) -> QPixmap:
        """Return the authoritative native paint device."""
        return self._pixmap

    @property
    def is_allocated(self) -> bool:
        """Return whether native storage has been allocated."""
        return not self._pixmap.isNull()

    @property
    def storage_origin(self) -> QPoint:
        """Return the physical storage position representing logical buffer zero."""
        return QPoint(self._storage_origin)

    def allocate(self, physical_size: QSize, device_pixel_ratio: float) -> None:
        """Allocate transparent native storage with the requested DPR."""
        self._image = QImage(
            physical_size,
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        self._image.setDevicePixelRatio(device_pixel_ratio)
        self._image.fill(Qt.GlobalColor.transparent)
        self.publish_image()
        self._spare_pixmap = QPixmap(physical_size)
        self._spare_pixmap.setDevicePixelRatio(device_pixel_ratio)
        self._spare_pixmap.fill(Qt.GlobalColor.transparent)

    def matches(self, physical_size: QSize, device_pixel_ratio: float) -> bool:
        """Return whether the surface matches the requested physical geometry."""
        return (
            self.is_allocated
            and self._pixmap.size() == physical_size
            and self._pixmap.devicePixelRatio() == device_pixel_ratio
        )

    def clear(self) -> None:
        """Clear every pixel to transparent."""
        if self.is_allocated:
            self.image.fill(Qt.GlobalColor.transparent)

    def begin_full_repaint(self) -> None:
        """Reset wrapped addressing before every logical pixel is replaced."""
        if not self.is_allocated:
            raise RuntimeError("render surface must be allocated before repainting")
        self._storage_origin = QPoint()
        self._image_current = False

    def scroll(self, dx: int, dy: int) -> QRegion:
        """Advance the wrapped origin and return newly exposed logical pixels."""
        if not self.is_allocated:
            raise RuntimeError("render surface must be allocated before scrolling")
        surface_rect = self._pixmap.rect()
        if abs(dx) >= surface_rect.width() or abs(dy) >= surface_rect.height():
            return QRegion(surface_rect)
        covered = surface_rect.translated(dx, dy).intersected(surface_rect)
        exposed = QRegion(surface_rect).subtracted(QRegion(covered))
        self._storage_origin = QPoint(
            (self._storage_origin.x() - dx) % surface_rect.width(),
            (self._storage_origin.y() - dy) % surface_rect.height(),
        )
        self._image_current = False
        return exposed

    def scroll_linear(self, dx: int, dy: int) -> QRegion:
        """Scroll materialized storage while preserving one global clip phase."""
        if not self.is_allocated:
            raise RuntimeError("render surface must be allocated before scrolling")
        self.normalize_storage()
        surface_rect = self._pixmap.rect()
        if abs(dx) >= surface_rect.width() or abs(dy) >= surface_rect.height():
            return QRegion(surface_rect)
        exposed = QRegion()
        self._pixmap.scroll(dx, dy, surface_rect, exposed)
        self._image_current = False
        return exposed

    def snapshot(self) -> QImage:
        """Return a linear image snapshot in logical buffer order."""
        if self._storage_origin.isNull():
            return self._pixmap.toImage()
        snapshot = QImage(
            self._pixmap.size(),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        snapshot.setDevicePixelRatio(self._pixmap.devicePixelRatio())
        snapshot.fill(
            Qt.GlobalColor.transparent
            if self._pixmap.hasAlphaChannel()
            else Qt.GlobalColor.black
        )
        painter = QPainter(snapshot)
        try:
            self._draw_logical_rect(
                painter,
                self._pixmap.rect(),
                QPoint(),
            )
        finally:
            painter.end()
        return snapshot

    @property
    def image(self) -> QImage:
        """Return a writable image synchronized with the native presentation."""
        if not self.is_allocated:
            raise RuntimeError("render surface must be allocated before image access")
        self.normalize_storage()
        if not self._image_current:
            self._image = self._pixmap.toImage()
            self._image_current = True
        return self._image

    def publish_image(self) -> None:
        """Replace the native presentation with the current full image."""
        if self._image.isNull():
            self._pixmap = QPixmap()
            self._image_current = False
            return
        self._pixmap = QPixmap.fromImage(self._image)
        self._storage_origin = QPoint()
        self._image_current = True

    def publish_patch(self, physical_rect: QRect, patch: QImage) -> None:
        """Replace one physical native rectangle from a matching DPR image patch."""
        if not self.is_allocated:
            raise RuntimeError("render surface must be allocated before patching")
        if physical_rect.size() != patch.size():
            raise ValueError("patch dimensions must match the physical target")
        self.normalize_storage()
        device_pixel_ratio = self._pixmap.devicePixelRatio()
        painter = QPainter(self._pixmap)
        try:
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            painter.drawImage(
                QPointF(
                    physical_rect.x() / device_pixel_ratio,
                    physical_rect.y() / device_pixel_ratio,
                ),
                patch,
            )
        finally:
            painter.end()
        self._image_current = False

    def paint_native(
        self,
        draw: Callable[[QPainter], None],
        *,
        logical_region: QRegion | None = None,
    ) -> None:
        """Apply one logical mutation across wrapped native storage segments."""
        if not self.is_allocated:
            raise RuntimeError("render surface must be allocated before painting")
        surface_region = QRegion(self._pixmap.rect())
        if (
            logical_region is None
            or logical_region.intersected(surface_region) == surface_region
        ):
            self._storage_origin = QPoint()
        if not self._storage_origin.isNull():
            self._paint_wrapped_patches(
                draw,
                surface_region if logical_region is None else logical_region,
            )
            self._image_current = False
            return
        painter = QPainter(self._pixmap)
        try:
            draw(painter)
        finally:
            painter.end()
        self._image_current = False

    def _paint_wrapped_patches(
        self,
        draw: Callable[[QPainter], None],
        logical_region: QRegion,
    ) -> None:
        """Map logical repair drawing directly onto wrapped native storage."""
        device_pixel_ratio = self._pixmap.devicePixelRatio()
        painter = QPainter(self._pixmap)
        try:
            for logical_rect in logical_region:
                clipped = logical_rect.intersected(self._pixmap.rect())
                if clipped.isEmpty():
                    continue
                for segment in wrapped_rect_segments(
                    clipped,
                    surface_size=self._pixmap.size(),
                    storage_origin=self._storage_origin,
                ):
                    logical_to_storage = (
                        segment.storage_rect.topLeft() - segment.logical_rect.topLeft()
                    )
                    painter.save()
                    try:
                        painter.translate(
                            logical_to_storage.x() / device_pixel_ratio,
                            logical_to_storage.y() / device_pixel_ratio,
                        )
                        painter.setClipRect(
                            self._physical_to_logical(segment.logical_rect),
                            Qt.ClipOperation.IntersectClip,
                        )
                        draw(painter)
                    finally:
                        painter.restore()
        finally:
            painter.end()

    def normalize_storage(self) -> None:
        """Materialize wrapped pixels linearly when a non-pan operation requires it."""
        if not self.is_allocated or self._storage_origin.isNull():
            return
        self._image = self.snapshot()
        self.publish_image()

    def prepare_staging(self) -> None:
        """Claim one preallocated detached surface for atomic replacement."""
        if not self.is_allocated:
            raise RuntimeError("render surface must be allocated before staging")
        if (
            self._spare_pixmap.size() == self._pixmap.size()
            and self._spare_pixmap.devicePixelRatio() == self._pixmap.devicePixelRatio()
        ):
            self._staging_pixmap = self._spare_pixmap
            self._spare_pixmap = QPixmap()
        else:
            self._staging_pixmap = QPixmap(self._pixmap.size())
            self._staging_pixmap.setDevicePixelRatio(self._pixmap.devicePixelRatio())
            self._staging_pixmap.fill(Qt.GlobalColor.transparent)

    def paint_staging(self, draw: Callable[[QPainter], None]) -> None:
        """Apply one bounded mutation to the unpublished staging image."""
        if self._staging_pixmap.isNull():
            raise RuntimeError("staging must be prepared before painting")
        painter = QPainter(self._staging_pixmap)
        if not painter.isActive():
            raise RuntimeError("staging painter could not be activated")
        try:
            draw(painter)
        finally:
            painter.end()

    def transfer_staging_patch(self, image: QImage, physical_rect: QRect) -> None:
        """Copy one exact physical image rectangle into native staging storage."""
        if self._staging_pixmap.isNull():
            raise RuntimeError("staging must be prepared before transfer")
        if (
            image.size() != self._staging_pixmap.size()
            or image.devicePixelRatio() != self._staging_pixmap.devicePixelRatio()
        ):
            raise ValueError("transfer image geometry must match native staging")
        if not image.rect().contains(physical_rect):
            raise ValueError("transfer patch must be inside the source image")
        painter = QPainter(self._staging_pixmap)
        if not painter.isActive():
            raise RuntimeError("staging painter could not be activated")
        device_pixel_ratio = self._staging_pixmap.devicePixelRatio()
        try:
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            painter.scale(1.0 / device_pixel_ratio, 1.0 / device_pixel_ratio)
            painter.drawImage(
                QRectF(physical_rect),
                image,
                QRectF(physical_rect),
            )
        finally:
            painter.end()

    def publish_staging(self) -> None:
        """Atomically replace native presentation with the completed staging image."""
        if self._staging_pixmap.isNull():
            raise RuntimeError("staging must be prepared before publication")
        previous = self._pixmap
        self._pixmap = self._staging_pixmap
        self._staging_pixmap = QPixmap()
        self._spare_pixmap = previous
        self._image = QImage()
        self._storage_origin = QPoint()
        self._image_current = False

    def discard_staging(self) -> None:
        """Release an incomplete staged frame without touching presentation."""
        if not self._staging_pixmap.isNull():
            self._spare_pixmap = self._staging_pixmap
        self._staging_pixmap = QPixmap()

    def restore(self, image: QImage) -> None:
        """Replace native storage with a saved image snapshot."""
        self.discard_staging()
        if image.isNull():
            self._pixmap = QPixmap()
            self._image = QImage()
            self._storage_origin = QPoint()
            self._image_current = False
            return
        self._image = QImage(image)
        self.publish_image()

    def _draw_logical_rect(
        self,
        painter: QPainter,
        logical_rect: QRect,
        target_origin: QPoint,
    ) -> None:
        """Draw one logical physical rectangle from wrapped native storage."""
        source_image = self._pixmap.toImage()
        if not source_image.hasAlphaChannel():
            source_image = source_image.convertToFormat(QImage.Format.Format_RGBX8888)
        for segment in wrapped_rect_segments(
            logical_rect,
            surface_size=self._pixmap.size(),
            storage_origin=self._storage_origin,
        ):
            target = segment.logical_rect.translated(
                target_origin - logical_rect.topLeft()
            )
            painter.drawImage(
                self._physical_to_logical(target),
                source_image,
                QRectF(segment.storage_rect),
            )

    def _physical_to_logical(self, rect: QRect) -> QRectF:
        """Convert one physical surface rectangle to painter-logical coordinates."""
        device_pixel_ratio = self._pixmap.devicePixelRatio()
        return QRectF(
            rect.x() / device_pixel_ratio,
            rect.y() / device_pixel_ratio,
            rect.width() / device_pixel_ratio,
            rect.height() / device_pixel_ratio,
        )
