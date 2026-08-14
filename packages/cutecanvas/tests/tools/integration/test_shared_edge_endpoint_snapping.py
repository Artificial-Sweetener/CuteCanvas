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

"""Gesture-level proof for shared-edge endpoint orientation snapping."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QPointF

from cutecanvas.editor.shared_edge_geometry import shared_edge_seam
from cutecanvas.editor.shared_edge_pivot import SharedEdgeHandle, shared_edge_pivots
from cutecanvas.editor.shared_edge_session import SharedEdgeGestureSession
from cutecanvas.snapping.edge_candidates import OrientedTargetSnapshot
from cutecanvas.snapping.edge_model import OrientedEdge, quadrilateral_edges
from qpane.sdk.scene import LayerTransform


def test_endpoint_session_snaps_to_exact_45_degree_orientation() -> None:
    """The complete gesture must map both participants to one perfect slant."""
    session = _session(())

    update = session.resolve(
        QPointF(54.0, 0.0),
        scene_units_per_device_pixel=1.0,
        suppressed=False,
    )

    assert update is not None
    assert update.points == (QPointF(50.0, 0.0), QPointF(150.0, 100.0))
    assert len(update.values) == 2
    assert update.guides and update.guides[0].target_owner_id == "orientation:45"


def test_endpoint_session_snaps_to_continuous_stationary_edge() -> None:
    """The complete gesture must extend an edge meeting the fixed seam endpoint."""
    target = OrientedEdge(
        "stationary",
        QPointF(150.0, 100.0),
        QPointF(200.0, 200.0),
        QPointF(175.0, 150.0),
        priority=10,
    )
    session = _session((target,))

    update = session.resolve(
        QPointF(104.0, 0.0),
        scene_units_per_device_pixel=1.0,
        suppressed=False,
    )

    assert update is not None
    assert update.points == (QPointF(100.0, 0.0), QPointF(150.0, 100.0))
    assert len(update.values) == 2
    assert update.guides and update.guides[0].target_owner_id == "stationary"


def _session(targets: tuple[OrientedEdge, ...]) -> SharedEdgeGestureSession:
    """Return one top-endpoint gesture with a long horizontal common rail."""
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    first = _boundary(0.0, 150.0)
    second = _boundary(150.0, 300.0)
    first_edges = quadrilateral_edges(str(first_id), first)
    second_edges = quadrilateral_edges(str(second_id), second)
    scene_id = uuid.uuid4()
    seam = shared_edge_seam(
        scene_id=scene_id,
        first=first_edges[1],
        second=second_edges[3],
        first_mapping=LayerTransform(),
        second_mapping=LayerTransform(),
        first_boundary=first,
        second_boundary=second,
        coincidence_tolerance=1e-7,
        minimum_overlap=5.0,
    )
    assert seam is not None
    start, _end = shared_edge_pivots(
        seam,
        (*first_edges, *second_edges),
        tolerance=1e-7,
    )
    assert start is not None
    return SharedEdgeGestureSession(
        seam=seam,
        handle=SharedEdgeHandle.START,
        pivot=start,
        origin=start.moving_point,
        targets=OrientedTargetSnapshot(scene_id, targets, None),
        scene_units_per_device_pixel=1.0,
    )


def _boundary(
    left: float,
    right: float,
) -> tuple[QPointF, QPointF, QPointF, QPointF]:
    """Return one half-height participant rectangle."""
    return (
        QPointF(left, 0.0),
        QPointF(right, 0.0),
        QPointF(right, 100.0),
        QPointF(left, 100.0),
    )
