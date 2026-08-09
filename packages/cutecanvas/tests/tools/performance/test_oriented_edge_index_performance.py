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

"""Interactive latency contract for frozen oriented-edge lookup."""

from __future__ import annotations

from cutecanvas.snapping.edge_index import OrientedEdgeIndex
from cutecanvas.snapping.edge_model import OrientedEdge
from cutecanvas_test_support.harness.timing import (
    INTERACTIVE_PERFORMANCE,
    interaction_clock,
    tail_interaction_latency_ms,
)
from PySide6.QtCore import QPointF

pytestmark = INTERACTIVE_PERFORMANCE


def test_large_frozen_edge_index_keeps_pointer_lookup_interactive() -> None:
    """Thousands of stationary edges must not cause per-update scene scans."""
    edges = tuple(
        OrientedEdge(
            f"layer-{index}",
            QPointF(index * 3.0, 0.0),
            QPointF(index * 3.0 + 100.0, 100.0),
            QPointF(index * 3.0 + 50.0, 50.0),
        )
        for index in range(2_000)
    )
    started = interaction_clock()
    index = OrientedEdgeIndex.build(edges, scene_units_per_device_pixel=1.0)
    build_ms = (interaction_clock() - started) * 1000.0
    latencies: list[float] = []
    batch_size = 32
    for batch in range(1_000):
        started = interaction_clock()
        for offset in range(batch_size):
            sample = batch * batch_size + offset
            point = QPointF(float((sample * 17) % 6_000), 50.0)
            index.near_point(point, 8.0)
        latencies.append((interaction_clock() - started) * 1000.0 / batch_size)

    assert build_ms < 150.0
    assert tail_interaction_latency_ms(latencies, quantile=0.99) < 1.0
