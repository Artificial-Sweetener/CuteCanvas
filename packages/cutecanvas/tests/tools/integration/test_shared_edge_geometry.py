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

"""Exact coupled-affine proof for inferred shared layer edges."""

from __future__ import annotations

import uuid

import pytest
from cutecanvas.editor.shared_edge_geometry import shared_edge_seam
from cutecanvas.editor.shared_edge_pivot import shared_edge_pivots
from cutecanvas.snapping.edge_model import (
    OrientedEdge,
    polygon_edges,
    quadrilateral_edges,
)
from PySide6.QtCore import QPointF
from qpane.sdk.scene import LayerTransform


def _shared_edges() -> tuple[OrientedEdge, OrientedEdge]:
    """Return one seam with participant centers on opposite sides."""
    first_id = str(uuid.uuid4())
    second_id = str(uuid.uuid4())
    return (
        OrientedEdge(
            first_id,
            QPointF(10.0, 0.0),
            QPointF(10.0, 10.0),
            QPointF(5.0, 5.0),
        ),
        OrientedEdge(
            second_id,
            QPointF(10.0, 10.0),
            QPointF(10.0, 0.0),
            QPointF(15.0, 5.0),
        ),
    )


def _participant_corners() -> tuple[
    tuple[QPointF, QPointF, QPointF, QPointF],
    tuple[QPointF, QPointF, QPointF, QPointF],
]:
    """Return side-by-side rectangles with continuous top and bottom rails."""
    return (
        (
            QPointF(0.0, 0.0),
            QPointF(10.0, 0.0),
            QPointF(10.0, 10.0),
            QPointF(0.0, 10.0),
        ),
        (
            QPointF(10.0, 0.0),
            QPointF(20.0, 0.0),
            QPointF(20.0, 10.0),
            QPointF(10.0, 10.0),
        ),
    )


def _seam_kwargs(first: OrientedEdge, second: OrientedEdge) -> dict[str, object]:
    """Return complete immutable participant inputs for one seam solve."""
    first_corners, second_corners = _participant_corners()
    return {
        "scene_id": uuid.uuid4(),
        "first": first,
        "second": second,
        "first_mapping": LayerTransform(),
        "second_mapping": LayerTransform(),
        "first_boundary": first_corners,
        "second_boundary": second_corners,
        "coincidence_tolerance": 1e-7,
        "minimum_overlap": 5.0,
    }


def test_shared_seam_moves_both_edges_and_fixes_exterior_boundaries() -> None:
    """One scalar must move the seam while every exterior vertex stays fixed."""
    first, second = _shared_edges()
    seam = shared_edge_seam(**_seam_kwargs(first, second))
    assert seam is not None
    assert seam.parallel_translation_enabled
    distance = 2.5
    translation = seam.translation_for_distance(distance, minimum_thickness=0.1)
    transforms = dict(translation.mappings)

    assert translation.distance == pytest.approx(distance)
    displacement = seam.edge.normal * distance
    for participant in seam.participants:
        mapping = transforms[participant.layer_id]
        for index, (source, initial) in enumerate(
            zip(
                participant.source_boundary,
                participant.scene_boundary,
                strict=True,
            )
        ):
            expected = (
                initial + displacement
                if index in participant.translation_indexes
                else initial
            )
            mapped = mapping.map_point(source)
            assert mapped.x() == pytest.approx(expected.x())
            assert mapped.y() == pytest.approx(expected.y())


def test_shared_seam_constraint_prevents_zero_thickness_and_crossing() -> None:
    """Extreme pointer motion must stop before either layer becomes singular."""
    first, second = _shared_edges()
    seam = shared_edge_seam(**_seam_kwargs(first, second))
    assert seam is not None

    constrained_positive = seam.translation_for_distance(
        1_000.0,
        minimum_thickness=2.0,
    )
    constrained_negative = seam.translation_for_distance(
        -1_000.0,
        minimum_thickness=2.0,
    )

    assert constrained_negative.distance == pytest.approx(-8.0, abs=1e-3)
    assert constrained_positive.distance == pytest.approx(8.0, abs=1e-3)
    for translation in (constrained_negative, constrained_positive):
        assert all(mapping.is_invertible for _layer_id, mapping in translation.mappings)


