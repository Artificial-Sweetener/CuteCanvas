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

"""Open-session topology proof for deliberate polygon coverage authoring."""

from __future__ import annotations

from cutecanvas.tools.polygon_coverage_session import PolygonCoverageSession
from PySide6.QtCore import QPointF


def test_earlier_vertex_can_move_before_polygon_is_finished() -> None:
    """Revising placed geometry must not end or redirect the open endpoint."""
    session = PolygonCoverageSession()
    first = session.append(QPointF(0.0, 0.0))
    session.append(QPointF(10.0, 0.0))
    endpoint = session.append(QPointF(10.0, 10.0))

    assert session.move(first, QPointF(-2.0, 1.0))
    appended = session.append(QPointF(0.0, 10.0))

    assert session.vertex_ids == (first, session.vertex_ids[1], endpoint, appended)
    assert session.points == (
        QPointF(-2.0, 1.0),
        QPointF(10.0, 0.0),
        QPointF(10.0, 10.0),
        QPointF(0.0, 10.0),
    )
    assert session.open_endpoint_id == appended


def test_inserting_between_neighbors_preserves_open_endpoint() -> None:
    """An interior insertion must preserve order and continued authoring state."""
    session = PolygonCoverageSession()
    first = session.append(QPointF(0.0, 0.0))
    second = session.append(QPointF(10.0, 0.0))
    endpoint = session.append(QPointF(10.0, 10.0))

    inserted = session.insert_after(first, QPointF(5.0, 2.0))

    assert session.vertex_ids == (first, inserted, second, endpoint)
    assert session.points[1] == QPointF(5.0, 2.0)
    assert session.open_endpoint_id == endpoint


def test_removing_an_earlier_vertex_keeps_valid_open_geometry() -> None:
    """Deleting a selected prior point must leave the unfinished chain usable."""
    session = PolygonCoverageSession()
    first = session.append(QPointF(0.0, 0.0))
    removed = session.append(QPointF(5.0, 0.0))
    session.append(QPointF(10.0, 0.0))
    endpoint = session.append(QPointF(10.0, 10.0))

    assert session.remove(removed)
    session.append(QPointF(0.0, 10.0))

    assert removed not in session.vertex_ids
    assert session.vertex_ids[0] == first
    assert session.vertex_ids[2] == endpoint
    assert session.can_finish


def test_duplicate_and_nonfinite_vertices_are_rejected() -> None:
    """Invalid authored topology must fail before it reaches coverage geometry."""
    session = PolygonCoverageSession()
    session.append(QPointF(1.0, 2.0))

    try:
        session.append(QPointF(1.0, 2.0))
    except ValueError as error:
        assert str(error) == "polygon vertices must be distinct"
    else:
        raise AssertionError("duplicate polygon vertex was accepted")

    try:
        session.append(QPointF(float("nan"), 2.0))
    except ValueError as error:
        assert str(error) == "polygon vertices must be finite"
    else:
        raise AssertionError("non-finite polygon vertex was accepted")
