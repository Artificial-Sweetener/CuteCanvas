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
"""Exact geometry tests for affine transform gestures."""

from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QPointF

from qpane.scene.affine import LayerTransform
from qpane.scene.projective import ProjectiveLayerTransform
from qpane.scene.transform_geometry import (
    AffineTransformGeometry,
    TransformHandle,
    TransformLocalBounds,
    TransformModifiers,
    TransformOperation,
    TransformOperationKind,
)


def _assert_point(actual: QPointF, expected: QPointF) -> None:
    """Assert two floating points are geometrically equivalent."""
    assert actual.x() == pytest.approx(expected.x())
    assert actual.y() == pytest.approx(expected.y())


def test_proportional_corner_scale_preserves_opposite_rotated_anchor() -> None:
    """Corner scaling must preserve local aspect and the opposite scene point."""
    initial = LayerTransform(0.8, 0.6, -0.6, 0.8, 200.0, 100.0)
    geometry = AffineTransformGeometry(
        TransformLocalBounds(10.0, 20.0, 100.0, 60.0),
        initial,
    )
    handle = TransformHandle.TOP_LEFT
    origin = geometry.scene_point(handle)
    anchor_local = geometry.bounds.opposite(handle)
    anchor_scene = initial.map_point(anchor_local)
    pointer = anchor_scene + (origin - anchor_scene) * 1.75

    transformed = geometry.transform_for_drag(
        TransformOperation(TransformOperationKind.SCALE, handle),
        origin,
        pointer,
        TransformModifiers(proportional=True),
    )

    assert transformed is not None
    _assert_point(transformed.map_point(anchor_local), anchor_scene)
    _assert_point(transformed.map_point(geometry.bounds.point(handle)), pointer)


def test_side_scale_changes_only_local_axis_under_shear() -> None:
    """A side handle must preserve the orthogonal local dimension and anchor."""
    initial = LayerTransform(1.0, 0.2, 0.35, 0.9, 40.0, -20.0)
    geometry = AffineTransformGeometry(
        TransformLocalBounds(0.0, 0.0, 200.0, 100.0),
        initial,
    )
    handle = TransformHandle.RIGHT
    origin = geometry.scene_point(handle)
    local_delta = initial.map_vector(QPointF(100.0, 0.0))
    anchor = geometry.bounds.opposite(handle)

    transformed = geometry.transform_for_drag(
        TransformOperation(TransformOperationKind.SCALE, handle),
        origin,
        origin + local_delta,
        TransformModifiers(proportional=False),
    )

    assert transformed is not None
    _assert_point(transformed.map_point(anchor), initial.map_point(anchor))
    assert transformed.map_vector(QPointF(0.0, 100.0)) == initial.map_vector(
        QPointF(0.0, 100.0)
    )
    _assert_point(
        transformed.map_point(geometry.bounds.point(handle)),
        origin + local_delta,
    )


def test_alt_corner_scale_preserves_center_reference() -> None:
    """Center-based scaling must move opposite edges symmetrically."""
    geometry = AffineTransformGeometry(
        TransformLocalBounds(0.0, 0.0, 80.0, 40.0),
        LayerTransform(dx=12.0, dy=9.0),
    )
    handle = TransformHandle.BOTTOM_RIGHT
    origin = geometry.scene_point(handle)
    center = geometry.scene_center()

    transformed = geometry.transform_for_drag(
        TransformOperation(TransformOperationKind.SCALE, handle),
        origin,
        center + (origin - center) * 2.0,
        TransformModifiers(proportional=True, about_center=True),
    )

    assert transformed is not None
    _assert_point(transformed.map_point(geometry.bounds.center), center)
    _assert_point(
        transformed.map_point(geometry.bounds.point(TransformHandle.TOP_LEFT)),
        center + (geometry.scene_point(TransformHandle.TOP_LEFT) - center) * 2.0,
    )


def test_rotation_shift_snaps_delta_to_fifteen_degrees() -> None:
    """Shift rotation must snap the gesture delta to a 15-degree grid."""
    geometry = AffineTransformGeometry(
        TransformLocalBounds(0.0, 0.0, 100.0, 100.0),
        LayerTransform(),
    )
    center = geometry.scene_center()
    origin = center + QPointF(100.0, 0.0)
    radians = math.radians(22.0)
    pointer = center + QPointF(math.cos(radians) * 100.0, math.sin(radians) * 100.0)

    transformed = geometry.transform_for_drag(
        TransformOperation(TransformOperationKind.ROTATE),
        origin,
        pointer,
        TransformModifiers(snap_rotation=True),
    )

    assert transformed is not None
    assert math.degrees(math.atan2(transformed.m12, transformed.m11)) == pytest.approx(
        15.0
    )
    _assert_point(transformed.map_point(geometry.bounds.center), center)


