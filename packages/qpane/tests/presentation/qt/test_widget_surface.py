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
"""Tests for native widget render-surface ownership."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRegion

from qpane.rendering.widget_surface import WidgetRenderSurface


def test_widget_surface_scrolls_pixels_in_place_and_reports_exposure(qapp) -> None:
    """Native scroll should preserve overlap and identify uncovered strips."""
    surface = WidgetRenderSurface()
    surface.allocate(QSize(12, 8), 1.0)
    painter = QPainter(surface.pixmap)
    try:
        painter.fillRect(QRect(0, 0, 6, 8), QColor("red"))
        painter.fillRect(QRect(6, 0, 6, 8), QColor("blue"))
    finally:
        painter.end()

    exposed = surface.scroll(3, -2)
    snapshot = surface.snapshot()

    assert exposed == QRegion(QRect(0, 0, 3, 6)).united(QRegion(QRect(0, 6, 12, 2)))
    assert snapshot.pixelColor(4, 1) == QColor("red")
    assert snapshot.pixelColor(10, 1) == QColor("blue")


def test_widget_surface_restore_preserves_dpr_and_pixels(qapp) -> None:
    """Restoring a snapshot should recreate the same native surface."""
    surface = WidgetRenderSurface()
    surface.allocate(QSize(20, 10), 2.0)
    surface.pixmap.fill(Qt.GlobalColor.green)
    snapshot = surface.snapshot()

    surface.allocate(QSize(2, 2), 1.0)
    surface.restore(snapshot)

    assert surface.pixmap.size() == QSize(20, 10)
    assert surface.pixmap.devicePixelRatio() == 2.0
    assert surface.snapshot().pixelColor(5, 5) == QColor(Qt.GlobalColor.green)


def test_widget_surface_staging_is_atomic_and_preserves_dpr(qapp) -> None:
    """Unpublished staging must leave the front frame untouched until promotion."""
    surface = WidgetRenderSurface()
    surface.allocate(QSize(20, 10), 2.0)
    surface.pixmap.fill(Qt.GlobalColor.red)
    surface.prepare_staging()
    surface.paint_staging(
        lambda painter: painter.fillRect(
            QRect(0, 0, 20, 10),
            QColor(Qt.GlobalColor.blue),
        )
    )

    assert surface.snapshot().pixelColor(5, 5) == QColor(Qt.GlobalColor.red)

    surface.publish_staging()

    assert surface.pixmap.devicePixelRatio() == 2.0
    assert surface.snapshot().pixelColor(5, 5) == QColor(Qt.GlobalColor.blue)


def test_widget_surface_staging_preserves_transparent_unpainted_pixels(qapp) -> None:
    """Atomic navigation frames must retain alpha outside painted content."""
    surface = WidgetRenderSurface()
    surface.allocate(QSize(20, 10), 1.75)
    surface.prepare_staging()
    surface.paint_staging(
        lambda painter: painter.fillRect(
            QRect(8, 3, 4, 4),
            QColor(Qt.GlobalColor.blue),
        )
    )
    surface.publish_staging()
    snapshot = surface.snapshot()

    assert surface.pixmap.hasAlphaChannel()
    assert snapshot.pixelColor(0, 0) == QColor(0, 0, 0, 0)
    assert snapshot.pixelColor(16, 7) == QColor(Qt.GlobalColor.blue)


def test_widget_surface_transfers_fractional_dpr_frame_pixels_exactly(qapp) -> None:
    """Time-sliced native transfer must not resample fractional-DPR pixels."""
    size = QSize(137, 91)
    source = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    source.setDevicePixelRatio(1.75)
    for y in range(size.height()):
        for x in range(size.width()):
            source.setPixelColor(
                x,
                y,
                QColor(
                    (x * 17 + y * 3) % 256,
                    (x * 5 + y * 19) % 256,
                    (x * 11 + y * 7) % 256,
                    (x * 13 + y * 23) % 256,
                ),
            )
    surface = WidgetRenderSurface()
    surface.allocate(size, 1.75)
    surface.prepare_staging()
    for top in range(0, size.height(), 29):
        for left in range(0, size.width(), 37):
            surface.transfer_staging_patch(
                source,
                QRect(left, top, 37, 29).intersected(source.rect()),
            )

    surface.publish_staging()

    assert surface.snapshot() == source


def test_widget_surface_paints_exposed_logical_pixels_across_wrapped_storage(
    qapp,
) -> None:
    """Partial repair drawing should address logical pixels after a ring advance."""
    surface = WidgetRenderSurface()
    surface.allocate(QSize(8, 4), 1.0)
    surface.pixmap.fill(Qt.GlobalColor.red)
    exposed = surface.scroll(3, 0)

    surface.paint_native(
        lambda painter: painter.fillRect(QRect(0, 0, 3, 4), QColor("green")),
        logical_region=exposed,
    )
    snapshot = surface.snapshot()

    assert all(
        snapshot.pixelColor(x, y) == QColor("green")
        for y in range(snapshot.height())
        for x in range(3)
    )
    assert all(
        snapshot.pixelColor(x, y) == QColor("red")
        for y in range(snapshot.height())
        for x in range(3, snapshot.width())
    )


def test_widget_surface_full_repaint_resets_wrapped_addressing(qapp) -> None:
    """A complete replacement should return subsequent patches to linear storage."""
    surface = WidgetRenderSurface()
    surface.allocate(QSize(8, 4), 1.0)
    surface.scroll(3, 1)

    surface.begin_full_repaint()
    surface.paint_native(
        lambda painter: painter.fillRect(surface.pixmap.rect(), QColor("green")),
        logical_region=QRegion(surface.pixmap.rect()),
    )

    assert surface.storage_origin.isNull()
    assert surface.snapshot().pixelColor(7, 3) == QColor("green")


def test_widget_surface_snapshot_normalizes_rgb32_storage_alpha(qapp) -> None:
    """Wrapped RGB32 snapshots should keep semantically opaque black pixels opaque."""
    image = QImage(QSize(8, 2), QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.black)
    surface = WidgetRenderSurface()
    surface.restore(image)

    def clear_storage_tail(painter: QPainter) -> None:
        """Write transparent storage bits into the opaque native format."""
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(QRect(5, 0, 3, 2), Qt.GlobalColor.transparent)

    surface.paint_native(clear_storage_tail)
    surface.scroll(3, 0)
    snapshot = surface.snapshot()

    assert snapshot.pixelColor(0, 0) == QColor(0, 0, 0, 255)
