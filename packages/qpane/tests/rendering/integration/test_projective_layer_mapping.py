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

"""Canonical geometry proof for projective scene-layer mappings."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPolygonF, QTransform

from qpane.rendering.projective_sampling import conservative_transform_scale
from qpane.rendering.projective_visibility import visible_source_rect
from qpane.rendering.render_tile_geometry import scale_bucket
from qpane.scene.affine import LayerTransform
from qpane.scene.mapping import (
    compose_layer_mappings,
    layer_mapping_from_qtransform,
    mapped_layer_quad,
    validate_layer_mapping,
)
from qpane.scene.projective import ProjectiveLayerTransform
from qpane.scene.raster import RasterBounds


def test_projective_mapping_uses_homogeneous_division() -> None:
    """Point mapping divides both numerators by the projective denominator."""
    mapping = ProjectiveLayerTransform(
        m11=2.0,
        m22=3.0,
        m23=0.01,
        m33=1.0,
    )

    mapped = mapping.map_point(QPointF(4.0, 20.0))

    assert mapped.x() == pytest.approx(8.0 / 1.2)
    assert mapped.y() == pytest.approx(60.0 / 1.2)


def test_projective_mapping_round_trips_through_qt() -> None:
    """The immutable value preserves all nine detached Qt coefficients."""
    source = QTransform(1.2, 0.1, 0.002, -0.3, 0.9, -0.001, 14.0, -8.0, 1.0)

    mapping = ProjectiveLayerTransform.from_qtransform(source)
    restored = mapping.to_qtransform()

    assert (
        restored.m11(),
        restored.m12(),
        restored.m13(),
        restored.m21(),
        restored.m22(),
        restored.m23(),
        restored.m31(),
        restored.m32(),
        restored.m33(),
    ) == pytest.approx(
        (
            source.m11(),
            source.m12(),
            source.m13(),
            source.m21(),
            source.m22(),
            source.m23(),
            source.m31(),
            source.m32(),
            source.m33(),
        )
    )


def test_projective_inverse_round_trips_points() -> None:
    """An invertible homography restores finite points exactly enough for input."""
    mapping = ProjectiveLayerTransform(
        m11=1.2,
        m12=0.1,
        m13=0.002,
        m21=-0.3,
        m22=0.9,
        m23=-0.001,
        dx=14.0,
        dy=-8.0,
    )
    local = QPointF(37.5, -12.25)

    inverse = mapping.inverted()

    assert inverse is not None
    restored = inverse.map_point(mapping.map_point(local))
    assert restored.x() == pytest.approx(local.x())
    assert restored.y() == pytest.approx(local.y())


def test_projective_mapping_solves_exact_quadrilateral_correspondence() -> None:
    """Four source corners map to the independently specified target quad."""
    source = (
        QPointF(0.0, 0.0),
        QPointF(100.0, 0.0),
        QPointF(100.0, 100.0),
        QPointF(0.0, 100.0),
    )
    target = (
        QPointF(0.0, 0.0),
        QPointF(120.0, 10.0),
        QPointF(100.0, 100.0),
        QPointF(0.0, 100.0),
    )
    assert (
        QTransform.quadToQuad(QPolygonF(source), QPolygonF(target)).isAffine() is False
    )

    mapping = ProjectiveLayerTransform.from_quadrilaterals(source, target)

    for source_point, target_point in zip(source, target):
        mapped = mapping.map_point(source_point)
        assert mapped.x() == pytest.approx(target_point.x())
        assert mapped.y() == pytest.approx(target_point.y())


def test_mapping_factory_preserves_explicit_affine_ownership() -> None:
    """Qt values enter the narrow affine type unless perspective is present."""
    affine = layer_mapping_from_qtransform(QTransform.fromScale(2.0, 3.0))
    projective = layer_mapping_from_qtransform(
        QTransform(1.0, 0.0, 0.001, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    )

    assert isinstance(affine, LayerTransform)
    assert isinstance(projective, ProjectiveLayerTransform)


def test_mapping_composition_applies_affine_after_projective() -> None:
    """Common composition keeps operation order without affine assumptions."""
    projective = ProjectiveLayerTransform(m13=0.01)
    translation = LayerTransform(dx=7.0, dy=-4.0)
    point = QPointF(20.0, 10.0)

    composed = compose_layer_mappings(projective, translation)

    expected = translation.map_point(projective.map_point(point))
    actual = composed.map_point(point)
    assert actual.x() == pytest.approx(expected.x())
    assert actual.y() == pytest.approx(expected.y())


def test_mapping_validation_accepts_finite_convex_trapezoid() -> None:
    """A horizon-free target quadrilateral is admitted for scene use."""
    bounds = RasterBounds(0, 0, 100, 100)
    target = (
        QPointF(0.0, 0.0),
        QPointF(120.0, 10.0),
        QPointF(100.0, 100.0),
        QPointF(0.0, 100.0),
    )
    mapping = ProjectiveLayerTransform.from_quadrilaterals(
        (
            QPointF(0.0, 0.0),
            QPointF(100.0, 0.0),
            QPointF(100.0, 100.0),
            QPointF(0.0, 100.0),
        ),
        target,
    )

    validate_layer_mapping(mapping, bounds)

    actual = mapped_layer_quad(mapping, bounds)
    for actual_point, target_point in zip(actual, target):
        assert actual_point.x() == pytest.approx(target_point.x())
        assert actual_point.y() == pytest.approx(target_point.y())


def test_mapping_validation_rejects_horizon_crossing_source_bounds() -> None:
    """An invertible matrix cannot enter a scene when its horizon cuts content."""
    mapping = ProjectiveLayerTransform(m13=1.0, dx=1.0, m33=-50.0)

    with pytest.raises(ValueError, match="horizon crosses"):
        validate_layer_mapping(mapping, RasterBounds(0, 0, 100, 100))


def test_projective_sampling_bound_covers_numerical_local_scales() -> None:
    """Demand density never undershoots finite-difference scale samples."""
    transform = QTransform(1.4, 0.2, 0.002, -0.1, 1.1, -0.001, 8.0, 5.0, 1.0)
    bounds = QRectF(0.0, 0.0, 120.0, 80.0)

    bound = conservative_transform_scale(transform, bounds)

    samples = tuple(
        _numerical_scale(transform, QPointF(x, y))
        for x in (0.0, 30.0, 60.0, 90.0, 120.0)
        for y in (0.0, 20.0, 40.0, 60.0, 80.0)
    )
    assert bound >= max(samples)
    assert bound < 4.0 * max(samples)


def test_projective_scale_bucket_requires_and_uses_finite_bounds() -> None:
    """Tile planning cannot silently apply affine density to a homography."""
    transform = QTransform(1.4, 0.2, 0.002, -0.1, 1.1, -0.001, 8.0, 5.0, 1.0)
    bounds = QRectF(0.0, 0.0, 120.0, 80.0)

    with pytest.raises(ValueError, match="finite source bounds"):
        scale_bucket(transform, 1.0)

    bucket = scale_bucket(transform, 1.0, bounds)
    assert bucket >= conservative_transform_scale(transform, bounds)


def test_projective_visibility_contains_every_numerically_visible_sample() -> None:
    """Path clipping never omits a source point contributing to the viewport."""
    mapping = ProjectiveLayerTransform.from_quadrilaterals(
        (
            QPointF(0.0, 0.0),
            QPointF(100.0, 0.0),
            QPointF(100.0, 100.0),
            QPointF(0.0, 100.0),
        ),
        (
            QPointF(0.0, 0.0),
            QPointF(120.0, 20.0),
            QPointF(100.0, 100.0),
            QPointF(0.0, 100.0),
        ),
    )
    panel = QRectF(40.0, 10.0, 35.0, 45.0)
    source = QRectF(0.0, 0.0, 100.0, 100.0)

    visible = visible_source_rect(mapping.to_qtransform(), panel, source)

    contributing = tuple(
        QPointF(float(x), float(y))
        for x in range(0, 101, 2)
        for y in range(0, 101, 2)
        if panel.contains(mapping.map_point(QPointF(float(x), float(y))))
    )
    assert contributing
    assert all(
        visible.adjusted(-1e-6, -1e-6, 1e-6, 1e-6).contains(point)
        for point in contributing
    )


@pytest.mark.parametrize(
    "mapping",
    (
        ProjectiveLayerTransform(m11=0.0, m22=0.0),
        ProjectiveLayerTransform(m13=1.0, dx=1.0, m33=0.0),
    ),
)
def test_projective_mapping_rejects_unusable_inverse_or_horizon(
    mapping: ProjectiveLayerTransform,
) -> None:
    """Singular mappings and points on the horizon never publish partial values."""
    if mapping.is_invertible:
        with pytest.raises(ValueError, match="horizon"):
            mapping.map_point(QPointF(0.0, 2.0))
    else:
        assert mapping.inverted() is None


def _numerical_scale(transform: QTransform, point: QPointF) -> float:
    """Estimate the largest local stretch through independent finite differences."""
    step = 1e-5
    origin = transform.map(point)
    x_sample = transform.map(point + QPointF(step, 0.0))
    y_sample = transform.map(point + QPointF(0.0, step))
    columns = (
        ((x_sample.x() - origin.x()) / step, (x_sample.y() - origin.y()) / step),
        ((y_sample.x() - origin.x()) / step, (y_sample.y() - origin.y()) / step),
    )
    return (
        sum(component * component for column in columns for component in column)
    ) ** 0.5
