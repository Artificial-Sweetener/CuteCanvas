#    CuteCanvas - High-performance layered image editor
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

"""Finite-rail snapping and hysteresis proof for endpoint pivots."""

from __future__ import annotations

from cutecanvas.snapping.edge_model import OrientedEdge
from cutecanvas.snapping.model import SnapGrid
from cutecanvas.snapping.rail_resolution import RailSnapResolver
from PySide6.QtCore import QPointF, QRectF


def test_diagonal_rail_snaps_to_frozen_edge_intersection_with_hysteresis() -> None:
    """A pivot point must retain an exact edge crossing through pointer jitter."""
    target = OrientedEdge(
        "target",
        QPointF(50.0, 0.0),
        QPointF(50.0, 100.0),
        QPointF(60.0, 50.0),
        priority=10,
    )
    resolver = RailSnapResolver(
        QPointF(0.0, 0.0),
        QPointF(100.0, 100.0),
        (target,),
        threshold_device_pixels=6.0,
        release_device_pixels=9.0,
    )

    acquired = resolver.resolve(
        QPointF(53.0, 53.0),
        scene_units_per_device_pixel=1.0,
    )
    retained = resolver.resolve(
        QPointF(56.0, 56.0),
        scene_units_per_device_pixel=1.0,
    )
    suppressed = resolver.resolve(
        QPointF(53.0, 53.0),
        scene_units_per_device_pixel=1.0,
        suppressed=True,
    )

    assert acquired.point == QPointF(50.0, 50.0)
    assert acquired.guide is not None
    assert retained.point == QPointF(50.0, 50.0)
    assert suppressed.point == QPointF(53.0, 53.0)
    assert suppressed.guide is None


def test_rail_snaps_to_nearest_reachable_grid_crossing() -> None:
    """Grid snapping must remain available for a non-axis-aligned rail."""
    resolver = RailSnapResolver(
        QPointF(0.0, 0.0),
        QPointF(100.0, 50.0),
        (),
        threshold_device_pixels=6.0,
        release_device_pixels=9.0,
        grid=SnapGrid(
            QPointF(0.0, 0.0),
            20.0,
            20.0,
            QRectF(0.0, 0.0, 100.0, 100.0),
        ),
    )

    result = resolver.resolve(
        QPointF(39.0, 21.0),
        scene_units_per_device_pixel=1.0,
    )

    assert result.point == QPointF(40.0, 20.0)
    assert result.guide is not None
