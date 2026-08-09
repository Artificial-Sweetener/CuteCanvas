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

"""Qt presentation proof for concise shared-edge manipulation feedback."""

from __future__ import annotations

import uuid

from cutecanvas.editor.shared_edge_presentation import (
    SharedEdgeHandlePresentation,
    SharedEdgePresentation,
)
from cutecanvas.ui.shared_edge import SharedEdgeRenderer
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, QPainter


def test_shared_edge_feedback_draws_no_line_to_unmatched_participant_corner(
    qapp,
) -> None:
    """The overlay contains only the shared seam and its manipulation handles."""
    del qapp
    image = QImage(140, 140, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    presentation = SharedEdgePresentation(
        (
            SharedEdgeHandlePresentation(
                (uuid.uuid4(), uuid.uuid4()),
                QPointF(50.0, 20.0),
                QPointF(50.0, 100.0),
                hovered=True,
            ),
        )
    )
    painter = QPainter(image)
    try:
        SharedEdgeRenderer().draw(painter, presentation)
    finally:
        painter.end()

    assert image.pixelColor(50, 60).alpha() > 0
    assert image.pixelColor(75, 120).alpha() == 0
