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
"""Viewport-only presentation of overscanned composited frame buffers."""

from __future__ import annotations

from math import isclose

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize
from PySide6.QtGui import QPainter, QPixmap, QTransform

from .wrapped_geometry import wrapped_rect_segments


class FrameBufferPresenter:
    """Draw only the visible crop of one retained native frame buffer."""

    @staticmethod
    def draw(
        painter: QPainter,
        presentation: QPixmap,
        *,
        viewport_physical_size: QSize,
        viewport_rect: QRect,
        overscan_physical_px: int,
        subpixel_pan_offset: QPointF,
        presentation_transform: QTransform,
        storage_origin_physical: QPoint | None = None,
    ) -> None:
        """Present a settled crop or transformed preview into the widget."""
        if presentation.isNull() or viewport_physical_size.isEmpty():
            return
        device_pixel_ratio = max(0.01, presentation.devicePixelRatio())
        if presentation_transform.isIdentity():
            FrameBufferPresenter._draw_settled(
                painter,
                presentation,
                viewport_physical_size=viewport_physical_size,
                overscan_physical_px=overscan_physical_px,
                subpixel_pan_offset=subpixel_pan_offset,
                device_pixel_ratio=device_pixel_ratio,
                storage_origin_physical=storage_origin_physical or QPoint(),
            )
            return
        FrameBufferPresenter._draw_transformed(
            painter,
            presentation,
            viewport_rect=viewport_rect,
            overscan_physical_px=overscan_physical_px,
            presentation_transform=presentation_transform,
            device_pixel_ratio=device_pixel_ratio,
            storage_origin_physical=storage_origin_physical or QPoint(),
        )

    @staticmethod
    def _draw_settled(
        painter: QPainter,
        presentation: QPixmap,
        *,
        viewport_physical_size: QSize,
        overscan_physical_px: int,
        subpixel_pan_offset: QPointF,
        device_pixel_ratio: float,
        storage_origin_physical: QPoint,
    ) -> None:
        """Draw the unscaled physical viewport crop as one native-DPR blit."""
        requires_fractional_filter = not (
            isclose(
                subpixel_pan_offset.x(),
                round(subpixel_pan_offset.x()),
                rel_tol=0.0,
                abs_tol=1e-9,
            )
            and isclose(
                subpixel_pan_offset.y(),
                round(subpixel_pan_offset.y()),
                rel_tol=0.0,
                abs_tol=1e-9,
            )
        )
        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform,
            requires_fractional_filter,
        )
        if not storage_origin_physical.isNull():
            FrameBufferPresenter._draw_wrapped_settled(
                painter,
                presentation,
                viewport_physical_size=viewport_physical_size,
                overscan_physical_px=overscan_physical_px,
                subpixel_pan_offset=subpixel_pan_offset,
                device_pixel_ratio=device_pixel_ratio,
                storage_origin_physical=storage_origin_physical,
            )
            return
        painter.drawPixmap(
            QPointF(
                (subpixel_pan_offset.x() - float(overscan_physical_px))
                / device_pixel_ratio,
                (subpixel_pan_offset.y() - float(overscan_physical_px))
                / device_pixel_ratio,
            ),
            presentation,
        )

    @staticmethod
    def _draw_wrapped_settled(
        painter: QPainter,
        presentation: QPixmap,
        *,
        viewport_physical_size: QSize,
        overscan_physical_px: int,
        subpixel_pan_offset: QPointF,
        device_pixel_ratio: float,
        storage_origin_physical: QPoint,
    ) -> None:
        """Draw a visible crop split across wrapped physical storage."""
        source_rect = QRect(
            round(overscan_physical_px - subpixel_pan_offset.x()),
            round(overscan_physical_px - subpixel_pan_offset.y()),
            viewport_physical_size.width(),
            viewport_physical_size.height(),
        )
        for segment in wrapped_rect_segments(
            source_rect,
            surface_size=presentation.size(),
            storage_origin=storage_origin_physical,
        ):
            target_rect = segment.logical_rect.translated(-source_rect.topLeft())
            painter.drawPixmap(
                QRectF(
                    target_rect.x() / device_pixel_ratio,
                    target_rect.y() / device_pixel_ratio,
                    target_rect.width() / device_pixel_ratio,
                    target_rect.height() / device_pixel_ratio,
                ),
                presentation,
                QRectF(segment.storage_rect),
            )

    @staticmethod
    def _draw_transformed(
        painter: QPainter,
        presentation: QPixmap,
        *,
        viewport_rect: QRect,
        overscan_physical_px: int,
        presentation_transform: QTransform,
        device_pixel_ratio: float,
        storage_origin_physical: QPoint,
    ) -> None:
        """Resample only source pixels whose transformed result reaches the widget."""
        widget_translation = QTransform.fromTranslate(
            -float(overscan_physical_px) / device_pixel_ratio,
            -float(overscan_physical_px) / device_pixel_ratio,
        )
        combined = presentation_transform * widget_translation
        physical_source = FrameBufferPresenter.transformed_source_rect(
            presentation,
            viewport_rect=viewport_rect,
            overscan_physical_px=overscan_physical_px,
            presentation_transform=presentation_transform,
        )
        if physical_source.isEmpty():
            return
        painter.save()
        try:
            painter.setClipRect(viewport_rect)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            for segment in wrapped_rect_segments(
                physical_source,
                surface_size=presentation.size(),
                storage_origin=storage_origin_physical,
            ):
                logical_segment = QRectF(
                    segment.logical_rect.x() / device_pixel_ratio,
                    segment.logical_rect.y() / device_pixel_ratio,
                    segment.logical_rect.width() / device_pixel_ratio,
                    segment.logical_rect.height() / device_pixel_ratio,
                )
                painter.drawPixmap(
                    combined.mapRect(logical_segment),
                    presentation,
                    QRectF(segment.storage_rect),
                )
        finally:
            painter.restore()

    @staticmethod
    def transformed_source_rect(
        presentation: QPixmap,
        *,
        viewport_rect: QRect,
        overscan_physical_px: int,
        presentation_transform: QTransform,
    ) -> QRect:
        """Return physical retained pixels required by one transformed viewport."""
        if presentation.isNull():
            return QRect()
        device_pixel_ratio = max(0.01, presentation.devicePixelRatio())
        logical_source_bounds = QRectF(
            0.0,
            0.0,
            presentation.width() / device_pixel_ratio,
            presentation.height() / device_pixel_ratio,
        )
        logical_source = FrameBufferPresenter._required_logical_source_rect(
            presentation,
            viewport_rect=viewport_rect,
            overscan_physical_px=overscan_physical_px,
            presentation_transform=presentation_transform,
        ).intersected(logical_source_bounds)
        if logical_source.isEmpty():
            return QRect()
        return (
            QRectF(
                logical_source.x() * device_pixel_ratio,
                logical_source.y() * device_pixel_ratio,
                logical_source.width() * device_pixel_ratio,
                logical_source.height() * device_pixel_ratio,
            )
            .toAlignedRect()
            .intersected(presentation.rect())
        )

    @staticmethod
    def transformed_viewport_is_covered(
        presentation: QPixmap,
        *,
        viewport_rect: QRect,
        overscan_physical_px: int,
        presentation_transform: QTransform,
    ) -> bool:
        """Return whether retained storage covers every transformed target pixel."""
        if presentation.isNull():
            return False
        device_pixel_ratio = max(0.01, presentation.devicePixelRatio())
        logical_source_bounds = QRectF(
            0.0,
            0.0,
            presentation.width() / device_pixel_ratio,
            presentation.height() / device_pixel_ratio,
        )
        required = FrameBufferPresenter._required_logical_source_rect(
            presentation,
            viewport_rect=viewport_rect,
            overscan_physical_px=overscan_physical_px,
            presentation_transform=presentation_transform,
        )
        return not required.isEmpty() and logical_source_bounds.contains(required)

    @staticmethod
    def _required_logical_source_rect(
        presentation: QPixmap,
        *,
        viewport_rect: QRect,
        overscan_physical_px: int,
        presentation_transform: QTransform,
    ) -> QRectF:
        """Map a target viewport plus filtering fringe into retained coordinates."""
        device_pixel_ratio = max(0.01, presentation.devicePixelRatio())
        widget_translation = QTransform.fromTranslate(
            -float(overscan_physical_px) / device_pixel_ratio,
            -float(overscan_physical_px) / device_pixel_ratio,
        )
        combined = presentation_transform * widget_translation
        inverse, invertible = combined.inverted()
        if not invertible:
            return QRectF()
        filter_fringe = 2.0 / device_pixel_ratio
        return inverse.mapRect(QRectF(viewport_rect)).adjusted(
            -filter_fringe,
            -filter_fringe,
            filter_fringe,
            filter_fringe,
        )


__all__ = ["FrameBufferPresenter"]