def test_side_skew_preserves_opposite_edge() -> None:
    """A side-skew gesture must keep its opposite edge fixed."""
    geometry = AffineTransformGeometry(
        TransformLocalBounds(0.0, 0.0, 120.0, 80.0),
        LayerTransform(dx=50.0, dy=30.0),
    )
    handle = TransformHandle.TOP
    origin = geometry.scene_point(handle)

    transformed = geometry.transform_for_drag(
        TransformOperation(TransformOperationKind.SKEW, handle),
        origin,
        origin + QPointF(30.0, 0.0),
        TransformModifiers(proportional=False),
    )

    assert transformed is not None
    _assert_point(
        transformed.map_point(QPointF(0.0, 80.0)),
        QPointF(50.0, 110.0),
    )
    _assert_point(
        transformed.map_point(QPointF(120.0, 80.0)),
        QPointF(170.0, 110.0),
    )
    _assert_point(
        transformed.map_point(geometry.bounds.point(handle)),
        origin + QPointF(30.0, 0.0),
    )


def test_scale_refuses_the_singular_crossing_sample() -> None:
    """The one zero-area pointer sample must not publish singular geometry."""
    geometry = AffineTransformGeometry(
        TransformLocalBounds(0.0, 0.0, 100.0, 100.0),
        LayerTransform(),
    )
    handle = TransformHandle.BOTTOM_RIGHT
    origin = geometry.scene_point(handle)

    transformed = geometry.transform_for_drag(
        TransformOperation(TransformOperationKind.SCALE, handle),
        origin,
        QPointF(0.0, 0.0),
        TransformModifiers(proportional=False),
    )

    assert transformed is None


def test_affine_gesture_composes_over_projective_layer_mapping() -> None:
    """Ordinary move and scale remain available after a projective edit."""
    initial = ProjectiveLayerTransform.from_quadrilaterals(
        (
            QPointF(0.0, 0.0),
            QPointF(100.0, 0.0),
            QPointF(100.0, 80.0),
            QPointF(0.0, 80.0),
        ),
        (
            QPointF(0.0, 0.0),
            QPointF(110.0, 10.0),
            QPointF(100.0, 80.0),
            QPointF(0.0, 80.0),
        ),
    )
    geometry = AffineTransformGeometry(
        TransformLocalBounds(0.0, 0.0, 100.0, 80.0),
        initial,
    )
    move_delta = QPointF(13.0, -7.0)

    moved = geometry.transform_for_drag(
        TransformOperation(TransformOperationKind.MOVE),
        QPointF(20.0, 20.0),
        QPointF(20.0, 20.0) + move_delta,
        TransformModifiers(),
    )

    assert moved is not None
    for corner in (
        QPointF(0.0, 0.0),
        QPointF(100.0, 0.0),
        QPointF(100.0, 80.0),
        QPointF(0.0, 80.0),
    ):
        _assert_point(moved.map_point(corner), initial.map_point(corner) + move_delta)

    handle = TransformHandle.TOP_RIGHT
    origin = geometry.scene_point(handle)
    anchor = geometry.bounds.opposite(handle)
    anchor_scene = initial.map_point(anchor)
    scaled = geometry.transform_for_drag(
        TransformOperation(TransformOperationKind.SCALE, handle),
        origin,
        anchor_scene + (origin - anchor_scene) * 1.2,
        TransformModifiers(proportional=True),
    )
    assert scaled is not None
    _assert_point(scaled.map_point(anchor), anchor_scene)


@pytest.mark.parametrize("handle", tuple(TransformHandle))
def test_every_transform_handle_moves_and_preserves_its_opposite_anchor(
    handle: TransformHandle,
) -> None:
    """All eight visible circles must be live affine edit points."""
    geometry = AffineTransformGeometry(
        TransformLocalBounds(10.0, 20.0, 120.0, 80.0),
        LayerTransform(0.9, 0.25, -0.15, 1.1, 30.0, 40.0),
    )
    origin = geometry.scene_point(handle)
    center = geometry.scene_center()
    pointer = center + (origin - center) * 1.25
    anchor = geometry.bounds.opposite(handle)

    transformed = geometry.transform_for_drag(
        TransformOperation(TransformOperationKind.SCALE, handle),
        origin,
        pointer,
        TransformModifiers(proportional=False),
    )

    assert transformed is not None
    _assert_point(
        transformed.map_point(anchor), geometry.initial_transform.map_point(anchor)
    )
    _assert_point(transformed.map_point(geometry.bounds.point(handle)), pointer)


@pytest.mark.parametrize(
    "handle",
    (
        TransformHandle.TOP,
        TransformHandle.RIGHT,
        TransformHandle.BOTTOM,
        TransformHandle.LEFT,
    ),
)
def test_every_side_handle_supports_affine_skew(handle: TransformHandle) -> None:
    """Ctrl+Shift side gestures must work on every side of the box."""
    geometry = AffineTransformGeometry(
        TransformLocalBounds(0.0, 0.0, 100.0, 60.0),
        LayerTransform(dx=20.0, dy=15.0),
    )
    origin = geometry.scene_point(handle)
    delta = (
        QPointF(18.0, 0.0)
        if handle in {TransformHandle.TOP, TransformHandle.BOTTOM}
        else QPointF(0.0, 18.0)
    )

    transformed = geometry.transform_for_drag(
        TransformOperation(TransformOperationKind.SKEW, handle),
        origin,
        origin + delta,
        TransformModifiers(proportional=False),
    )

    assert transformed is not None
    _assert_point(
        transformed.map_point(geometry.bounds.opposite(handle)),
        geometry.initial_transform.map_point(geometry.bounds.opposite(handle)),
    )
