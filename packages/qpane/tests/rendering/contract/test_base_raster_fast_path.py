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

"""Contract proof for direct base-raster presentation eligibility."""

from __future__ import annotations

import uuid
from dataclasses import replace

from PySide6.QtCore import QPointF, QRect
from PySide6.QtGui import QTransform
from qpane import ClipCoordinateSpace, LayerClip, PiecewiseLayerTransform
from qpane.rendering.base_raster_fast_path import base_only_raster_item
from qpane.rendering.panel_mapping import PiecewisePanelMapping
from qpane_test_support.render_plan import make_render_plan


def test_base_fast_path_accepts_one_ordinary_affine_raster() -> None:
    """A sole opaque affine base raster uses the direct drawing path."""
    plan = make_render_plan(QRect(0, 0, 320, 180))

    assert base_only_raster_item(plan) is plan.render_items[0]


def test_base_fast_path_rejects_piecewise_mapping() -> None:
    """Finite mappings retain complete-layer compositing on full repaint."""
    plan = make_render_plan(QRect(0, 0, 320, 180))
    item = plan.render_items[0]
    mapping = PiecewisePanelMapping.from_layer_mapping(
        PiecewiseLayerTransform(
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
        ),
        QTransform(),
    )
    piecewise = replace(item, transform=mapping)
    plan = replace(plan, render_items=(piecewise,))

    assert base_only_raster_item(plan) is None


def test_base_fast_path_rejects_clipped_raster() -> None:
    """A clipped base retains visibility-aware scene composition."""
    plan = make_render_plan(QRect(0, 0, 320, 180))
    item = plan.render_items[0]
    clip = LayerClip(
        coordinate_space=ClipCoordinateSpace.NORMALIZED_VIEWPORT,
        x=0.0,
        y=0.0,
        width=0.5,
        height=1.0,
    )
    clipped = replace(
        item,
        descriptor=replace(item.descriptor, clip=clip),
        clip=clip,
    )

    assert base_only_raster_item(replace(plan, render_items=(clipped,))) is None


def test_base_fast_path_rejects_additional_layer() -> None:
    """Every layered plan retains complete scene composition."""
    plan = make_render_plan(QRect(0, 0, 320, 180))
    item = plan.render_items[0]
    additional = replace(
        item,
        descriptor=replace(item.descriptor, layer_id=uuid.uuid4()),
        is_base_raster=False,
    )

    assert base_only_raster_item(replace(plan, render_items=(item, additional))) is None
