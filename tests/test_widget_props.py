#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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

"""Regression tests for QPane widget drawing defaults."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from qpane import QPane
from qpane.raster.image_conversion import qimage_to_numpy_argb32
from qpane.ui.widget_props import apply_widget_defaults

from tests.harness.timing import completion_clock
from tests.helpers.render_compare import checker_image


def test_widget_defaults_preserve_host_background_composition(
    qapp: QApplication,
) -> None:
    """QPane should use Qt's normal child-background propagation contract."""
    widget = QWidget()
    try:
        apply_widget_defaults(widget)

        assert widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        assert not widget.testAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        assert not widget.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
    finally:
        widget.deleteLater()
        qapp.processEvents()


def test_blank_qpane_composites_the_parent_background(qapp: QApplication) -> None:
    """Transparent canvas pixels should reveal the host widget beneath them."""
    parent = QWidget()
    parent.resize(96, 64)
    parent.setStyleSheet("background-color: rgb(187, 43, 91);")
    pane = QPane()
    pane.setParent(parent)
    pane.setGeometry(parent.rect())
    try:
        parent.show()
        qapp.processEvents()

        image = parent.grab().toImage()

        assert image.pixelColor(48, 32) == QColor(187, 43, 91)
    finally:
        parent.close()
        parent.deleteLater()
        qapp.processEvents()


def test_qpane_composites_parent_outside_rendered_scene(qapp: QApplication) -> None:
    """Transparent buffer pixels around scene content should reveal the host."""
    parent = QWidget()
    parent.resize(96, 64)
    parent.setStyleSheet("background-color: rgb(187, 43, 91);")
    pane = QPane()
    pane.setParent(parent)
    pane.setGeometry(parent.rect())
    image = QImage(16, 16, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(21, 133, 204))
    pane.setImage(image)
    pane.setZoom1To1()
    try:
        parent.show()
        qapp.processEvents()

        rendered = parent.grab().toImage()

        assert rendered.pixelColor(2, 2) == QColor(187, 43, 91)
        assert rendered.pixelColor(48, 32) == QColor(21, 133, 204)

        pane.clear()
        qapp.processEvents()
        cleared = parent.grab().toImage()

        assert cleared.pixelColor(48, 32) == QColor(187, 43, 91)
    finally:
        parent.close()
        parent.deleteLater()
        qapp.processEvents()