def test_irregular_shared_seam_does_not_move_remote_vertices() -> None:
    """Diagonal editing must not expand an irregular participant behind its seam."""
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
    seam = shared_edge_seam(
        scene_id=uuid.uuid4(),
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
    assert not seam.parallel_translation_enabled

    translation = seam.translation_for_distance(50.0, minimum_thickness=2.0)
    displacement = seam.edge.normal * translation.distance
    assert translation.distance == pytest.approx(50.0)
    for participant in seam.participants:
        mapping = dict(translation.mappings)[participant.layer_id]
        for index, (source, initial) in enumerate(
            zip(
                participant.source_boundary,
                participant.scene_boundary,
                strict=True,
            )
        ):
            expected = (
                initial + displacement
                if index in participant.translation_indexes
                else initial
            )
            mapped = mapping.map_point(source)
            assert mapped.x() == pytest.approx(expected.x())
            assert mapped.y() == pytest.approx(expected.y())


def test_same_side_or_short_overlap_does_not_form_a_shared_seam() -> None:
    """Coincident lines without true adjacency must not deceive the user."""
    first, second = _shared_edges()
    same_side = OrientedEdge(
        second.owner_id,
        second.start,
        second.end,
        QPointF(8.0, 8.0),
    )

    assert shared_edge_seam(**_seam_kwargs(first, same_side)) is None
    assert (
        shared_edge_seam(
            **{
                **_seam_kwargs(first, second),
                "minimum_overlap": 20.0,
            }
        )
        is None
    )


def test_endpoint_pivot_moves_only_common_corner_and_fixes_opposite_end() -> None:
    """A common rail enables one exact paired cage corner gesture."""
    first_corners, second_corners = _participant_corners()
    first_edges = quadrilateral_edges(str(uuid.uuid4()), first_corners)
    second_edges = quadrilateral_edges(str(uuid.uuid4()), second_corners)
    seam = shared_edge_seam(
        scene_id=uuid.uuid4(),
        first=first_edges[1],
        second=second_edges[3],
        first_mapping=LayerTransform(),
        second_mapping=LayerTransform(),
        first_boundary=first_corners,
        second_boundary=second_corners,
        coincidence_tolerance=1e-7,
        minimum_overlap=5.0,
    )
    assert seam is not None
    start, end = shared_edge_pivots(
        seam,
        (*first_edges, *second_edges),
        tolerance=1e-7,
    )
    assert start is not None and end is not None

    target = start.constrained_point(
        QPointF(12.0, 3.0),
        endpoint_join_span=1.0,
    )
    assert target == QPointF(12.0, 0.0)
    mappings = dict(start.mappings_for_point(target))

    for participant, corner_index in zip(
        seam.participants,
        start.corner_indexes,
        strict=True,
    ):
        mapping = mappings[participant.layer_id]
        assert mapping.map_point(participant.source_boundary[corner_index]) == target
        fixed_index = participant.scene_boundary.index(start.fixed_point)
        assert (
            mapping.map_point(participant.source_boundary[fixed_index])
            == start.fixed_point
        )


def test_endpoint_pivot_joins_exact_rail_corner_without_dropping_source_area() -> None:
    """The valid rail limit keeps both participant interiors mapped."""
    first_corners, second_corners = _participant_corners()
    first_edges = quadrilateral_edges(str(uuid.uuid4()), first_corners)
    second_edges = quadrilateral_edges(str(uuid.uuid4()), second_corners)
    seam = shared_edge_seam(
        scene_id=uuid.uuid4(),
        first=first_edges[1],
        second=second_edges[3],
        first_mapping=LayerTransform(),
        second_mapping=LayerTransform(),
        first_boundary=first_corners,
        second_boundary=second_corners,
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

    target = start.constrained_point(
        start.rail_end,
        endpoint_join_span=1.0,
    )
    assert target == start.rail_end
    mappings = dict(start.mappings_for_point(target))

    for participant in seam.participants:
        mapping = mappings[participant.layer_id]
        center = _boundary_center(participant.source_boundary)
        restored = mapping.inverse_map(mapping.map_point(center))
        assert restored is not None
        assert restored.x() == pytest.approx(center.x())
        assert restored.y() == pytest.approx(center.y())


def _boundary_center(boundary: tuple[QPointF, ...]) -> QPointF:
    """Return the arithmetic center of one convex participant boundary."""
    return sum(boundary, QPointF()) * (1.0 / len(boundary))


def test_endpoint_without_collinear_participant_rails_is_disabled() -> None:
    """A visible seam endpoint must not pivot when adjacent edges diverge."""
    first_corners, second_corners = _participant_corners()
    second_corners = (
        second_corners[0],
        QPointF(20.0, 2.0),
        second_corners[2],
        second_corners[3],
    )
    first_edges = quadrilateral_edges(str(uuid.uuid4()), first_corners)
    second_edges = quadrilateral_edges(str(uuid.uuid4()), second_corners)
    seam = shared_edge_seam(
        scene_id=uuid.uuid4(),
        first=first_edges[1],
        second=second_edges[3],
        first_mapping=LayerTransform(),
        second_mapping=LayerTransform(),
        first_boundary=first_corners,
        second_boundary=second_corners,
        coincidence_tolerance=1e-7,
        minimum_overlap=5.0,
    )
    assert seam is not None

    start, end = shared_edge_pivots(
        seam,
        (*first_edges, *second_edges),
        tolerance=1e-7,
    )

    assert start is None
    assert end is not None


def test_endpoint_inserts_shared_opposite_vertex_into_longer_boundary() -> None:
    """A partial seam creates matching topology before its valid corner pivots."""
    first_corners = (
        QPointF(0.0, 0.0),
        QPointF(10.0, 0.0),
        QPointF(10.0, 10.0),
        QPointF(0.0, 10.0),
    )
    second_corners = (
        QPointF(10.0, 0.0),
        QPointF(20.0, 0.0),
        QPointF(20.0, 20.0),
        QPointF(10.0, 20.0),
    )
    first_edges = quadrilateral_edges(str(uuid.uuid4()), first_corners)
    second_edges = quadrilateral_edges(str(uuid.uuid4()), second_corners)
    seam = shared_edge_seam(
        scene_id=uuid.uuid4(),
        first=first_edges[1],
        second=second_edges[3],
        first_mapping=LayerTransform(),
        second_mapping=LayerTransform(),
        first_boundary=first_corners,
        second_boundary=second_corners,
        coincidence_tolerance=1e-7,
        minimum_overlap=5.0,
    )
    assert seam is not None
    assert seam.start == QPointF(10.0, 0.0)
    assert seam.end == QPointF(10.0, 10.0)

    start, end = shared_edge_pivots(
        seam,
        (*first_edges, *second_edges),
        tolerance=1e-7,
    )

    assert start is not None
    assert end is None
    target = start.constrained_point(
        QPointF(12.0, 0.0),
        endpoint_join_span=1.0,
    )
    mappings = dict(start.mappings_for_point(target))
    longer = next(
        participant
        for participant in seam.participants
        if len(participant.scene_boundary) == 5
    )
    mapping = mappings[longer.layer_id]
    assert len(mapping.source_boundary) == 5
    moving_index = longer.scene_boundary.index(start.moving_point)
    assert mapping.map_point(longer.source_boundary[moving_index]) == target
    fixed_index = longer.scene_boundary.index(start.fixed_point)
    assert mapping.map_point(longer.source_boundary[fixed_index]) == start.fixed_point
