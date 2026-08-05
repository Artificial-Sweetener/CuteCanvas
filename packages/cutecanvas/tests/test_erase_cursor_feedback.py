#    CuteCanvas - High-performance layered image editor
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

"""Verify canonical erase feedback across every cursor rendering path."""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

from cutecanvas.painting.tools.brush_preview import BrushPreview, BrushPreviewRenderer
from cutecanvas.ui.cursor_builder import CursorBuilder
from cutecanvas.ui.erase_indicator import EraseIndicatorRenderer
from PySide6.QtCore import QPointF, QRect, QRectF, QSizeF
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from qpane import PointerDeviceKind


class _RecordingEraseIndicator(EraseIndicatorRenderer):
    """Record canonical decoration requests while retaining real rendering."""

    def __init__(self) -> None:
        """Initialize an empty logical-bounds history."""
        self.bounds: list[QRectF] = []

    def draw(self, painter: QPainter, bounds: QRectF) -> None:
        """Record and render one erase decoration request."""
        self.bounds.append(QRectF(bounds))
        super().draw(painter, bounds)


def test_canonical_erase_decorator_uses_the_brush_underscore_glyph() -> None:
    """The erase marker must retain the established outlined underscore."""
    painter = MagicMock(spec=QPainter)
    painter.font.return_value = QFont()

    EraseIndicatorRenderer().draw(
        cast(QPainter, painter),
        QRectF(0.0, 0.0, 32.0, 32.0),
    )

    assert [call.args[2] for call in painter.drawText.call_args_list] == ["_", "_"]


def test_every_feedback_family_uses_the_canonical_erase_decorator(qapp) -> None:
    """Brush, precision, and direct preview feedback must share one renderer."""
    indicator = _RecordingEraseIndicator()
    builder = CursorBuilder(indicator)
    preview_renderer = BrushPreviewRenderer(indicator)

    builder.create_brush_cursor(32, QColor("red"), True)
    builder.create_precision_cursor(True)
    image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    preview_renderer.draw(
        painter,
        BrushPreview.at(
            QPointF(32.0, 32.0),
            diameter=32.0,
            erase=True,
            device=PointerDeviceKind.MOUSE,
            contact=False,
        ),
        zoom=1.0,
        dpr=1.0,
        color=QColor("red"),
    )
    painter.end()

    assert indicator.bounds == [
        QRectF(4.0, 4.0, 32.0, 32.0),
        QRectF(0.0, 0.0, 32.0, 32.0),
        QRectF(16.0, 16.0, 32.0, 32.0),
    ]


def test_cursor_rasters_preserve_logical_geometry_at_fractional_dpr(qapp) -> None:
    """High-DPI cursors must gain physical detail without changing their size."""
    builder = CursorBuilder()

    brush_1x = builder.create_brush_cursor(
        32,
        QColor("white"),
        True,
        device_pixel_ratio=1.0,
    )
    brush_175x = builder.create_brush_cursor(
        32,
        QColor("white"),
        True,
        device_pixel_ratio=1.75,
    )
    precision_1x = builder.create_precision_cursor(True, device_pixel_ratio=1.0)
    precision_175x = builder.create_precision_cursor(
        True,
        device_pixel_ratio=1.75,
    )

    assert brush_1x.pixmap().deviceIndependentSize() == QSizeF(40.0, 40.0)
    assert brush_175x.pixmap().deviceIndependentSize() == QSizeF(40.0, 40.0)
    assert brush_175x.pixmap().size().width() == 70
    assert brush_175x.hotSpot() == brush_1x.hotSpot()
    assert precision_1x.pixmap().deviceIndependentSize() == QSizeF(40.0, 40.0)
    assert precision_175x.pixmap().deviceIndependentSize() == QSizeF(40.0, 40.0)
    assert precision_175x.pixmap().size().width() == 70
    assert precision_175x.hotSpot() == precision_1x.hotSpot()


def test_precision_add_cursor_is_cached_and_preserves_hotspot(qapp) -> None:
    """Addition feedback should add detail without changing pointing geometry."""

    builder = CursorBuilder()

    plain = builder.create_precision_cursor(device_pixel_ratio=1.5)
    addition = builder.create_precision_cursor(
        add_indicator=True,
        device_pixel_ratio=1.5,
    )
    repeated = builder.create_precision_cursor(
        add_indicator=True,
        device_pixel_ratio=1.5,
    )

    assert addition.hotSpot() == plain.hotSpot()
    assert addition.pixmap().cacheKey() == repeated.pixmap().cacheKey()
    assert addition.pixmap().cacheKey() != plain.pixmap().cacheKey()


def test_precision_erase_glyph_matches_same_diameter_brush_across_dprs(qapp) -> None:
    """Precision feedback must match an equal displayed brush diameter."""
    indicator = _RecordingEraseIndicator()
    builder = CursorBuilder(indicator)

    for device_pixel_ratio in (1.0, 1.25, 1.5, 2.0):
        builder.create_brush_cursor(
            32,
            QColor("white"),
            True,
            device_pixel_ratio=device_pixel_ratio,
        )
        builder.create_precision_cursor(
            True,
            device_pixel_ratio=device_pixel_ratio,
        )

    assert len(indicator.bounds) == 8
    for brush_bounds, precision_bounds in zip(
        indicator.bounds[::2],
        indicator.bounds[1::2],
        strict=True,
    ):
        assert brush_bounds.size() == precision_bounds.size() == QSizeF(32.0, 32.0)


def test_equal_diameter_cursors_render_equal_erase_glyph_bounds(qapp) -> None:
    """Composition padding must prevent tool cursors from clipping the glyph."""
    builder = CursorBuilder()

    for device_pixel_ratio in (1.0, 1.25, 1.5, 2.0):
        brush_plain = builder.create_brush_cursor(
            32,
            QColor("white"),
            False,
            device_pixel_ratio=device_pixel_ratio,
        )
        brush_erase = builder.create_brush_cursor(
            32,
            QColor("white"),
            True,
            device_pixel_ratio=device_pixel_ratio,
        )
        precision_plain = builder.create_precision_cursor(
            False,
            device_pixel_ratio=device_pixel_ratio,
        )
        precision_erase = builder.create_precision_cursor(
            True,
            device_pixel_ratio=device_pixel_ratio,
        )

        assert (
            _changed_pixel_bounds(
                brush_plain.pixmap().toImage(), brush_erase.pixmap().toImage()
            ).size()
            == _changed_pixel_bounds(
                precision_plain.pixmap().toImage(),
                precision_erase.pixmap().toImage(),
            ).size()
        )


def _changed_pixel_bounds(before: QImage, after: QImage) -> QRect:
    """Return the physical bounds whose rendered pixels changed."""
    changed = [
        (x, y)
        for y in range(before.height())
        for x in range(before.width())
        if before.pixel(x, y) != after.pixel(x, y)
    ]
    assert changed
    x_values = [point[0] for point in changed]
    y_values = [point[1] for point in changed]
    return QRect(
        min(x_values),
        min(y_values),
        max(x_values) - min(x_values) + 1,
        max(y_values) - min(y_values) + 1,
    )
