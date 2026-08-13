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

"""Finite-boundary constraints for shared-edge midpoint translation."""

from __future__ import annotations

import uuid

import pytest
from PySide6.QtCore import QPointF

from cutecanvas.editor.shared_edge_geometry import shared_edge_seam
from cutecanvas.snapping.edge_model import polygon_edges
from qpane.sdk.scene import PiecewiseLayerTransform


def test_skewed_seam_crosses_remote_vertex_projection_before_collision() -> None:
    """A finite diagonal seam may move rightward while both cages stay valid."""
    left_source = _points(
        (226.5693, 127.4453),
        (630.6569, 127.4453),
        (630.6569, 825.8394),
        (226.5693, 825.8394),
    )
    left_target = _points(
        (226.5693, 127.4453),
        (633.2730, 127.0690),
        (733.7110, 825.4630),
        (226.5693, 825.8394),
    )
    right_source = _points(
        (630.6569, 76.0584),
        (960.0, 76.0584),
        (960.0, 825.8394),
        (630.6569, 825.8394),
        (630.6569, 127.4453),
    )
    right_target = _points(
        (630.6569, 76.0584),
        (960.0, 76.0584),
        (960.0, 825.8394),
        (733.7110, 825.4630),
        (633.2730, 127.0690),
    )
    left_id = uuid.uuid4()
    right_id = uuid.uuid4()
    left_edges = polygon_edges(str(left_id), left_target)
    right_edges = polygon_edges(str(right_id), right_target)
    seam = shared_edge_seam(
        scene_id=uuid.uuid4(),
        first=left_edges[1],
        second=right_edges[3],
        first_mapping=PiecewiseLayerTransform(left_source, left_target),
        second_mapping=PiecewiseLayerTransform(right_source, right_target),
        first_boundary=left_target,
        second_boundary=right_target,
        coincidence_tolerance=1e-3,
        minimum_overlap=5.0,
    )
    assert seam is not None

    translation = seam.translation_for_distance(-100.0, minimum_thickness=2.0)

    assert translation.distance == pytest.approx(-100.0)
    displacement = seam.edge.normal * translation.distance
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
            assert mapping.map_point(source) == expected


def test_partial_overlap_moves_the_contiguous_collinear_extension() -> None:
    """A longer straight participant edge must translate without forming a kink."""
    left_boundary = _points(
        (0.0, 2.0),
        (10.0, 2.0),
        (10.0, 10.0),
        (0.0, 10.0),
    )
    right_boundary = _points(
        (10.0, 0.0),
        (20.0, 0.0),
        (20.0, 10.0),
        (10.0, 10.0),
    )
    left_id = uuid.uuid4()
    right_id = uuid.uuid4()
    seam = shared_edge_seam(
        scene_id=uuid.uuid4(),
        first=polygon_edges(str(left_id), left_boundary)[1],
        second=polygon_edges(str(right_id), right_boundary)[3],
        first_mapping=PiecewiseLayerTransform(left_boundary, left_boundary),
        second_mapping=PiecewiseLayerTransform(right_boundary, right_boundary),
        first_boundary=left_boundary,
        second_boundary=right_boundary,
        coincidence_tolerance=1e-7,
        minimum_overlap=5.0,
    )
    assert seam is not None

    translation = seam.translation_for_distance(-2.0, minimum_thickness=0.1)
    right = next(
        participant
        for participant in seam.participants
        if participant.layer_id == right_id
    )
    mapping = dict(translation.mappings)[right_id]
    displacement = seam.edge.normal * translation.distance
    extension_index = right.scene_boundary.index(QPointF(10.0, 0.0))
    inserted_index = right.scene_boundary.index(QPointF(10.0, 2.0))
    seam_end_index = right.scene_boundary.index(QPointF(10.0, 10.0))

    assert {extension_index, inserted_index, seam_end_index}.issubset(
        right.translation_indexes
    )
    for index, (source, initial) in enumerate(
        zip(right.source_boundary, right.scene_boundary, strict=True)
    ):
        expected = (
            initial + displacement if index in right.translation_indexes else initial
        )
        assert mapping.map_point(source) == expected


def _points(*coordinates: tuple[float, float]) -> tuple[QPointF, ...]:
    """Return detached points for one recorded finite cage."""
    return tuple(QPointF(x, y) for x, y in coordinates)
