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
"""Pixel proof for viewport-bounded retained-frame presentation."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QTransform

from qpane.raster.image_conversion import qimage_to_numpy_argb32
from qpane.rendering.frame_buffer_presenter import FrameBufferPresenter
from qpane.rendering.widget_surface import WidgetRenderSurface


def test_transformed_crop_matches_full_overscan_presentation(qapp) -> None:
    """Visible cropping must preserve the established transformed pixels exactly."""
    presentation = QPixmap(360, 240)
    presentation.fill(Qt.GlobalColor.transparent)
    painter = QPainter(presentation)
    try:
        for y in range(0, 240, 12):
            for x in range(0, 360, 12):
                painter.fillRect(
                    x,
                    y,
                    12,
                    12,
                    QColor(
                        (x * 3 + y) % 256,
                        (x + y * 5) % 256,
                        (x * 7 + y * 2) % 256,
                    ),
                )
    finally:
        painter.end()
    viewport_rect = QRect(0, 0, 240, 140)
    transform = QTransform()
    transform.translate(132.5, 78.25)
    transform.scale(1.17, 1.17)
    transform.translate(-120.0, -70.0)

    expected = _reference_frame(
        presentation,
        viewport_rect=viewport_rect,
        overscan_physical_px=40,
        transform=transform,
    )
    actual = QImage(QSize(240, 140), QImage.Format.Format_ARGB32_Premultiplied)
    actual.fill(Qt.GlobalColor.transparent)
    painter = QPainter(actual)
    try:
        FrameBufferPresenter.draw(
            painter,
            presentation,
            viewport_physical_size=QSize(240, 140),
            viewport_rect=viewport_rect,
            overscan_physical_px=40,
            subpixel_pan_offset=QPointF(),
            presentation_transform=transform,
        )
    finally:
        painter.end()

    assert (qimage_to_numpy_argb32(actual) == qimage_to_numpy_argb32(expected)).all()


def test_settled_native_blit_matches_source_rect_presentation(qapp) -> None:
    """Settled presentation must preserve the previous physical crop exactly."""
    device_pixel_ratio = 1.75
    physical_viewport = QSize(384, 216)
    logical_viewport = QSize(
        round(physical_viewport.width() / device_pixel_ratio),
        round(physical_viewport.height() / device_pixel_ratio),
    )
    presentation = QPixmap(512, 344)
    presentation.setDevicePixelRatio(device_pixel_ratio)
    presentation.fill(Qt.GlobalColor.transparent)
    painter = QPainter(presentation)
    try:
        for y in range(0, presentation.height(), 8):
            for x in range(0, presentation.width(), 8):
                painter.fillRect(
                    x,
                    y,
                    8,
                    8,
                    QColor(
                        (x * 3 + y) % 256,
                        (x + y * 5) % 256,
                        (x * 7 + y * 2) % 256,
                    ),
                )
    finally:
        painter.end()
    offset = QPointF(3.5, -1.75)
    expected = QImage(
        physical_viewport,
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    expected.setDevicePixelRatio(device_pixel_ratio)
    expected.fill(Qt.GlobalColor.transparent)
    painter = QPainter(expected)
    try:
        painter.drawPixmap(
            QRectF(
                0.0,
                0.0,
                physical_viewport.width() / device_pixel_ratio,
                physical_viewport.height() / device_pixel_ratio,
            ),
            presentation,
            QRectF(
                64.0 - offset.x(),
                64.0 - offset.y(),
                physical_viewport.width(),
                physical_viewport.height(),
            ),
        )
    finally:
        painter.end()

    actual = QImage(
        physical_viewport,
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    actual.setDevicePixelRatio(device_pixel_ratio)
    actual.fill(Qt.GlobalColor.transparent)
    painter = QPainter(actual)
    try:
        FrameBufferPresenter.draw(
            painter,
            presentation,
            viewport_physical_size=physical_viewport,
            viewport_rect=QRect(QPointF().toPoint(), logical_viewport),
            overscan_physical_px=64,
            subpixel_pan_offset=offset,
            presentation_transform=QTransform(),
        )
    finally:
        painter.end()

    assert (qimage_to_numpy_argb32(actual) == qimage_to_numpy_argb32(expected)).all()


def test_settled_wrapped_surface_matches_linear_snapshot(qapp) -> None:
    """Settled ring-buffer crops must preserve alignment and transparent pixels."""
    device_pixel_ratio = 1.75
    physical_viewport = QSize(240, 140)
    logical_viewport = QSize(
        round(physical_viewport.width() / device_pixel_ratio),
        round(physical_viewport.height() / device_pixel_ratio),
    )
    surface = WidgetRenderSurface()
    surface.allocate(QSize(360, 240), device_pixel_ratio)
    painter = QPainter(surface.pixmap)
    try:
        for y in range(0, 240, 12):
            for x in range(0, 360, 12):
                if (x // 12 + y // 12) % 5 == 0:
                    continue
                painter.fillRect(
                    QRectF(
                        x / device_pixel_ratio,
                        y / device_pixel_ratio,
                        12 / device_pixel_ratio,
                        12 / device_pixel_ratio,
                    ),
                    QColor(
                        (x * 3 + y) % 256,
                        (x + y * 5) % 256,
                        (x * 7 + y * 2) % 256,
                        173,
                    ),
                )
    finally:
        painter.end()
    surface.scroll(37, -29)
    linear = QPixmap.fromImage(surface.snapshot())
    expected = QImage(
        physical_viewport,
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    actual = QImage(
        physical_viewport,
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    expected.setDevicePixelRatio(device_pixel_ratio)
    actual.setDevicePixelRatio(device_pixel_ratio)
    expected.fill(Qt.GlobalColor.transparent)
    actual.fill(Qt.GlobalColor.transparent)
    for target, presentation, origin in (
        (expected, linear, None),
        (actual, surface.pixmap, surface.storage_origin),
    ):
        painter = QPainter(target)
        try:
            FrameBufferPresenter.draw(
                painter,
                presentation,
                viewport_physical_size=physical_viewport,
                viewport_rect=QRect(QPointF().toPoint(), logical_viewport),
                overscan_physical_px=40,
                subpixel_pan_offset=QPointF(),
                presentation_transform=QTransform(),
                storage_origin_physical=origin,
            )
        finally:
            painter.end()

    assert (qimage_to_numpy_argb32(actual) == qimage_to_numpy_argb32(expected)).all()


def test_transformed_wrapped_surface_matches_linear_snapshot(qapp) -> None:
    """Zoom previews should transform wrapped storage without normalizing its pixels."""
    surface = WidgetRenderSurface()
    surface.allocate(QSize(360, 240), 1.0)
    painter = QPainter(surface.pixmap)
    try:
        for y in range(0, 240, 12):
            for x in range(0, 360, 12):
                painter.fillRect(
                    x,
                    y,
                    12,
                    12,
                    QColor(
                        (x * 3 + y) % 256,
                        (x + y * 5) % 256,
                        (x * 7 + y * 2) % 256,
                    ),
                )
    finally:
        painter.end()
    surface.scroll(17, -11)
    linear = QPixmap.fromImage(surface.snapshot())
    viewport_rect = QRect(0, 0, 240, 140)
    transform = QTransform()
    transform.translate(132.5, 78.25)
    transform.scale(1.17, 1.17)
    transform.translate(-120.0, -70.0)

    expected = QImage(viewport_rect.size(), QImage.Format.Format_ARGB32_Premultiplied)
    actual = QImage(viewport_rect.size(), QImage.Format.Format_ARGB32_Premultiplied)
    expected.fill(Qt.GlobalColor.transparent)
    actual.fill(Qt.GlobalColor.transparent)
    for target, presentation, origin in (
        (expected, linear, None),
        (actual, surface.pixmap, surface.storage_origin),
    ):
        painter = QPainter(target)
        try:
            FrameBufferPresenter.draw(
                painter,
                presentation,
                viewport_physical_size=viewport_rect.size(),
                viewport_rect=viewport_rect,
                overscan_physical_px=40,
                subpixel_pan_offset=QPointF(),
                presentation_transform=transform,
                storage_origin_physical=origin,
            )
        finally:
            painter.end()

    delta = np.abs(
        qimage_to_numpy_argb32(actual).astype(np.int16)
        - qimage_to_numpy_argb32(expected).astype(np.int16)
    )
    assert int(delta.max(initial=0)) <= 1


def test_transformed_coverage_rejects_zoom_out_beyond_retained_guard(qapp) -> None:
    """A valid center crop cannot stand in for newly exposed viewport pixels."""
    presentation = QPixmap(440, 280)
    presentation.setDevicePixelRatio(1.0)
    viewport_rect = QRect(0, 0, 320, 180)
    covered_transform = QTransform()
    covered_transform.translate(160.0, 90.0)
    covered_transform.scale(1.1, 1.1)
    covered_transform.translate(-160.0, -90.0)
    uncovered_transform = QTransform()
    uncovered_transform.translate(160.0, 90.0)
    uncovered_transform.scale(0.7, 0.7)
    uncovered_transform.translate(-160.0, -90.0)

    assert FrameBufferPresenter.transformed_viewport_is_covered(
        presentation,
        viewport_rect=viewport_rect,
        overscan_physical_px=60,
        presentation_transform=covered_transform,
    )
    assert not FrameBufferPresenter.transformed_viewport_is_covered(
        presentation,
        viewport_rect=viewport_rect,
        overscan_physical_px=60,
        presentation_transform=uncovered_transform,
    )


def _reference_frame(
    presentation: QPixmap,
    *,
    viewport_rect: QRect,
    overscan_physical_px: int,
    transform: QTransform,
) -> QImage:
    """Return the original whole-pixmap transformed presentation."""
    image = QImage(viewport_rect.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        painter.setClipRect(viewport_rect)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        widget_translation = QTransform.fromTranslate(
            -float(overscan_physical_px) / presentation.devicePixelRatio(),
            -float(overscan_physical_px) / presentation.devicePixelRatio(),
        )
        combined = transform * widget_translation
        painter.setTransform(combined, True)
        painter.drawPixmap(QPointF(), presentation)
    finally:
        painter.end()
    return image
