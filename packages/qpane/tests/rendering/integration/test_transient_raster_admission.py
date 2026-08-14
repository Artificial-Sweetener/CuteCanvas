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
"""Verify transient raster products are admitted only to compatible items."""

from __future__ import annotations

import uuid
from dataclasses import replace

from PySide6.QtCore import QRect, QRectF
from PySide6.QtGui import QColor, QImage, QPainter

from qpane.rendering.item_compositor import SceneItemCompositor
from qpane.rendering.transient_raster import TransientRasterHandoff
from qpane.scene.raster import RasterBounds
from qpane.scene.render_plan import (
    SampledTileRenderData,
    TransientSampledResolvedContribution,
)
from qpane_test_support.render_plan import make_render_plan


def test_sampled_contribution_is_rejected_before_raster_item_composition() -> None:
    """A sampled handoff cannot escape admission into raster-only painting."""
    plan = make_render_plan(QRect(0, 0, 64, 64))
    item = plan.render_items[0]
    sampled_image = QImage(64, 64, QImage.Format_ARGB32_Premultiplied)
    sampled_image.fill(QColor(220, 40, 120, 255))
    sampled_tile = SampledTileRenderData(
        sampled_image,
        QRectF(0.0, 0.0, 64.0, 64.0),
        QRectF(sampled_image.rect()),
    )
    contribution = TransientSampledResolvedContribution(
        session_id=uuid.uuid4(),
        scene_id=item.descriptor.scene_id,
        layer_id=item.descriptor.layer_id,
        source_asset_key=item.asset_key,
        source_bounds=RasterBounds(8, 8, 16, 16),
        tiles=(sampled_tile,),
        sampled_raster_bounds=item.descriptor.raster_bounds,
        sampled_source_size=item.source_size,
    )

    settled, needs_redraw = TransientRasterHandoff().settled_plan(
        replace(plan, transient_raster=contribution)
    )
    output = QImage(64, 64, QImage.Format_ARGB32_Premultiplied)
    output.fill(QColor(0, 0, 0, 0))
    painter = QPainter(output)
    try:
        SceneItemCompositor().draw_visible_items(painter, settled)
    finally:
        painter.end()

    assert settled.transient_raster is None
    assert needs_redraw
    assert output.pixelColor(32, 32) == item.source_image.pixelColor(32, 32)
