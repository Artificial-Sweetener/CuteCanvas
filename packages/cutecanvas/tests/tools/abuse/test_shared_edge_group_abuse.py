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

"""Stress contracts for arbitrary-participant shared-edge translation."""

from __future__ import annotations

import uuid

from cutecanvas.editor.shared_edge_geometry import SharedEdgeSeam, shared_edge_seam
from cutecanvas.editor.shared_edge_grouping import grouped_shared_edges
from cutecanvas.snapping.edge_model import quadrilateral_edges
from PySide6.QtCore import QPointF
from qpane.sdk.scene import LayerTransform


def test_four_participant_group_survives_extreme_direction_switching() -> None:
    """Every extreme sample must resolve one complete group without stale mappings."""
    seam = _four_participant_seam()
    expected_ids = {participant.layer_id for participant in seam.participants}

    for sample in range(2_000):
        requested = (-1.0 if sample % 2 else 1.0) * (60.0 + sample % 23)
        update = seam.translation_for_distance(
            requested,
            minimum_thickness=2.0,
        )
        assert {layer_id for layer_id, _mapping in update.mappings} == expected_ids
        assert abs(update.distance) <= abs(requested)

    restored = seam.translation_for_distance(0.0, minimum_thickness=2.0)
    assert {layer_id for layer_id, _mapping in restored.mappings} == expected_ids
    restored_mappings = dict(restored.mappings)
    assert all(
        restored_mappings[participant.layer_id].map_point(source) == target
        for participant in seam.participants
        for source, target in zip(
            participant.source_boundary,
            participant.scene_boundary,
            strict=True,
        )
    )


def _four_participant_seam() -> SharedEdgeSeam:
    """Return the horizontal seam through a four-rectangle grid."""
    scene_id = uuid.uuid4()
    boundaries = (
        _rectangle(0.0, 0.0, 50.0, 50.0),
        _rectangle(50.0, 0.0, 50.0, 50.0),
        _rectangle(0.0, 50.0, 50.0, 50.0),
        _rectangle(50.0, 50.0, 50.0, 50.0),
    )
    edges = tuple(
        quadrilateral_edges(str(uuid.uuid4()), boundary) for boundary in boundaries
    )
    pairs = tuple(
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
    assert all(pair is not None for pair in pairs)
    groups = grouped_shared_edges(
        tuple(pair for pair in pairs if pair is not None),
        tolerance=1e-7,
    )
    assert len(groups) == 1
    assert len(groups[0].participants) == 4
    return groups[0]


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