def test_qpane_composites_parent_through_transparent_scene_pixels(
    qapp: QApplication,
) -> None:
    """Transparent source pixels should preserve the host inside scene bounds."""
    parent = QWidget()
    parent.resize(96, 64)
    parent.setStyleSheet("background-color: rgb(187, 43, 91);")
    pane = QPane()
    pane.setParent(parent)
    pane.setGeometry(parent.rect())
    image = QImage(16, 16, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    image.setPixelColor(0, 0, QColor(21, 133, 204))
    pane.setImage(image)
    pane.setZoom1To1()
    try:
        parent.show()
        qapp.processEvents()

        rendered = parent.grab().toImage()

        assert rendered.pixelColor(40, 24) == QColor(21, 133, 204)
        assert rendered.pixelColor(48, 32) == QColor(187, 43, 91)
    finally:
        parent.close()
        parent.deleteLater()
        qapp.processEvents()


def test_anchored_zoom_preview_matches_authoritative_frame(
    qapp: QApplication,
) -> None:
    """Every immediate zoom frame must preserve pixels and anchor coordinates."""
    parent = QWidget()
    parent.resize(320, 240)
    parent.setStyleSheet("background-color: rgb(187, 43, 91);")
    pane = QPane()
    pane.setParent(parent)
    pane.setGeometry(parent.rect())
    pane.applySettings(smooth_zoom_enabled=False)
    image = checker_image(QSize(400, 300))
    pane.setImage(image)
    pane.setZoom1To1()
    anchor = QPointF(83.0, 61.0)
    presenter = pane._rendering.presenter
    try:
        parent.show()
        qapp.processEvents()

        for zoom in (1.23, 0.91, 1.47, 1.08):
            scene_before = presenter.panel_to_scene_point(anchor)
            assert scene_before is not None

            pane.applyZoom(zoom, anchor)
            pane.repaint()
            preview = parent.grab().toImage()
            scene_after = presenter.panel_to_scene_point(anchor)
            assert scene_after is not None

            presenter.renderer.markDirty()
            pane.repaint()
            authoritative = parent.grab().toImage()

            assert abs(scene_after.x() - scene_before.x()) <= 1e-6
            assert abs(scene_after.y() - scene_before.y()) <= 1e-6
            preview_anchor = preview.pixelColor(anchor.toPoint())
            authoritative_anchor = authoritative.pixelColor(anchor.toPoint())
            anchor_delta = max(
                abs(preview_channel - authoritative_channel)
                for preview_channel, authoritative_channel in zip(
                    preview_anchor.getRgb(),
                    authoritative_anchor.getRgb(),
                    strict=True,
                )
            )
            assert anchor_delta <= 8
    finally:
        parent.close()
        parent.deleteLater()
        qapp.processEvents()


def test_zoom_preview_never_paints_outside_authoritative_image_bounds(
    qapp: QApplication,
) -> None:
    """Zoom resampling must not add pixels or black backing around the image."""
    host_color = QColor(187, 43, 91)
    parent = QWidget()
    parent.resize(320, 240)
    parent.setStyleSheet("background-color: rgb(187, 43, 91);")
    pane = QPane()
    pane.setParent(parent)
    pane.setGeometry(parent.rect())
    pane.applySettings(smooth_zoom_enabled=False)
    image = QImage(120, 80, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(21, 133, 204))
    pane.setImage(image)
    pane.setZoom1To1()
    presenter = pane._rendering.presenter
    try:
        parent.show()
        qapp.processEvents()

        for zoom in (1.37, 0.82, 1.63, 1.0):
            pane.applyZoom(zoom, QPointF(pane.rect().center()))
            pane.repaint()
            preview = parent.grab().toImage()
            plan = presenter.renderer.get_current_render_plan()
            assert plan is not None
            base_item = plan.base_raster_item
            assert base_item is not None
            image_bounds = presenter.renderer.item_panel_bounds(base_item).adjusted(
                -2,
                -2,
                2,
                2,
            )

            pixels = qimage_to_numpy_argb32(preview)
            black_pixels = np.argwhere(np.all(pixels[:, :, :3] == 0, axis=2))
            assert (
                not black_pixels.size
            ), f"zoom={zoom:g} first_black={black_pixels[0].tolist()}"
            for y in range(preview.height()):
                for x in range(preview.width()):
                    if image_bounds.contains(x, y):
                        continue
                    assert preview.pixelColor(x, y) == host_color

            presenter.renderer.markDirty()
            pane.repaint()
    finally:
        parent.close()
        parent.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize(
    ("viewport_size", "device_pixel_ratio"),
    (
        pytest.param(QSize(320, 240), 1.0, id="small-1x"),
        pytest.param(QSize(3840, 2160), 1.75, id="4k-1.75x"),
    ),
)
def test_settled_pan_and_zoom_keep_staged_canvas_background_transparent(
    qapp: QApplication,
    viewport_size: QSize,
    device_pixel_ratio: float,
) -> None:
    """Atomic navigation frames must keep the host visible through canvas alpha."""
    parent = QWidget()
    parent.resize(viewport_size)
    parent.setStyleSheet("background-color: rgb(187, 43, 91);")
    pane = QPane()
    pane.devicePixelRatioF = lambda: device_pixel_ratio  # type: ignore[method-assign]
    pane.setParent(parent)
    pane.setGeometry(parent.rect())
    pane.applySettings(
        smooth_zoom_enabled=False,
        cache={"mode": "hard", "budget_mb": 0},
    )
    image = QImage(800, 600, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    image_painter = QPainter(image)
    try:
        image_painter.fillRect(240, 180, 320, 240, QColor(21, 133, 204))
    finally:
        image_painter.end()
    pane.setImage(image)
    pane.setZoom1To1()
    presenter = pane._rendering.presenter

    def wait_for_navigation_refinement() -> None:
        """Drain the exact-frame lifecycle without accepting a latent timer."""
        deadline = completion_clock() + 8.0
        while presenter.navigation_refinement_pending and completion_clock() < deadline:
            qapp.processEvents()
            QTest.qWait(1)
        assert not presenter.navigation_refinement_pending

    def assert_parent_has_no_black_pixels() -> None:
        """Reject opaque-black pixels from the transparent navigation surface."""
        rendered = parent.grab().toImage()
        pixels = qimage_to_numpy_argb32(rendered)
        black_pixels = np.argwhere(np.all(pixels[:, :, :3] == 0, axis=2))
        assert not black_pixels.size, black_pixels[0].tolist()
        assert np.any(np.all(pixels[:, :, :3] == np.array([91, 43, 187]), axis=2))

    try:
        parent.show()
        qapp.processEvents()
        renderer = presenter.renderer

        presenter.begin_navigation_interaction()
        pane.setPan(
            QPointF(
                float(renderer.buffer_overscan_physical_px + 16),
                64.0,
            )
        )
        presenter.finish_navigation_interaction()
        wait_for_navigation_refinement()

        assert renderer._surface.pixmap.hasAlphaChannel()
        assert_parent_has_no_black_pixels()

        pane.applyZoom(1.25, QPointF(pane.rect().center()))
        wait_for_navigation_refinement()

        assert renderer._surface.pixmap.hasAlphaChannel()
        assert_parent_has_no_black_pixels()
    finally:
        parent.close()
        parent.deleteLater()
        qapp.processEvents()
