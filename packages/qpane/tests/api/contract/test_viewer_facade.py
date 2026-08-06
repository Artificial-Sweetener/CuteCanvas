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
"""Mounted contract tests for the focused QPane viewer facade."""

from __future__ import annotations

from time import monotonic

from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QRegion
from PySide6.QtWidgets import QWidget
from qpane import QPane, RasterSource, RenderLayer, RenderScene


def _large_image() -> QImage:
    """Return a large opaque image that requires derived render products."""
    image = QImage(4096, 3072, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(24, 72, 120, 255))
    return image


def _wait_for_render_plan(pane: QPane, qapp, timeout_seconds: float = 3.0):
    """Process Qt work until the asynchronous first render product is ready."""
    deadline = monotonic() + timeout_seconds
    plan = pane.calculateRenderPlan()
    while plan is None and monotonic() < deadline:
        qapp.processEvents()
        plan = pane.calculateRenderPlan()
    return plan


def _render_transparent(widget: QWidget) -> QImage:
    """Render one widget into an alpha-preserving image."""
    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    widget.render(
        painter,
        QPoint(),
        QRegion(),
        QWidget.RenderFlag.DrawChildren,
    )
    painter.end()
    return image


def test_qpane_mounts_and_renders_the_convenient_image_path(qapp) -> None:
    """The focused viewer mounts and renders a large image without editor code."""
    pane = QPane()
    pane.resize(800, 600)

    source = pane.setImage(_large_image())
    pane.show()
    qapp.processEvents()

    assert isinstance(source, RasterSource)
    assert pane.scene() is not None
    assert pane.scene().canvas.size().toSize() == QSize(4096, 3072)
    assert _wait_for_render_plan(pane, qapp) is not None
    assert pane.currentZoom() > 0.0
    pane.close()
    pane.deleteLater()
    qapp.processEvents()


def test_qpane_antialiases_the_configured_viewport_corner_radius(qapp) -> None:
    """Viewport presentation clipping must preserve partial edge coverage."""
    pane = QPane()
    pane.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    pane.resize(100, 50)
    image = QImage(100, 50, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("magenta"))

    pane.setViewportCornerRadius(8.0)
    pane.setImage(image)
    pane.show()
    assert _wait_for_render_plan(pane, qapp) is not None
    qapp.processEvents()

    actual = _render_transparent(pane)
    expected = QImage(actual.size(), QImage.Format.Format_ARGB32_Premultiplied)
    expected.fill(Qt.GlobalColor.transparent)
    painter = QPainter(expected)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, 100, 50), 8.0, 8.0)
    painter.setClipPath(path)
    painter.fillRect(expected.rect(), QColor("magenta"))
    painter.end()

    assert pane.viewportCornerRadius() == 8.0
    assert actual == expected
    assert actual.pixelColor(4, 0).alpha() not in {0, 255}
    pane.close()
    pane.deleteLater()
    qapp.processEvents()


def test_qpane_renders_shared_sources_as_independent_layers(qapp) -> None:
    """The public SDK uses one renderer for independently placed source instances."""
    pane = QPane()
    pane.resize(640, 480)
    source = RasterSource.from_image(_large_image())
    scene = RenderScene.from_size(
        QSize(5000, 4000),
        (RenderLayer(source), RenderLayer(source)),
    )

    assert pane.setScene(scene)
    assert not pane.setScene(scene)
    pane.show()
    qapp.processEvents()

    plan = _wait_for_render_plan(pane, qapp)
    assert plan is not None
    assert len(plan.render_items) >= 2
    pane.close()
    pane.deleteLater()
    qapp.processEvents()
