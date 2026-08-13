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

"""Repair-region proof for finite piecewise sampled mappings."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
from qpane.rendering.item_compositor import SceneItemCompositor
from qpane.rendering.panel_mapping import PiecewisePanelMapping
from qpane.scene.bilinear import BilinearLayerTransform
from qpane.scene.raster_sampling import RasterPresentationSampling
from qpane.scene.render_plan import SampledLayerRenderItem, SampledTileRenderData
from qpane_test_support.render_plan import make_render_plan


def test_repair_clip_selects_sample_from_its_finite_projective_patch(qapp) -> None:
    """A broad panel repair must not lose a tile near a projective apex."""
    del qapp
    source_boundary = (
        QPointF(630.6569, 825.8394),
        QPointF(226.5693, 825.8394),
        QPointF(226.5693, 127.4453),
        QPointF(630.6569, 127.4453),
    )
    target_boundary = (
        QPointF(226.5693, 825.8394),
        QPointF(226.5693, 825.8394),
        QPointF(226.5693, 127.4453),
        QPointF(630.6569, 127.4453),
    )
    mapping = PiecewisePanelMapping.from_layer_mapping(
        BilinearLayerTransform(source_boundary, target_boundary),
        QTransform(),
    )
    finite_patch = mapping.patches[5]
    source_rect = finite_patch.source_path.boundingRect()
    sample = QImage(
        max(1, round(source_rect.width())),
        max(1, round(source_rect.height())),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    sample.fill(QColor("magenta"))
    transparent = QImage(960, 900, QImage.Format.Format_ARGB32_Premultiplied)
    transparent.fill(Qt.GlobalColor.transparent)
    plan = make_render_plan(QRect(0, 0, 960, 900), source_image=transparent)
    raster_item = plan.render_items[0]
    item = SampledLayerRenderItem(
        descriptor=raster_item.descriptor,
        transform=mapping,
        placement=raster_item.placement,
        clip=None,
        source_size=QSize(960, 900),
        presentation_sampling=RasterPresentationSampling.BILINEAR,
        tiles=(
            SampledTileRenderData(
                sample,
                source_rect,
                QRectF(sample.rect()),
            ),
        ),
    )
    rendered = QImage(960, 900, QImage.Format.Format_ARGB32_Premultiplied)
    rendered.fill(Qt.GlobalColor.transparent)
    painter = QPainter(rendered)
    try:
        SceneItemCompositor().draw_visible_items(
            painter,
            replace(plan, render_items=(item,)),
            panel_clips=(QRectF(0.0, 0.0, 1000.0, 1000.0),),
        )
    finally:
        painter.end()

    sample_point = finite_patch.panel_path.boundingRect().center().toPoint()
    assert rendered.pixelColor(sample_point) == QColor("magenta")
