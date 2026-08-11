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
"""Movement snapping correctness and workload-scaling regressions."""

from __future__ import annotations

import pytest
from cutecanvas.snapping.engine import SnapSession
from cutecanvas.snapping.model import SnapCandidate, bounds_candidates
from cutecanvas_test_support.harness.timing import (
    average_interaction_latency_ms,
    interaction_clock,
)
from PySide6.QtCore import QPointF, QRectF


def test_moving_top_edge_acquires_document_center_while_left_edge_stays_snapped() -> (
    None
):
    """A moving edge may acquire a perpendicular document center relationship."""
    session = SnapSession(
        "rectangle",
        QRectF(0.0, 600.0, 200.0, 100.0),
        bounds_candidates(
            "document",
            QRectF(0.0, 0.0, 1000.0, 800.0),
            cross_feature_center=True,
        ),
    )

    result = session.resolve(
        QPointF(0.0, -197.0),
        scene_units_per_device_pixel=1.0,
    )

    assert result.delta == QPointF(0.0, -200.0)
    assert result.snapped_x and result.snapped_y
    assert {guide.position for guide in result.guides} == {0.0, 400.0}


@pytest.mark.interactive_performance
def test_cross_feature_snapping_scales_subquadratically_under_dense_reversals() -> (
    None
):
    """Doubling candidates must not approach quadratic construction or pointer cost."""
    baseline_candidates = _candidates(250)
    dense_candidates = _candidates(500)
    source_bounds = QRectF(1.0, 2.0, 10.0, 8.0)
    baseline_construction_ms = average_interaction_latency_ms(
        lambda: SnapSession("source", source_bounds, baseline_candidates),
        repetitions=1_000,
    )
    dense_construction_ms = average_interaction_latency_ms(
        lambda: SnapSession("source", source_bounds, dense_candidates),
        repetitions=1_000,
    )
    baseline_resolution_ms = _average_reversal_latency_ms(
        SnapSession("source", source_bounds, baseline_candidates)
    )
    dense_resolution_ms = _average_reversal_latency_ms(
        SnapSession("source", source_bounds, dense_candidates)
    )

    assert dense_construction_ms < baseline_construction_ms * 3.0
    assert dense_resolution_ms < baseline_resolution_ms * 3.0


def _candidates(layer_count: int) -> tuple[SnapCandidate, ...]:
    """Return deterministic layer bounds for one snapping workload."""
    return tuple(
        candidate
        for index in range(layer_count)
        for candidate in bounds_candidates(
            f"layer:{index}",
            QRectF(index * 20.0, index * 13.0, 10.0, 8.0),
        )
    )


def _average_reversal_latency_ms(session: SnapSession) -> float:
    """Measure alternating near and far pointer resolution as one stable batch."""
    repetitions = 10_000
    started = interaction_clock()
    for index in range(repetitions):
        point = QPointF(9_000.0, 6_000.0) if index % 2 else QPointF(1_000.0, 650.0)
        session.resolve(point, scene_units_per_device_pixel=1.0)
    return (interaction_clock() - started) * 1000.0 / repetitions
