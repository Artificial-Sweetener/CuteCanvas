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

"""Interactive latency contract for constrained shared-edge pivots."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QPointF

from cutecanvas.editor.shared_edge_geometry import shared_edge_seam
from cutecanvas.editor.shared_edge_pivot import SharedEdgeHandle, shared_edge_pivots
from cutecanvas.editor.shared_edge_session import SharedEdgeGestureSession
from cutecanvas.snapping.edge_candidates import OrientedTargetSnapshot
from cutecanvas.snapping.edge_model import OrientedEdge, quadrilateral_edges
from cutecanvas_test_support.harness.timing import (
    INTERACTIVE_PERFORMANCE,
    interaction_clock,
    tail_interaction_latency_ms,
    tail_latency_sample_count,
)
from qpane.sdk.scene import LayerTransform

pytestmark = INTERACTIVE_PERFORMANCE


def test_pivot_updates_remain_interactive_with_large_frozen_target_set() -> None:
    """Paired cage mapping and snap resolution must stay below 2 ms."""
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    first_corners = _corners(0.0, 100.0)
    second_corners = _corners(100.0, 200.0)
    first_edges = quadrilateral_edges(str(first_id), first_corners)
    second_edges = quadrilateral_edges(str(second_id), second_corners)
    scene_id = uuid.uuid4()
    seam = shared_edge_seam(
        scene_id=scene_id,
        first=first_edges[1],
        second=second_edges[3],
        first_mapping=LayerTransform(),
        second_mapping=LayerTransform(),
        first_boundary=first_corners,
        second_boundary=second_corners,
        coincidence_tolerance=1e-7,
        minimum_overlap=10.0,
    )
    assert seam is not None
    start, _end = shared_edge_pivots(
        seam,
        (*first_edges, *second_edges),
        tolerance=1e-7,
    )
    assert start is not None
    targets = tuple(
        OrientedEdge(
            f"target-{index}",
            QPointF(index * 0.25, -10.0),
            QPointF(index * 0.25, 10.0),
            QPointF(index * 0.25, 0.0),
        )
        for index in range(1_000)
    )
    session = SharedEdgeGestureSession(
        seam=seam,
        handle=SharedEdgeHandle.START,
        pivot=start,
        origin=start.moving_point,
        targets=OrientedTargetSnapshot(scene_id, targets, None),
        scene_units_per_device_pixel=1.0,
    )
    latencies: list[float] = []
    batch_size = 16
    for batch in range(tail_latency_sample_count(quantile=0.99)):
        started = interaction_clock()
        for offset in range(batch_size):
            sample = batch * batch_size + offset
            update = session.resolve(
                QPointF(25.0 + sample % 150, float(sample % 7)),
                scene_units_per_device_pixel=1.0,
                suppressed=False,
            )
            assert update is not None
        latencies.append((interaction_clock() - started) * 1000.0 / batch_size)

    assert tail_interaction_latency_ms(latencies, quantile=0.99) < 2.0


def _corners(
    left: float,
    right: float,
) -> tuple[QPointF, QPointF, QPointF, QPointF]:
    """Return one rectangular manipulation quad with horizontal pivot rails."""
    return (
        QPointF(left, 0.0),
        QPointF(right, 0.0),
        QPointF(right, 100.0),
        QPointF(left, 100.0),
    )
