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
"""Regression proofs for exact affine layer-clip projection."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPointF, QRect

from qpane.rendering.layer_clip_projection import source_clip_path
from qpane.scene.affine import LayerTransform
from qpane.scene.model import ClipCoordinateSpace, LayerClip
from qpane.scene.raster import RasterBounds
from qpane_test_support.render_plan import make_render_plan


def test_scene_clip_preserves_interior_pixels_after_nonuniform_rotation() -> None:
    """A scene aperture must not become an axis-aligned source crop."""
    plan = make_render_plan(QRect(0, 0, 512, 512))
    item = plan.render_items[0]
    transform = LayerTransform(
        1.512726,
        1.308304,
        -0.327076,
        0.378182,
        -53.904478,
        -178.115735,
    )
    bounds = RasterBounds(0, 0, 512, 512)
    placement = transform.map_bounds(bounds)
    clip = LayerClip(
        coordinate_space=ClipCoordinateSpace.SCENE,
        x=0.0,
        y=0.0,
        width=512.0,
        height=512.0,
    )
    descriptor = replace(
        item.descriptor,
        placement=placement,
        raster_bounds=bounds,
        transform=transform,
        clip=clip,
    )
    transformed_item = replace(
        item,
        descriptor=descriptor,
        transform=transform.to_qtransform(),
        placement=placement,
        clip=clip,
    )
    transformed_plan = replace(plan, render_items=(transformed_item,))

    path = source_clip_path(transformed_plan, transformed_item)

    assert path is not None
    assert path.contains(QPointF(256.0, 50.0))
    assert path.contains(QPointF(256.0, 400.0))
    assert not path.contains(QPointF(0.0, 0.0))
