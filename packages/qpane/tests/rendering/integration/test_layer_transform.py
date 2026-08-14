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
"""Characterization tests for authoritative layer-local transforms."""

from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QPointF, QRect
from PySide6.QtGui import QTransform

from qpane.scene.affine import LayerTransform
from qpane.scene.model import LayerPlacement
from qpane.scene.raster import RasterBounds


def test_transform_from_placement_preserves_rectangular_mapping() -> None:
    """Rectangular placement maps every local bound edge exactly."""
    bounds = RasterBounds(-4, 6, 20, 10)
    placement = LayerPlacement(12.5, -7.0, 80.0, 25.0)

    transform = LayerTransform.from_placement(bounds, placement)

    assert transform.map_point(QPointF(-4.0, 6.0)) == QPointF(12.5, -7.0)
    assert transform.map_point(QPointF(16.0, 16.0)) == QPointF(92.5, 18.0)
    assert transform.map_bounds(bounds) == placement


def test_transform_translation_is_applied_in_scene_space() -> None:
    """Scene translation changes no local scale or mapped dimensions."""
    original = LayerTransform(
        m11=2.0,
        m22=3.0,
        dx=4.0,
        dy=-8.0,
    )

    moved = original.translated(-6.0, 11.0)

    assert moved.map_point(QPointF(5.0, 7.0)) == QPointF(8.0, 24.0)
    assert moved.map_rect(QRect(1, 2, 4, 5)).size().toSize().width() == 8
    assert moved.map_rect(QRect(1, 2, 4, 5)).size().toSize().height() == 15


def test_transform_inverse_round_trips_axis_aligned_points() -> None:
    """An invertible transform maps scene points back to exact local points."""
    transform = LayerTransform(m11=0.5, m22=4.0, dx=17.0, dy=-9.0)
    local = QPointF(-12.0, 3.25)

    scene = transform.map_point(local)

    assert transform.inverse_map(scene) == local


def test_transform_inverse_rejects_degenerate_axis() -> None:
    """Collapsed placements cannot be inverse-mapped into local space."""
    transform = LayerTransform(m11=0.0, m22=1.0)

    assert transform.inverse_map(QPointF(4.0, 5.0)) is None


def test_transform_maps_rotated_bounds_to_conservative_placement() -> None:
    """Derived placement encloses all corners without replacing rotation."""
    transform = LayerTransform(m11=0.0, m12=1.0, m21=-1.0, m22=0.0, dx=7.0)

    placement = transform.map_bounds(RasterBounds(0, 0, 20, 10))

    assert placement.x == pytest.approx(-3.0)
    assert placement.y == pytest.approx(0.0)
    assert placement.width == pytest.approx(10.0)
    assert placement.height == pytest.approx(20.0)
    assert transform.map_point(QPointF(20.0, 10.0)) == QPointF(-3.0, 20.0)


def test_transform_inverse_round_trips_shear_and_reflection() -> None:
    """General affine inverse mapping preserves points and vectors."""
    transform = LayerTransform(
        m11=-1.5,
        m12=0.25,
        m21=0.5,
        m22=2.0,
        dx=18.0,
        dy=-6.0,
    )
    local_point = QPointF(13.5, -4.25)
    local_vector = QPointF(-2.0, 7.0)

    inverse = transform.inverted()

    assert inverse is not None
    restored_point = inverse.map_point(transform.map_point(local_point))
    restored_vector = transform.inverse_map_vector(transform.map_vector(local_vector))
    assert restored_point.x() == pytest.approx(local_point.x())
    assert restored_point.y() == pytest.approx(local_point.y())
    assert restored_vector is not None
    assert restored_vector.x() == pytest.approx(local_vector.x())
    assert restored_vector.y() == pytest.approx(local_vector.y())


def test_transform_detaches_from_qt_affine_value() -> None:
    """Qt conversion preserves all six coefficients without shared state."""
    qt_transform = QTransform()
    qt_transform.translate(11.0, -3.0)
    qt_transform.rotate(37.0)
    qt_transform.shear(0.2, -0.1)

    transform = LayerTransform.from_qtransform(qt_transform)
    round_tripped = transform.to_qtransform()

    assert round_tripped.m11() == pytest.approx(qt_transform.m11())
    assert round_tripped.m12() == pytest.approx(qt_transform.m12())
    assert round_tripped.m21() == pytest.approx(qt_transform.m21())
    assert round_tripped.m22() == pytest.approx(qt_transform.m22())
    assert round_tripped.dx() == pytest.approx(qt_transform.dx())
    assert round_tripped.dy() == pytest.approx(qt_transform.dy())
    assert math.isfinite(transform.determinant)
