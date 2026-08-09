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

"""Public geometry contract proof for full-source joined-edge mappings."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF
from qpane.scene.affine import LayerTransform
from qpane.scene.bilinear import BilinearLayerTransform


def test_joined_edge_mapping_covers_and_round_trips_the_complete_source() -> None:
    """Joining one target edge must not discard any source region."""
    mapping = _mapping()

    for y in range(11):
        for x in range(11):
            source = QPointF(float(x), float(y))
            target = mapping.map_point(source)
            restored = mapping.inverse_map(target)
            assert restored is not None
            if y == 0:
                assert target == QPointF(10.0, 0.0)
                continue
            assert restored.x() == pytest.approx(source.x())
            assert restored.y() == pytest.approx(source.y())


def test_joined_edge_mapping_composes_without_losing_its_source_domain() -> None:
    """Global composition preserves every source point and the joined edge."""
    mapping = _mapping()
    affine = LayerTransform(dx=5.0, dy=-3.0)

    followed = mapping.followed_by(affine)
    preceded = mapping.preceded_by(affine)

    assert followed.map_point(QPointF(5.0, 5.0)) == affine.map_point(
        mapping.map_point(QPointF(5.0, 5.0))
    )
    assert preceded.map_point(QPointF(0.0, 3.0)) == mapping.map_point(
        affine.map_point(QPointF(0.0, 3.0))
    )
    assert followed.target_boundary[0] == followed.target_boundary[1]
    assert preceded.source_boundary[0] == QPointF(-5.0, 3.0)


def test_joined_edge_mapping_rejects_an_unjoined_target() -> None:
    """The bilinear limit type accepts exactly one joined first edge."""
    source = _mapping().source_boundary

    with pytest.raises(ValueError, match="join its first edge"):
        BilinearLayerTransform(source, source)


def _mapping() -> BilinearLayerTransform:
    """Return one square-to-triangle joined-edge mapping."""
    return BilinearLayerTransform(
        (
            QPointF(0.0, 0.0),
            QPointF(10.0, 0.0),
            QPointF(10.0, 10.0),
            QPointF(0.0, 10.0),
        ),
        (
            QPointF(10.0, 0.0),
            QPointF(10.0, 0.0),
            QPointF(10.0, 10.0),
            QPointF(0.0, 10.0),
        ),
    )
