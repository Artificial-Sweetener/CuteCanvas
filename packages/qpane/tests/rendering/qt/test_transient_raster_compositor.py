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
"""Pixel contracts for source-neutral transient raster composition."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter
from qpane.rendering.layer_isolation import LayerIsolationCompositor
from qpane.rendering.transient_raster_compositor import TransientRasterCompositor
from qpane.scene.affine import LayerTransform
from qpane.scene.raster import RasterBounds
from qpane.scene.render_plan import TransientRasterTransformContribution
from qpane_test_support.render_plan import make_render_plan


def test_destination_attenuation_adds_contribution_without_double_fading() -> None:
    """Attenuation followed by addition must implement scalar replacement math."""
    plan = make_render_plan(QRect(0, 0, 1, 1))
    item = plan.render_items[0]
    destination = QImage(1, 1, QImage.Format_ARGB32_Premultiplied)
    destination.fill(QColor(255, 0, 0, 80))
    fragment = QImage(1, 1, QImage.Format_ARGB32_Premultiplied)
    fragment.fill(QColor(255, 0, 0, 100))
    attenuation = QImage(1, 1, QImage.Format_ARGB32_Premultiplied)
    attenuation.fill(QColor(0, 0, 0, 128))
    contribution = TransientRasterTransformContribution(
        session_id=uuid.uuid4(),
        scene_id=plan.scene_id,
        layer_id=item.descriptor.layer_id,
        source_asset_key=item.asset_key,
        source_patch=None,
        source_bounds=RasterBounds(0, 0, 1, 1),
        fragment_image=fragment,
        fragment_bounds=RasterBounds(0, 0, 1, 1),
        destination_attenuation_mask=attenuation,
        fragment_transform=LayerTransform(),
        extent_clip_bounds=None,
    )
    painter = QPainter(destination)
    try:
        TransientRasterCompositor(LayerIsolationCompositor()).apply(
            painter,
            item,
            contribution,
        )
    finally:
        painter.end()

    assert 139 <= destination.pixelColor(0, 0).alpha() <= 141
