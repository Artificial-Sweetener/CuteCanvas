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

"""Interactive latency contract for irregular shared-edge translation."""

from __future__ import annotations

import uuid

from cutecanvas.editor.shared_edge_geometry import shared_edge_seam
from cutecanvas.editor.shared_edge_grouping import grouped_shared_edges
from cutecanvas.snapping.edge_model import polygon_edges, quadrilateral_edges
from cutecanvas_test_support.harness.timing import (
    INTERACTIVE_PERFORMANCE,
    interaction_clock,
    tail_interaction_latency_ms,
)
from PySide6.QtCore import QPointF
from qpane.sdk.scene import LayerTransform

pytestmark = INTERACTIVE_PERFORMANCE


def test_dormant_irregular_translation_geometry_remains_interactive() -> None:
    """Preserved angled cage geometry must stay below 2 ms per resolution."""
    first_id = str(uuid.uuid4())
    second_id = str(uuid.uuid4())
    first_boundary = (
        QPointF(8.0, 121.0),
        QPointF(846.0, 318.0),
        QPointF(423.0, 990.0),
        QPointF(258.0, 951.0),
    )
    second_boundary = (
        QPointF(872.0, 223.0),
        QPointF(1038.0, 160.0),
        QPointF(1109.0, 327.0),
        QPointF(1040.0, 579.0),
        QPointF(863.0, 824.0),
        QPointF(423.0, 990.0),
        QPointF(846.0, 318.0),
    )
    first_edges = polygon_edges(first_id, first_boundary)
    second_edges = polygon_edges(second_id, second_boundary)
    scene_id = uuid.uuid4()
    seam = shared_edge_seam(
        scene_id=scene_id,
        first=first_edges[1],
        second=second_edges[5],
        first_mapping=LayerTransform(),
        second_mapping=LayerTransform(),
        first_boundary=first_boundary,
        second_boundary=second_boundary,
        coincidence_tolerance=1e-7,
        minimum_overlap=5.0,
    )
    assert seam is not None
    latencies: list[float] = []
    batch_size = 16
    for batch in range(150):
        started = interaction_clock()
        for offset in range(batch_size):
            sample = batch * batch_size + offset
            update = seam.translation_for_distance(
                float((sample % 101) - 50),
                minimum_thickness=2.0,
            )
            assert len(update.mappings) == 2
        latencies.append((interaction_clock() - started) * 1000.0 / batch_size)

    assert tail_interaction_latency_ms(latencies, quantile=0.99) < 2.0


def test_four_participant_group_translation_remains_interactive() -> None:
    """A four-layer grid seam must resolve below 2 ms per update."""
    scene_id = uuid.uuid4()
    boundaries = (
        _rectangle(0.0, 0.0, 50.0, 50.0),
        _rectangle(50.0, 0.0, 50.0, 50.0),
        _rectangle(0.0, 50.0, 50.0, 50.0),
        _rectangle(50.0, 50.0, 50.0, 50.0),
    )
    layer_ids = tuple(str(uuid.uuid4()) for _boundary in boundaries)
    edges = tuple(
        quadrilateral_edges(layer_id, boundary)
        for layer_id, boundary in zip(layer_ids, boundaries, strict=True)
    )
    pair_seams = tuple(
        shared_edge_seam(
            scene_id=scene_id,
            first=edges[top][2],
            second=edges[bottom][0],
            first_mapping=LayerTransform(),
            second_mapping=LayerTransform(),
            first_boundary=boundaries[top],
            second_boundary=boundaries[bottom],
            coincidence_tolerance=1e-7,
            minimum_overlap=5.0,
        )
        for top, bottom in ((0, 2), (1, 3))
    )
    assert all(seam is not None for seam in pair_seams)
    seam = grouped_shared_edges(
        tuple(seam for seam in pair_seams if seam is not None),
        tolerance=1e-7,
    )[0]
    assert len(seam.participants) == 4

    latencies: list[float] = []
    batch_size = 16
    for batch in range(150):
        started = interaction_clock()
        for offset in range(batch_size):
            sample = batch * batch_size + offset
            update = seam.translation_for_distance(
                float((sample % 41) - 20),
                minimum_thickness=2.0,
            )
            assert len(update.mappings) == 4
        latencies.append((interaction_clock() - started) * 1000.0 / batch_size)

    assert tail_interaction_latency_ms(latencies, quantile=0.99) < 2.0


def _rectangle(
    left: float,
    top: float,
    width: float,
    height: float,
) -> tuple[QPointF, QPointF, QPointF, QPointF]:
    """Return a clockwise rectangular boundary."""
    return (
        QPointF(left, top),
        QPointF(left + width, top),
        QPointF(left + width, top + height),
        QPointF(left, top + height),
    )
