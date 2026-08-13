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
"""Characterize viewport transforms while a mounted QPane is resized."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from qpane import QPane


@pytest.fixture()
def mounted_pane(qapp: QApplication) -> Iterator[QPane]:
    """Mount a deterministic image viewer and release all Qt resources."""
    pane = QPane()
    pane.resize(400, 300)
    image = QImage(1600, 1200, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(32, 64, 96, 255))
    pane.setImage(image)
    pane.show()
    qapp.processEvents()
    try:
        yield pane
    finally:
        pane.close()
        pane.deleteLater()
        qapp.processEvents()


def test_manual_view_preserves_scale_pan_and_content_center_across_resizes(
    mounted_pane: QPane,
    qapp: QApplication,
) -> None:
    """Manual navigation must remain invariant even when content begins to fit."""
    pane = mounted_pane
    pane.applyZoom(0.5)
    pane.setPan(QPointF(150.0, 100.0))
    qapp.processEvents()
    expected_zoom = pane.currentZoom()
    expected_pan = QPointF(pane.currentPan())

    for size in (
        QSize(1200, 900),
        QSize(1, 1),
        QSize(2000, 1500),
        QSize(400, 300),
        QSize(799, 601),
    ):
        pane.resize(size)
        qapp.processEvents()

        assert pane.currentZoom() == pytest.approx(expected_zoom)
        assert pane.currentPan() == expected_pan


def test_fit_view_recomputes_scale_when_viewport_resizes(
    mounted_pane: QPane,
    qapp: QApplication,
) -> None:
    """FIT remains responsive to viewport geometry instead of becoming manual."""
    pane = mounted_pane
    pane.setZoomFit()
    qapp.processEvents()
    original_zoom = pane.currentZoom()

    pane.resize(800, 600)
    qapp.processEvents()

    assert pane.currentZoom() > original_zoom
    assert pane.currentPan() == QPointF()
