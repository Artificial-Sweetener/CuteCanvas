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

"""Public geometry contract proof for bounded piecewise layer mappings."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF
from qpane.scene.affine import LayerTransform
from qpane.scene.mapping import inverse_mapping_linearization
from qpane.scene.piecewise import (
    PiecewiseLayerTransform,
    TriangularLayerMappingPatch,
)


def test_inserted_boundary_vertex_maps_without_moving_anchored_remainder() -> None:
    """A split edge must support a kink that one homography cannot represent."""
    mapping = PiecewiseLayerTransform(
        source_boundary=(
            QPointF(0.0, 0.0),
            QPointF(10.0, 0.0),
            QPointF(10.0, 10.0),
            QPointF(10.0, 20.0),
            QPointF(0.0, 20.0),
        ),
        target_boundary=(
            QPointF(0.0, 0.0),
            QPointF(12.0, 0.0),
            QPointF(10.0, 10.0),
            QPointF(10.0, 20.0),
            QPointF(0.0, 20.0),
        ),
    )

    assert mapping.map_point(QPointF(10.0, 0.0)) == QPointF(12.0, 0.0)
    assert mapping.map_point(QPointF(10.0, 10.0)) == QPointF(10.0, 10.0)
    assert mapping.map_point(QPointF(10.0, 20.0)) == QPointF(10.0, 20.0)


def test_piecewise_mapping_round_trips_points_in_each_patch() -> None:
    """Forward and inverse selection must agree across deterministic patches."""
    mapping = _mapping()

    for point in (QPointF(2.0, 2.0), QPointF(8.0, 4.0), QPointF(7.0, 15.0)):
        target = mapping.map_point(point)
        restored = mapping.inverse_map(target)
        assert restored is not None
        assert restored.x() == pytest.approx(point.x())
        assert restored.y() == pytest.approx(point.y())


def test_piecewise_mapping_rejects_inverted_or_mismatched_topology() -> None:
    """Malformed mapping boundaries must fail before entering a render scene."""
    source = _mapping().source_boundary

    with pytest.raises(ValueError, match="same vertex count"):
        PiecewiseLayerTransform(source, source[:-1])
    with pytest.raises(ValueError, match="winding"):
        PiecewiseLayerTransform(source, tuple(reversed(source)))


def test_piecewise_mapping_rejects_collinear_boundary_backtracking() -> None:
    """Inserted topology may be collinear but must never overlap an earlier edge."""
    overlapping = (
        QPointF(0.0, 0.0),
        QPointF(10.0, 0.0),
        QPointF(10.0, 10.0),
        QPointF(0.0, 10.0),
        QPointF(5.0, 0.0),
    )

    with pytest.raises(ValueError, match="boundary must be simple"):
        PiecewiseLayerTransform(overlapping, overlapping)


def test_piecewise_mapping_exposes_local_inverse_differential() -> None:
    """Consumers can preserve scene-space geometry within the active patch."""
    mapping = _mapping()

    inverse = inverse_mapping_linearization(mapping, QPointF(8.0, 4.0))

    assert inverse is not None
    patch = next(
        patch for patch in mapping.patches if patch.contains_source(QPointF(8.0, 4.0))
    )
    expected = patch.transform.inverted()
    assert expected is not None
    assert inverse == LayerTransform(
        m11=expected.m11,
        m12=expected.m12,
        m21=expected.m21,
        m22=expected.m22,
    )


def test_angled_thin_patch_solves_an_exact_affine_mapping() -> None:
    """Valid angled cage triangles must not fail from projective solver noise."""
    source = (
        QPointF(-87.16477036119368, 64.9672169305976),
        QPointF(-111.65043406833708, 108.26275269403399),
        QPointF(-100.61868025180763, 88.49394071069336),
    )
    target = (
        QPointF(-79.02581623794939, -16.52199445991444),
        QPointF(-94.32795318876832, 17.869792064759925),
        QPointF(-87.49824925191397, 2.124074784161333),
    )

    patch = TriangularLayerMappingPatch(source, target)

    for source_point, target_point in zip(source, target, strict=True):
        mapped = patch.transform.map_point(source_point)
        assert mapped.x() == pytest.approx(target_point.x(), abs=1e-9)
        assert mapped.y() == pytest.approx(target_point.y(), abs=1e-9)


def _mapping() -> PiecewiseLayerTransform:
    """Return one convex five-vertex mapping with a split right edge."""
    return PiecewiseLayerTransform(
        (
            QPointF(0.0, 0.0),
            QPointF(10.0, 0.0),
            QPointF(10.0, 10.0),
            QPointF(10.0, 20.0),
            QPointF(0.0, 20.0),
        ),
        (
            QPointF(0.0, 0.0),
            QPointF(12.0, 0.0),
            QPointF(10.0, 10.0),
            QPointF(10.0, 20.0),
            QPointF(0.0, 20.0),
        ),
    )
