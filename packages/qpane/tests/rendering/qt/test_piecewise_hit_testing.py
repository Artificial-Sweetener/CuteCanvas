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

"""Mounted hit-testing proof for finite piecewise layer mappings."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor, QImage
from qpane import PiecewiseLayerTransform, QPane, RasterSource, RenderLayer, RenderScene
from qpane.rendering.scene_hit_testing import SceneRenderHitTester


def test_piecewise_hit_test_rejects_panel_point_outside_layer(qapp) -> None:
    """Hovering empty panel space beside a deformed layer returns no hit."""
    source = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(QColor("magenta"))
    mapping = PiecewiseLayerTransform(
        (
            QPointF(0.0, 0.0),
            QPointF(64.0, 0.0),
            QPointF(64.0, 32.0),
            QPointF(64.0, 64.0),
            QPointF(0.0, 64.0),
        ),
        (
            QPointF(0.0, 0.0),
            QPointF(64.0, 0.0),
            QPointF(48.0, 32.0),
            QPointF(64.0, 64.0),
            QPointF(0.0, 64.0),
        ),
    )
    pane = QPane()
    pane.resize(64, 64)
    try:
        assert pane.setScene(
            RenderScene.from_size(
                QSize(64, 64),
                (RenderLayer(RasterSource.from_image(source), transform=mapping),),
            ),
            fit=False,
        )
        plan = pane.calculateRenderPlan()

        assert plan is not None
        assert (
            SceneRenderHitTester().hit_test(
                plan,
                plan.render_items[0],
                QPointF(60.0, 32.0),
            )
            is None
        )
    finally:
        pane.clear()
        pane.close()
        pane.deleteLater()
        qapp.processEvents()
