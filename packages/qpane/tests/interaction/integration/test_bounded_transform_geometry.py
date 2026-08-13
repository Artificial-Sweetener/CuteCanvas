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

"""Affine-gesture contracts for finite bounded layer mappings."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF

from qpane.scene.bilinear import BilinearLayerTransform
from qpane.scene.piecewise import PiecewiseLayerTransform
from qpane.scene.transform_geometry import (
    AffineTransformGeometry,
    TransformHandle,
    TransformLocalBounds,
    TransformModifiers,
    TransformOperation,
    TransformOperationKind,
)

_SOURCE = (
    QPointF(0.0, 0.0),
    QPointF(100.0, 0.0),
    QPointF(100.0, 80.0),
    QPointF(0.0, 80.0),
)


def test_bounded_mapping_uses_its_scene_bounding_box_as_the_affine_frame() -> None:
    """Polygon topology must not become affine transform-box geometry."""
    geometry = _geometry()

    expected = {
        TransformHandle.TOP_LEFT: QPointF(0.0, 5.0),
        TransformHandle.TOP: QPointF(60.0, 5.0),
        TransformHandle.TOP_RIGHT: QPointF(120.0, 5.0),
        TransformHandle.RIGHT: QPointF(120.0, 47.5),
        TransformHandle.BOTTOM_RIGHT: QPointF(120.0, 90.0),
        TransformHandle.BOTTOM: QPointF(60.0, 90.0),
        TransformHandle.BOTTOM_LEFT: QPointF(0.0, 90.0),
        TransformHandle.LEFT: QPointF(0.0, 47.5),
    }

    for handle, point in expected.items():
        _assert_point(geometry.scene_point(handle), point)
    _assert_point(geometry.scene_center(), QPointF(60.0, 47.5))


def test_vectorized_polygon_vertices_do_not_become_affine_handles() -> None:
    """A detailed vector cage still presents one ordinary eight-handle box."""
    mapping = PiecewiseLayerTransform(
        (
            QPointF(10.0, 0.0),
            QPointF(60.0, 0.0),
            QPointF(100.0, 10.0),
            QPointF(100.0, 60.0),
            QPointF(90.0, 80.0),
            QPointF(30.0, 80.0),
            QPointF(0.0, 60.0),
            QPointF(0.0, 20.0),
        ),
        (
            QPointF(20.0, 10.0),
            QPointF(70.0, 5.0),
            QPointF(120.0, 20.0),
            QPointF(125.0, 70.0),
            QPointF(105.0, 100.0),
            QPointF(35.0, 95.0),
            QPointF(-10.0, 75.0),
            QPointF(-5.0, 25.0),
        ),
    )
    geometry = AffineTransformGeometry(
        TransformLocalBounds(0.0, 0.0, 100.0, 80.0),
        mapping,
    )

    points = {handle: geometry.scene_point(handle) for handle in TransformHandle}

    assert len(points) == 8
    _assert_point(points[TransformHandle.TOP_LEFT], QPointF(-10.0, 5.0))
    _assert_point(points[TransformHandle.TOP_RIGHT], QPointF(125.0, 5.0))
    _assert_point(points[TransformHandle.BOTTOM_RIGHT], QPointF(125.0, 100.0))
    _assert_point(points[TransformHandle.BOTTOM_LEFT], QPointF(-10.0, 100.0))
    assert not any(point in mapping.target_boundary for point in points.values())


@pytest.mark.parametrize("factor", (0.8, 1.2))
def test_scale_preserves_a_bounded_mapping_source_cage(factor: float) -> None:
    """Scaling mapped content transforms its target without moving its source."""
    geometry = _geometry()
    handle = TransformHandle.BOTTOM_RIGHT
    origin = geometry.scene_point(handle)
    anchor_scene = geometry.scene_point(TransformHandle.TOP_LEFT)
    pointer = anchor_scene + (origin - anchor_scene) * factor

    scaled = geometry.transform_for_drag(
        TransformOperation(TransformOperationKind.SCALE, handle),
        origin,
        pointer,
        TransformModifiers(proportional=True),
    )

    assert isinstance(scaled, PiecewiseLayerTransform)
    assert scaled.source_boundary == _SOURCE
    result = AffineTransformGeometry(geometry.bounds, scaled)
    _assert_point(result.scene_point(TransformHandle.TOP_LEFT), anchor_scene)
    _assert_point(result.scene_point(handle), pointer)


def test_skew_preserves_a_bounded_mapping_source_cage() -> None:
    """Skewing mapped content leaves its finite raster admission cage unchanged."""
    geometry = _geometry()
    initial = geometry.initial_transform
    assert isinstance(initial, PiecewiseLayerTransform)
    handle = TransformHandle.TOP
    origin = geometry.scene_point(handle)
    fixed_points = _opposite_edge_points(initial.target_boundary, handle)

    skewed = geometry.transform_for_drag(
        TransformOperation(TransformOperationKind.SKEW, handle),
        origin,
        origin + QPointF(20.0, 0.0),
        TransformModifiers(),
    )

    assert isinstance(skewed, PiecewiseLayerTransform)
    assert skewed.source_boundary == _SOURCE
    assert all(point in skewed.target_boundary for point in fixed_points)


def test_nonproportional_scale_keeps_the_bounded_handle_under_the_pointer() -> None:
    """Independent bounded-axis scaling retains exact direct manipulation."""
    geometry = _geometry()
    handle = TransformHandle.BOTTOM_RIGHT
    origin = geometry.scene_point(handle)
    anchor_scene = geometry.scene_point(TransformHandle.TOP_LEFT)
    pointer = QPointF(
        anchor_scene.x() + (origin.x() - anchor_scene.x()) * 0.8,
        anchor_scene.y() + (origin.y() - anchor_scene.y()) * 0.7,
    )

    scaled = geometry.transform_for_drag(
        TransformOperation(TransformOperationKind.SCALE, handle),
        origin,
        pointer,
        TransformModifiers(proportional=False),
    )

    assert isinstance(scaled, PiecewiseLayerTransform)
    assert scaled.source_boundary == _SOURCE
    result = AffineTransformGeometry(geometry.bounds, scaled)
    _assert_point(result.scene_point(handle), pointer)


def test_bounded_scale_pointer_storm_never_escapes_the_source_cage() -> None:
    """Extreme pointer samples either stay admissible or publish no mapping."""
    geometry = _geometry()
    handle = TransformHandle.BOTTOM_RIGHT
    origin = geometry.scene_point(handle)

    for x in range(-200, 301, 50):
        for y in range(-200, 301, 50):
            candidate = geometry.transform_for_drag(
                TransformOperation(TransformOperationKind.SCALE, handle),
                origin,
                QPointF(float(x), float(y)),
                TransformModifiers(proportional=False),
            )
            if isinstance(candidate, PiecewiseLayerTransform):
                assert candidate.source_boundary == _SOURCE


def test_cached_collapsed_edge_supports_every_affine_scale_handle() -> None:
    """A valid triangular target remains affine-transformable at every handle."""
    geometry = _cached_triangular_geometry()
    initial = geometry.initial_transform
    assert isinstance(initial, BilinearLayerTransform)

    for handle in TransformHandle:
        origin = geometry.scene_point(handle)
        pointer = origin + QPointF(24.0, 18.0)
        opposite = _OPPOSITE_HANDLE[handle]
        anchor_scene = geometry.scene_point(opposite)
        transformed = geometry.transform_for_drag(
            TransformOperation(TransformOperationKind.SCALE, handle),
            origin,
            pointer,
            TransformModifiers(proportional=False),
        )

        assert isinstance(transformed, BilinearLayerTransform), handle
        assert transformed.source_boundary == initial.source_boundary
        result = AffineTransformGeometry(geometry.bounds, transformed)
        expected = QPointF(
            (
                pointer.x()
                if handle not in {TransformHandle.TOP, TransformHandle.BOTTOM}
                else origin.x()
            ),
            (
                pointer.y()
                if handle not in {TransformHandle.LEFT, TransformHandle.RIGHT}
                else origin.y()
            ),
        )
        _assert_point(result.scene_point(handle), expected)
        _assert_point(result.scene_point(opposite), anchor_scene)


def test_cached_collapsed_edge_supports_every_affine_skew_handle() -> None:
    """Joined-edge singularities do not disable side-handle affine skewing."""
    geometry = _cached_triangular_geometry()
    initial = geometry.initial_transform
    assert isinstance(initial, BilinearLayerTransform)

    for handle in (
        TransformHandle.TOP,
        TransformHandle.RIGHT,
        TransformHandle.BOTTOM,
        TransformHandle.LEFT,
    ):
        origin = geometry.scene_point(handle)
        delta = (
            QPointF(24.0, 0.0)
            if handle in {TransformHandle.TOP, TransformHandle.BOTTOM}
            else QPointF(0.0, 18.0)
        )
        transformed = geometry.transform_for_drag(
            TransformOperation(TransformOperationKind.SKEW, handle),
            origin,
            origin + delta,
            TransformModifiers(),
        )

        assert isinstance(transformed, BilinearLayerTransform), handle
        assert transformed.source_boundary == initial.source_boundary
        fixed_points = _opposite_edge_points(initial.target_boundary, handle)
        assert all(point in transformed.target_boundary for point in fixed_points)


def _geometry() -> AffineTransformGeometry:
    """Return one deliberately non-affine bounded transform box."""
    initial = PiecewiseLayerTransform(
        _SOURCE,
        (
            QPointF(10.0, 5.0),
            QPointF(120.0, 10.0),
            QPointF(100.0, 90.0),
            QPointF(0.0, 80.0),
        ),
    )
    return AffineTransformGeometry(
        TransformLocalBounds(0.0, 0.0, 100.0, 80.0),
        initial,
    )


def _cached_triangular_geometry() -> AffineTransformGeometry:
    """Return the exact collapsed-edge topology observed in SugarSubstitute."""
    initial = BilinearLayerTransform(
        (
            QPointF(480.00000000000017, 1344.0),
            QPointF(0.0, 1343.9999999999998),
            QPointF(0.0, 0.0),
            QPointF(479.9999999999999, 0.0),
        ),
        (
            QPointF(0.0, 1344.0),
            QPointF(0.0, 1344.0),
            QPointF(0.0, 0.0),
            QPointF(960.0, 0.0),
        ),
    )
    return AffineTransformGeometry(
        TransformLocalBounds(0.0, 0.0, 480.0, 1344.0),
        initial,
    )


def _assert_point(actual: QPointF, expected: QPointF) -> None:
    """Assert two floating points are geometrically equivalent."""
    assert actual.x() == pytest.approx(expected.x())
    assert actual.y() == pytest.approx(expected.y())


_OPPOSITE_HANDLE = {
    TransformHandle.TOP_LEFT: TransformHandle.BOTTOM_RIGHT,
    TransformHandle.TOP: TransformHandle.BOTTOM,
    TransformHandle.TOP_RIGHT: TransformHandle.BOTTOM_LEFT,
    TransformHandle.RIGHT: TransformHandle.LEFT,
    TransformHandle.BOTTOM_RIGHT: TransformHandle.TOP_LEFT,
    TransformHandle.BOTTOM: TransformHandle.TOP,
    TransformHandle.BOTTOM_LEFT: TransformHandle.TOP_RIGHT,
    TransformHandle.LEFT: TransformHandle.RIGHT,
}


def _opposite_edge_points(
    boundary: tuple[QPointF, ...],
    handle: TransformHandle,
) -> tuple[QPointF, ...]:
    """Return actual topology points lying on a side handle's fixed box edge."""
    if handle is TransformHandle.TOP:
        value = max(point.y() for point in boundary)
        return tuple(point for point in boundary if point.y() == value)
    if handle is TransformHandle.BOTTOM:
        value = min(point.y() for point in boundary)
        return tuple(point for point in boundary if point.y() == value)
    if handle is TransformHandle.LEFT:
        value = max(point.x() for point in boundary)
        return tuple(point for point in boundary if point.x() == value)
    value = min(point.x() for point in boundary)
    return tuple(point for point in boundary if point.x() == value)
