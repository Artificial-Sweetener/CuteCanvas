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
"""Tests for active-raster instance coordinate projection."""

from __future__ import annotations

import uuid

import pytest
from cutecanvas.resources.active_raster import ActiveRasterSnapshot
from cutecanvas.resources.active_raster_coordinates import (
    ActiveRasterCoordinateProjection,
)
from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QTransform
from qpane import LayerSourcePoint
from qpane.sdk.rendering import (
    LayerCoordinateProjection,
    SceneCoordinateProjection,
    SceneCoordinateSystem,
)
from qpane.sdk.scene import LayerTransform


def test_active_raster_projection_honors_affine_layer_and_view_geometry() -> None:
    """Smart Select prompts must round-trip through the raster layer instance."""
    scene_id = uuid.uuid4()
    layer_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    scene_transform = QTransform()
    scene_transform.translate(140.0, -35.0)
    scene_transform.scale(1.75, 0.65)
    scene = SceneCoordinateProjection(scene_id, scene_transform)
    layer = LayerCoordinateProjection(
        scene,
        layer_id,
        LayerTransform(m11=1.2, m22=0.9, dx=31.0, dy=-47.0),
        QPointF(-19.0, 23.0),
    )
    coordinates = SceneCoordinateSystem(
        scene_projection=lambda: scene,
        layer_projection=lambda requested_scene, requested_layer: (
            layer
            if requested_scene == scene_id and requested_layer == layer_id
            else None
        ),
    )
    image = QImage(128, 96, QImage.Format.Format_ARGB32)
    snapshot = ActiveRasterSnapshot(
        scene_id,
        layer_id,
        resource_id,
        image,
        None,
    )
    projection = ActiveRasterCoordinateProjection(snapshot, coordinates)
    expected_source = LayerSourcePoint(scene_id, layer_id, 82.25, 14.5)
    expected_panel = layer.source_to_panel(expected_source)
    assert expected_panel is not None

    actual_source = projection.panel_to_source(expected_panel.to_qt())
    actual_panel = projection.source_to_panel(expected_source.to_qt())

    assert actual_source is not None
    assert actual_panel is not None
    assert (actual_source.x(), actual_source.y()) == pytest.approx(
        (
            expected_source.x,
            expected_source.y,
        )
    )
    assert (actual_panel.x(), actual_panel.y()) == pytest.approx(
        (
            expected_panel.x,
            expected_panel.y,
        )
    )
