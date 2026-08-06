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
"""Typed QPane scene-coordinate projection contracts."""

from __future__ import annotations

import uuid

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QTransform
from qpane.sdk.rendering import (
    LayerCoordinateProjection,
    LayerLocalPoint,
    LayerSourcePoint,
    PanelPoint,
    SceneCoordinateProjection,
    SceneCoordinateSystem,
    ScenePoint,
)
from qpane.sdk.scene import LayerTransform


def test_layer_projection_round_trips_affine_nonzero_source_origin() -> None:
    """Every supported coordinate route must agree under full affine geometry."""
    scene_id = uuid.uuid4()
    layer_id = uuid.uuid4()
    scene_transform = QTransform()
    scene_transform.translate(140.0, -35.0)
    scene_transform.rotate(17.0)
    scene_transform.scale(1.75, 0.65)
    scene = SceneCoordinateProjection(scene_id, scene_transform)
    layer = LayerCoordinateProjection(
        scene,
        layer_id,
        LayerTransform(
            m11=1.2,
            m12=0.35,
            m21=-0.25,
            m22=0.9,
            dx=31.0,
            dy=-47.0,
        ),
        QPointF(-19.0, 23.0),
    )
    source = LayerSourcePoint(scene_id, layer_id, 82.25, -14.5)
    local = LayerLocalPoint(scene_id, layer_id, 63.25, 8.5)

    scene_point = layer.source_to_scene(source)
    panel_point = layer.source_to_panel(source)

    assert layer.source_to_local(source) == local
    assert layer.local_to_source(local) == source
    assert scene_point is not None
    assert panel_point is not None
    source_round_trip = layer.scene_to_source(scene_point)
    panel_source_round_trip = layer.panel_to_source(panel_point)
    panel_round_trip = scene.scene_to_panel(scene_point)
    scene_round_trip = scene.panel_to_scene(panel_point)
    assert source_round_trip is not None
    assert panel_source_round_trip is not None
    assert panel_round_trip is not None
    assert scene_round_trip is not None
    assert (source_round_trip.x, source_round_trip.y) == pytest.approx(
        (source.x, source.y)
    )
    assert (
        panel_source_round_trip.x,
        panel_source_round_trip.y,
    ) == pytest.approx((source.x, source.y))
    assert (panel_round_trip.x, panel_round_trip.y) == pytest.approx(
        (panel_point.x, panel_point.y)
    )
    assert (scene_round_trip.x, scene_round_trip.y) == pytest.approx(
        (scene_point.x, scene_point.y)
    )


def test_coordinate_system_rejects_points_from_other_domains_and_identities() -> None:
    """Typed points must make mixed spaces and stale identities non-operational."""
    scene_id = uuid.uuid4()
    layer_id = uuid.uuid4()
    scene = SceneCoordinateProjection(scene_id, QTransform())
    layer = LayerCoordinateProjection(
        scene,
        layer_id,
        LayerTransform(),
        QPointF(),
    )
    coordinates = SceneCoordinateSystem(
        scene_projection=lambda: scene,
        layer_projection=(
            lambda requested_scene, requested_layer: (
                layer
                if requested_scene == scene_id and requested_layer == layer_id
                else None
            )
        ),
    )

    with pytest.raises(TypeError):
        coordinates.panel_to_scene(ScenePoint(scene_id, 1.0, 2.0))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        coordinates.scene_to_panel(PanelPoint(1.0, 2.0))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        coordinates.layer_source_to_scene(
            ScenePoint(scene_id, 1.0, 2.0)  # type: ignore[arg-type]
        )

    assert coordinates.scene_to_panel(ScenePoint(uuid.uuid4(), 1.0, 2.0)) is None
    assert (
        coordinates.layer_source_to_scene(
            LayerSourcePoint(scene_id, uuid.uuid4(), 1.0, 2.0)
        )
        is None
    )


def test_coordinate_values_copy_qt_points_and_reject_nonfinite_components() -> None:
    """Public coordinate values must detach Qt inputs and remain numerically valid."""
    scene_id = uuid.uuid4()
    layer_id = uuid.uuid4()
    qt_point = QPointF(4.5, -7.25)

    panel = PanelPoint.from_qt(qt_point)
    scene = ScenePoint.from_qt(scene_id, qt_point)
    source = LayerSourcePoint.from_qt(scene_id, layer_id, qt_point)
    qt_point.setX(100.0)

    assert panel.to_qt() == QPointF(4.5, -7.25)
    assert scene.to_qt() == QPointF(4.5, -7.25)
    assert source.to_qt() == QPointF(4.5, -7.25)
    with pytest.raises(ValueError):
        PanelPoint(float("nan"), 0.0)
