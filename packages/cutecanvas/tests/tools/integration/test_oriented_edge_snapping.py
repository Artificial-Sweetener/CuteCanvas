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

"""Deterministic proof for finite oriented-edge snapping."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, QRectF

from cutecanvas.snapping.edge_index import OrientedEdgeIndex
from cutecanvas.snapping.edge_model import OrientedEdge, polygon_edges
from cutecanvas.snapping.model import SnapGrid
from cutecanvas.snapping.oriented_resolution import OrientedEdgeSnapResolver


def _edge(owner: str, offset: float) -> OrientedEdge:
    """Return a 45-degree segment translated along its canonical normal."""
    normal = QPointF(-(2**-0.5), 2**-0.5)
    translation = normal * offset
    return OrientedEdge(
        owner,
        QPointF(0.0, 0.0) + translation,
        QPointF(100.0, 100.0) + translation,
        QPointF(50.0, 50.0) + translation,
    )


def test_diagonal_edge_snaps_to_parallel_finite_target() -> None:
    """A translated diagonal side should align without axis approximation."""
    source = _edge("source", 0.0)
    target = _edge("target", 20.0)
    resolver = OrientedEdgeSnapResolver(
        source,
        OrientedEdgeIndex.build(
            (target,),
            scene_units_per_device_pixel=1.0,
        ),
        threshold_device_pixels=6.0,
        release_device_pixels=9.0,
    )

    result = resolver.resolve(16.0, scene_units_per_device_pixel=1.0)

    assert result.distance == pytest.approx(20.0)
    assert result.guide is not None
    assert result.guide.target_owner_id == "target"
    assert result.guide.source_owner_id == "source"


def test_oriented_snap_lock_releases_only_after_hysteresis_threshold() -> None:
    """Pointer jitter should retain a target until the larger release distance."""
    source = _edge("source", 0.0)
    target = _edge("target", 20.0)
    resolver = OrientedEdgeSnapResolver(
        source,
        OrientedEdgeIndex.build(
            (target,),
            scene_units_per_device_pixel=1.0,
        ),
        threshold_device_pixels=6.0,
        release_device_pixels=9.0,
    )

    assert resolver.resolve(
        15.0, scene_units_per_device_pixel=1.0
    ).distance == pytest.approx(20.0)
    assert resolver.resolve(
        12.0, scene_units_per_device_pixel=1.0
    ).distance == pytest.approx(20.0)
    released = resolver.resolve(10.0, scene_units_per_device_pixel=1.0)
    assert released.distance == 10.0
    assert released.guide is None


def test_snap_suppression_clears_lock_and_preserves_raw_distance() -> None:
    """Explicit suppression should never retain a prior oriented target."""
    source = _edge("source", 0.0)
    target = _edge("target", 20.0)
    resolver = OrientedEdgeSnapResolver(
        source,
        OrientedEdgeIndex.build(
            (target,),
            scene_units_per_device_pixel=1.0,
        ),
        threshold_device_pixels=6.0,
        release_device_pixels=9.0,
    )
    resolver.resolve(16.0, scene_units_per_device_pixel=1.0)

    suppressed = resolver.resolve(
        17.0,
        scene_units_per_device_pixel=1.0,
        suppressed=True,
    )

    assert suppressed.distance == 17.0
    assert suppressed.guide is None


def test_axis_shared_edge_uses_configured_grid_without_index_expansion() -> None:
    """An axis seam should synthesize only its nearest configured grid line."""
    source = OrientedEdge(
        "source",
        QPointF(10.0, 0.0),
        QPointF(10.0, 100.0),
        QPointF(0.0, 50.0),
    )
    resolver = OrientedEdgeSnapResolver(
        source,
        OrientedEdgeIndex.build((), scene_units_per_device_pixel=1.0),
        threshold_device_pixels=6.0,
        release_device_pixels=9.0,
        grid=SnapGrid(QPointF(), 32.0, 32.0, QRectF(0.0, 0.0, 200.0, 200.0)),
    )

    result = resolver.resolve(-19.0, scene_units_per_device_pixel=1.0)

    assert result.distance == pytest.approx(-22.0)
    assert result.guide is not None
    assert result.guide.target_owner_id == "grid:oriented:x"


def test_polygon_edges_ignore_one_joined_vertex_pair() -> None:
    """A valid joined-corner preview exposes its remaining finite snap edges."""
    edges = polygon_edges(
        "joined",
        (
            QPointF(0.0, 0.0),
            QPointF(0.0, 0.0),
            QPointF(10.0, 10.0),
            QPointF(0.0, 10.0),
        ),
    )

    assert len(edges) == 3
    assert all(edge.length > 0.0 for edge in edges)
