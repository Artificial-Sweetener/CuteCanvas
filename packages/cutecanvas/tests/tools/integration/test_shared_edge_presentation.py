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

"""Projection contracts for distinct shared-edge group carriers."""

from __future__ import annotations

import uuid
from dataclasses import replace

from PySide6.QtCore import QPointF

from cutecanvas.editor.shared_edge_geometry import SharedEdgeSeam, shared_edge_seam
from cutecanvas.editor.shared_edge_presentation import SharedEdgePresentationProjector
from cutecanvas.snapping.edge_model import OrientedEdge
from qpane.sdk.scene import LayerTransform


def test_focus_distinguishes_carriers_with_the_same_participants() -> None:
    """A four-way grid must focus only the hovered horizontal or vertical seam."""
    vertical = _vertical_seam()
    horizontal_edge = OrientedEdge(
        vertical.edge.owner_id,
        QPointF(0.0, 0.0),
        QPointF(10.0, 0.0),
        QPointF(5.0, -5.0),
    )
    horizontal = replace(
        vertical,
        edge=horizontal_edge,
        overlap_start=0.0,
        overlap_end=10.0,
    )
    projector = SharedEdgePresentationProjector(scene_to_panel=QPointF)

    presentation = projector.project(
        (vertical, horizontal),
        focused=vertical,
        focused_points=None,
        focused_handle=None,
        pivot_for=lambda _seam: (None, None),
        active=False,
    )

    assert len(presentation.edges) == 2
    assert sum(edge.hovered for edge in presentation.edges) == 1
    focused = presentation.focused_edge
    assert focused is not None
    assert focused.start == vertical.start
    assert focused.end == vertical.end


def _vertical_seam() -> SharedEdgeSeam:
    """Return one exact seam with two rectangular participants."""
    first_id = str(uuid.uuid4())
    second_id = str(uuid.uuid4())
    first_boundary = (
        QPointF(0.0, 0.0),
        QPointF(10.0, 0.0),
        QPointF(10.0, 10.0),
        QPointF(0.0, 10.0),
    )
    second_boundary = (
        QPointF(10.0, 0.0),
        QPointF(20.0, 0.0),
        QPointF(20.0, 10.0),
        QPointF(10.0, 10.0),
    )
    seam = shared_edge_seam(
        scene_id=uuid.uuid4(),
        first=OrientedEdge(
            first_id,
            QPointF(10.0, 0.0),
            QPointF(10.0, 10.0),
            QPointF(5.0, 5.0),
        ),
        second=OrientedEdge(
            second_id,
            QPointF(10.0, 10.0),
            QPointF(10.0, 0.0),
            QPointF(15.0, 5.0),
        ),
        first_mapping=LayerTransform(),
        second_mapping=LayerTransform(),
        first_boundary=first_boundary,
        second_boundary=second_boundary,
        coincidence_tolerance=1e-7,
        minimum_overlap=5.0,
    )
    assert seam is not None
    return seam
