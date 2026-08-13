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

"""Mounted presentation proof for projectively mapped scene layers."""

from __future__ import annotations

import uuid

import pytest
from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from qpane.rendering.item_compositor import SceneItemCompositor
from qpane.rendering.scene_hit_testing import SceneRenderHitTester
from qpane.scene.render_plan import SceneRenderPlan
from qpane_test_support.timing import interaction_clock, stable_latency_samples

from qpane import (
    ProjectiveLayerTransform,
    QPane,
    RasterSource,
    RenderLayer,
    RenderScene,
)


def test_projective_layer_draws_and_hit_tests_through_one_render_plan(qapp) -> None:
    """Mounted planning, composition, and input share the exact homography."""
    source = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(QColor("magenta"))
    mapping = ProjectiveLayerTransform.from_quadrilaterals(
        _source_corners(),
        (
            QPointF(0.0, 0.0),
            QPointF(64.0, 8.0),
            QPointF(64.0, 64.0),
            QPointF(0.0, 64.0),
        ),
    )
    layer = RenderLayer(RasterSource.from_image(source), transform=mapping)
    pane = QPane()
    pane.resize(64, 64)
    try:
        assert pane.setScene(
            RenderScene.from_size(QSize(64, 64), (layer,)),
            fit=False,
        )
        plan = pane.calculateRenderPlan()

        assert plan is not None
        assert len(plan.render_items) == 1
        item = plan.render_items[0]
        assert not item.transform.isAffine()
        rendered = _draw_plan(plan)
        assert rendered.pixelColor(32, 32) == QColor("magenta")
        assert rendered.pixelColor(63, 0).alpha() == 0

        source_point = QPointF(32.0, 32.0)
        panel_point = item.transform.map(source_point)
        hit = SceneRenderHitTester().hit_test(plan, item, panel_point)
        assert hit is not None
        assert (hit.source_point.x(), hit.source_point.y()) == pytest.approx(
            (source_point.x(), source_point.y())
        )
        expected_scene = mapping.map_point(source_point)
        assert (hit.scene_point.x(), hit.scene_point.y()) == pytest.approx(
            (expected_scene.x(), expected_scene.y())
        )
    finally:
        pane.clear()
        pane.close()
        pane.deleteLater()
        qapp.processEvents()


@pytest.mark.interactive_performance
def test_projective_mapping_updates_present_inside_one_frame(qapp) -> None:
    """Stable projective scene replacement must remain below 16 ms."""
    source = RasterSource.from_image(_solid_source())
    scene_id = uuid.uuid4()
    layer_id = uuid.uuid4()
    pane = QPane()
    pane.resize(64, 64)
    latencies: list[float] = []
    try:
        for index in range(96):
            mapping = ProjectiveLayerTransform.from_quadrilaterals(
                _source_corners(),
                (
                    QPointF(0.0, 0.0),
                    QPointF(64.0, float(index % 9)),
                    QPointF(64.0, 64.0),
                    QPointF(0.0, 64.0),
                ),
            )
            layer = RenderLayer(source, layer_id=layer_id, transform=mapping)
            started = interaction_clock()
            assert pane.setScene(
                RenderScene.from_size(
                    QSize(64, 64),
                    (layer,),
                    scene_id=scene_id,
                ),
                fit=False,
            )
            qapp.processEvents()
            latencies.append((interaction_clock() - started) * 1000.0)

        assert max(stable_latency_samples(latencies, parallel_batch_size=12)) < 16.0
    finally:
        pane.clear()
        pane.close()
        pane.deleteLater()
        qapp.processEvents()


def _draw_plan(plan: SceneRenderPlan) -> QImage:
    """Render one immutable plan through the authoritative compositor."""
    image = QImage(plan.qpane_rect.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        SceneItemCompositor().draw_visible_items(painter, plan)
    finally:
        painter.end()
    return image


def _solid_source() -> QImage:
    """Return the detached raster fixture used by performance updates."""
    image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("magenta"))
    return image


def _source_corners() -> tuple[QPointF, QPointF, QPointF, QPointF]:
    """Return ordered corners for the canonical square source fixture."""
    return (
        QPointF(0.0, 0.0),
        QPointF(64.0, 0.0),
        QPointF(64.0, 64.0),
        QPointF(0.0, 64.0),
    )
