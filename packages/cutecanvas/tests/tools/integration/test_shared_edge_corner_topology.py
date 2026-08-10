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

"""Retained topology proof for sequential shared-edge corner joins."""

from __future__ import annotations

import uuid

from cutecanvas.editor.shared_edge_geometry import SharedEdgeSeam, shared_edge_seam
from cutecanvas.editor.shared_edge_pivot import shared_edge_pivots
from cutecanvas.snapping.edge_model import (
    OrientedEdge,
    polygon_edges,
    quadrilateral_edges,
)
from PySide6.QtCore import QPointF
from qpane.sdk.scene import LayerMapping, LayerTransform


def test_both_endpoints_remain_editable_after_one_endpoint_joins_a_corner() -> None:
    """A joined endpoint and its opposite must remain editable without undo."""
    seam, edges = _initial_seam()
    first_pivot, _end = shared_edge_pivots(seam, edges, tolerance=1e-7)
    assert first_pivot is not None
    first_mappings = dict(first_pivot.mappings_for_point(QPointF(0.0, 0.0)))
    angled, angled_edges = _rediscovered_seam(seam, first_mappings)
    joined_pivot, second_pivot = shared_edge_pivots(
        angled,
        angled_edges,
        tolerance=1e-7,
    )
    assert joined_pivot is not None
    assert second_pivot is not None

    reopened = dict(joined_pivot.mappings_for_point(QPointF(50.0, 0.0)))
    assert len(reopened) == 2
    for participant in angled.participants:
        mapping = reopened[participant.layer_id]
        moving = participant.source_boundary[
            joined_pivot.corner_indexes[angled.participants.index(participant)]
        ]
        assert mapping.map_point(moving) == QPointF(50.0, 0.0)

    final = dict(second_pivot.mappings_for_point(QPointF(400.0, 300.0)))

    assert len(final) == 2
    for participant in angled.participants:
        mapping = final[participant.layer_id]
        moving = participant.source_boundary[
            second_pivot.corner_indexes[angled.participants.index(participant)]
        ]
        assert mapping.map_point(moving) == QPointF(400.0, 300.0)


def _initial_seam() -> tuple[SharedEdgeSeam, tuple[OrientedEdge, ...]]:
    """Return two exact half-canvas rectangles and their vertical seam."""
    first = _boundary(0.0, 200.0)
    second = _boundary(200.0, 400.0)
    first_edges = quadrilateral_edges(str(uuid.uuid4()), first)
    second_edges = quadrilateral_edges(str(uuid.uuid4()), second)
    seam = shared_edge_seam(
        scene_id=uuid.uuid4(),
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
    return seam, (*first_edges, *second_edges)


def _rediscovered_seam(
    initial: SharedEdgeSeam,
    mappings: dict[uuid.UUID, LayerMapping],
) -> tuple[SharedEdgeSeam, tuple[OrientedEdge, ...]]:
    """Rediscover the angled seam from the first committed mapping set."""
    edges = tuple(
        edge
        for participant in initial.participants
        for edge in polygon_edges(
            str(participant.layer_id),
            mappings[participant.layer_id].target_boundary,
        )
    )
    for first in edges:
        for second in edges:
            if first.owner_id >= second.owner_id:
                continue
            first_mapping = mappings[uuid.UUID(first.owner_id)]
            second_mapping = mappings[uuid.UUID(second.owner_id)]
            seam = shared_edge_seam(
                scene_id=initial.scene_id,
                first=first,
                second=second,
                first_mapping=first_mapping,
                second_mapping=second_mapping,
                first_boundary=first_mapping.target_boundary,
                second_boundary=second_mapping.target_boundary,
                coincidence_tolerance=1e-7,
                minimum_overlap=5.0,
            )
            if seam is not None:
                return seam, edges
    raise AssertionError("expected the committed angled seam to remain discoverable")


def _boundary(
    left: float,
    right: float,
) -> tuple[QPointF, QPointF, QPointF, QPointF]:
    """Return one full-height half-canvas rectangle."""
    return (
        QPointF(left, 0.0),
        QPointF(right, 0.0),
        QPointF(right, 300.0),
        QPointF(left, 300.0),
    )
