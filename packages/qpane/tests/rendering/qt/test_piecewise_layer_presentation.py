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

"""Mounted presentation proof for finite piecewise layer mappings."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPathStroker

from qpane import (
    BilinearLayerTransform,
    PiecewiseLayerTransform,
    QPane,
    RasterSource,
    RenderLayer,
    RenderScene,
)
from qpane.rendering.item_compositor import SceneItemCompositor
from qpane.rendering.panel_mapping import PiecewisePanelMapping
from qpane.rendering.piecewise_compositor import draw_piecewise_item
from qpane.rendering.scene_hit_testing import SceneRenderHitTester
from qpane.scene.render_plan import SceneRenderPlan


def test_piecewise_layer_draws_without_a_false_global_transform(qapp) -> None:
    """A split boundary vertex deforms, paints, and hit-tests through one plan."""
    source = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(QColor("magenta"))
    mapping = PiecewiseLayerTransform(
        _split_boundary(),
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
        item = plan.render_items[0]
        assert isinstance(item.transform, PiecewisePanelMapping)
        rendered = _draw_plan(plan)
        assert rendered.pixelColor(24, 32) == QColor("magenta")
        assert rendered.pixelColor(60, 32).alpha() == 0

        source_point = QPointF(32.0, 32.0)
        panel_point = item.transform.map_point(source_point)
        hit = SceneRenderHitTester().hit_test(plan, item, panel_point)
        assert hit is not None
        assert (hit.source_point.x(), hit.source_point.y()) == pytest.approx(
            (32.0, 32.0)
        )
    finally:
        pane.clear()
        pane.close()
        pane.deleteLater()
        qapp.processEvents()


def test_piecewise_layer_composites_internal_edges_once(qapp) -> None:
    """Adjacent mapping patches must not reveal their shared triangulation edge."""
    background = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    background.fill(QColor("black"))
    foreground = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    foreground.fill(QColor("white"))
    mapping = PiecewiseLayerTransform(
        _split_boundary(),
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
                (
                    RenderLayer(RasterSource.from_image(background)),
                    RenderLayer(
                        RasterSource.from_image(foreground),
                        transform=mapping,
                        opacity=0.5,
                    ),
                ),
            ),
            fit=False,
        )
        plan = pane.calculateRenderPlan()

        assert plan is not None
        rendered = _draw_plan(plan)
        item = plan.render_items[1]
        assert isinstance(item.transform, PiecewisePanelMapping)
        reds = tuple(
            rendered.pixelColor(x, y).red()
            for y in range(rendered.height())
            for x in range(rendered.width())
        )

        assert 127 in reds
        assert max(reds) <= 128
        boundary_stroker = QPainterPathStroker()
        boundary_stroker.setWidth(4.0)
        interior = item.transform.panel_path.subtracted(
            boundary_stroker.createStroke(item.transform.panel_path)
        )
        assert all(
            rendered.pixelColor(x, y).red() == 127
            for y in range(rendered.height())
            for x in range(rendered.width())
            if interior.contains(QPointF(x + 0.5, y + 0.5))
        )
    finally:
        pane.clear()
        pane.close()
        pane.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize(
    "mapping",
    (
        BilinearLayerTransform(
            (
                QPointF(0.0, 0.0),
                QPointF(64.0, 0.0),
                QPointF(64.0, 64.0),
                QPointF(0.0, 64.0),
            ),
            (
                QPointF(64.0, 0.0),
                QPointF(64.0, 0.0),
                QPointF(64.0, 64.0),
                QPointF(0.0, 64.0),
            ),
        ),
        PiecewiseLayerTransform(
            (
                QPointF(64.0, 64.0),
                QPointF(64.0, 0.0),
                QPointF(128.0, 0.0),
                QPointF(128.0, 88.0),
                QPointF(64.0, 88.0),
            ),
            (
                QPointF(64.0, 64.0),
                QPointF(0.0, 0.0),
                QPointF(128.0, 0.0),
                QPointF(128.0, 88.0),
                QPointF(64.0, 88.0),
            ),
        ),
    ),
)
def test_endpoint_limit_cages_have_no_transparent_internal_pixels(
    qapp,
    mapping: PiecewiseLayerTransform | BilinearLayerTransform,
) -> None:
    """Joined endpoints and inserted rails remain watertight when rasterized."""
    source = QImage(128, 96, QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(QColor("magenta"))
    pane = QPane()
    pane.resize(128, 96)
    try:
        assert pane.setScene(
            RenderScene.from_size(
                QSize(128, 96),
                (RenderLayer(RasterSource.from_image(source), transform=mapping),),
            ),
            fit=False,
        )
        plan = pane.calculateRenderPlan()
        assert plan is not None
        item = plan.render_items[0]
        assert isinstance(item.transform, PiecewisePanelMapping)
        rendered = _draw_plan(plan)
        boundary_stroker = QPainterPathStroker()
        boundary_stroker.setWidth(4.0)
        interior = item.transform.panel_path.subtracted(
            boundary_stroker.createStroke(item.transform.panel_path)
        )

        assert all(
            rendered.pixelColor(x, y) == QColor("magenta")
            for y in range(rendered.height())
            for x in range(rendered.width())
            if interior.contains(QPointF(x + 0.5, y + 0.5))
        )
    finally:
        pane.clear()
        pane.close()
        pane.deleteLater()
        qapp.processEvents()


def test_piecewise_layer_applies_opacity_once_across_all_patches(qapp) -> None:
    """Patch drawing remains opaque until one complete-layer composition."""
    source = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(QColor("white"))
    pane = QPane()
    pane.resize(64, 64)
    try:
        assert pane.setScene(
            RenderScene.from_size(
                QSize(64, 64),
                (
                    RenderLayer(
                        RasterSource.from_image(source),
                        transform=PiecewiseLayerTransform(
                            _split_boundary(),
                            (
                                QPointF(0.0, 0.0),
                                QPointF(64.0, 0.0),
                                QPointF(48.0, 32.0),
                                QPointF(64.0, 64.0),
                                QPointF(0.0, 64.0),
                            ),
                        ),
                        opacity=0.5,
                    ),
                ),
            ),
            fit=False,
        )
        plan = pane.calculateRenderPlan()
        assert plan is not None
        item = plan.render_items[0]
        assert isinstance(item.transform, PiecewisePanelMapping)
        isolation = _RecordingIsolation()
        patch_opacities: list[float] = []
        image = QImage(plan.qpane_rect.size(), QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        try:
            assert draw_piecewise_item(
                painter,
                item,
                isolation=isolation,
                panel_bounds=QRectF(plan.qpane_rect),
                panel_clips=None,
                draw_patch=lambda _target, patch, _clips: patch_opacities.append(
                    patch.descriptor.opacity
                ),
            )
        finally:
            painter.end()

        assert isolation.opacities == [0.5]
        assert patch_opacities == [1.0] * len(item.transform.patches)
    finally:
        pane.clear()
        pane.close()
        pane.deleteLater()
        qapp.processEvents()


def test_piecewise_layer_pan_publishes_during_active_navigation(qapp) -> None:
    """A guarded pan presents translated piecewise patches before release."""
    source = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(QColor("white"))
    pane = QPane()
    pane.resize(160, 120)
    mapping = PiecewiseLayerTransform(
        _split_boundary(),
        (
            QPointF(0.0, 0.0),
            QPointF(64.0, 0.0),
            QPointF(48.0, 32.0),
            QPointF(64.0, 64.0),
            QPointF(0.0, 64.0),
        ),
    )
    presenter = pane._rendering.presenter
    try:
        assert pane.setScene(
            RenderScene.from_size(
                QSize(64, 64),
                (RenderLayer(RasterSource.from_image(source), transform=mapping),),
            ),
            fit=False,
        )
        pane.applyZoom(4.0)
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        presenter.begin_navigation_interaction()

        pane.setPan(QPointF(6.0, -4.0))

        presented = presenter.renderer.get_current_render_plan()
        assert presented is not None
        assert presented.current_pan == QPointF(6.0, -4.0)
        assert isinstance(
            presented.render_items[0].transform,
            PiecewisePanelMapping,
        )
    finally:
        presenter.finish_navigation_interaction()
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


def _split_boundary() -> tuple[QPointF, ...]:
    """Return a rectangular source cage with an explicit right-edge vertex."""
    return (
        QPointF(0.0, 0.0),
        QPointF(64.0, 0.0),
        QPointF(64.0, 32.0),
        QPointF(64.0, 64.0),
        QPointF(0.0, 64.0),
    )


class _RecordingIsolation:
    """Record isolated compositing while executing its paint callback."""

    def __init__(self) -> None:
        """Create an empty opacity record."""
        self.opacities: list[float] = []

    def composite(
        self,
        painter: QPainter,
        *,
        opacity: float,
        paint_layer: Callable[[QPainter], None],
    ) -> None:
        """Record the final opacity and execute the isolated layer draw."""
        self.opacities.append(opacity)
        paint_layer(painter)
