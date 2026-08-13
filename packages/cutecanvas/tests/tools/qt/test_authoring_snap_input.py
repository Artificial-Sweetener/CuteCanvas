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

"""Device-parity and exclusion tests for authoring-snap tool ports."""

from __future__ import annotations

import pytest
from cutecanvas.coverage import CoverageDocument, CoverageDocumentEvaluator
from cutecanvas.tools.ports import (
    AuthoringSnapPort,
    PixelSelectionInteractionPort,
    VectorInteractionPort,
)
from cutecanvas.tools.selection_shapes import LassoSelectionTool, RectangleSelectionTool
from cutecanvas.vector.tools import VectorPathTool
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent

from qpane import PointerDeviceKind, PointerPhase, PointerSample


def _sample(
    device: PointerDeviceKind,
    phase: PointerPhase,
    point: QPointF,
) -> PointerSample:
    """Return one normalized direct-pointer observation."""
    return PointerSample(
        pointer_id=7,
        device=device,
        phase=phase,
        position=point,
        global_position=point,
        pressure=1.0,
        buttons=(
            Qt.MouseButton.NoButton
            if phase is PointerPhase.END
            else Qt.MouseButton.LeftButton
        ),
        modifiers=Qt.KeyboardModifier.NoModifier,
        timestamp_ms=0,
    )


@pytest.mark.parametrize(
    "device",
    (PointerDeviceKind.TOUCH, PointerDeviceKind.PEN),
)
def test_direct_pointer_shapes_commit_the_same_snapped_endpoint(
    device: PointerDeviceKind,
) -> None:
    """Touch and tablet shape paths consume the same authoring snap port."""
    commits = []
    clears = 0

    def clear() -> bool:
        """Count completed gesture sessions."""
        nonlocal clears
        clears += 1
        return True

    tool = RectangleSelectionTool()
    tool.activate(
        PixelSelectionInteractionPort(
            panel_to_scene_point=lambda point: QPointF(point),
            commit_coverage_item=lambda item: commits.append(item) or True,
            snapping=AuthoringSnapPort(
                begin=lambda point, _suppressed: QPointF(point),
                update=lambda point, _suppressed, _constrain: QPointF(100.0, point.y()),
                clear=clear,
            ),
        )
    )

    assert tool.handle_pointer_sample(
        _sample(device, PointerPhase.BEGIN, QPointF(20, 20))
    )
    assert tool.handle_pointer_sample(
        _sample(device, PointerPhase.UPDATE, QPointF(96, 50))
    )
    assert tool.handle_pointer_sample(
        _sample(device, PointerPhase.END, QPointF(96, 50))
    )

    assert len(commits) == 1
    bounds = CoverageDocumentEvaluator().content_bounds(
        CoverageDocument().add(commits[0])
    )
    assert bounds is not None and bounds.right == 100
    assert clears == 1


def test_lasso_never_enters_an_authoring_snap_session() -> None:
    """Freehand lasso samples remain raw even when a snap port is installed."""
    calls = []
    commits = []
    tool = LassoSelectionTool()
    tool.activate(
        PixelSelectionInteractionPort(
            panel_to_scene_point=lambda point: QPointF(point),
            commit_coverage_item=lambda item: commits.append(item) or True,
            snapping=AuthoringSnapPort(
                begin=lambda point, suppressed: (
                    calls.append((point, suppressed)) or QPointF(999.0, 999.0)
                ),
                update=lambda point, suppressed, constrain: (
                    calls.append((point, suppressed, constrain))
                    or QPointF(999.0, 999.0)
                ),
            ),
        )
    )

    for phase, point in (
        (PointerPhase.BEGIN, QPointF(2.0, 3.0)),
        (PointerPhase.UPDATE, QPointF(20.0, 3.0)),
        (PointerPhase.UPDATE, QPointF(10.0, 20.0)),
        (PointerPhase.END, QPointF(2.0, 3.0)),
    ):
        assert tool.handle_pointer_sample(_sample(PointerDeviceKind.PEN, phase, point))

    assert calls == []
    assert len(commits) == 1
    assert commits[0].geometry.local_bounds == (2.0, 3.0, 18.0, 17.0)


def test_vector_path_commits_resolved_explicit_anchors() -> None:
    """Every explicit path node uses the active authoring session."""
    commits = []
    update_calls = 0

    def update(point: QPointF, _suppressed: bool, _constrain: bool) -> QPointF:
        """Resolve every subsequent node to one exact vertical line."""
        nonlocal update_calls
        update_calls += 1
        return QPointF(100.0, point.y())

    tool = VectorPathTool()
    tool.activate(
        VectorInteractionPort(
            panel_to_source=lambda point: QPointF(point),
            commit_path=lambda points, closed: commits.append((points, closed)),
            snapping=AuthoringSnapPort(
                begin=lambda point, _suppressed: QPointF(point),
                update=update,
            ),
        )
    )

    for phase, point in (
        (PointerPhase.BEGIN, QPointF(20.0, 20.0)),
        (PointerPhase.END, QPointF(20.0, 20.0)),
        (PointerPhase.BEGIN, QPointF(96.0, 40.0)),
        (PointerPhase.END, QPointF(96.0, 40.0)),
    ):
        assert tool.handle_pointer_sample(
            _sample(PointerDeviceKind.TOUCH, phase, point)
        )
    enter = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.NoModifier)
    tool.keyPressEvent(enter)

    assert enter.isAccepted()
    assert commits == [((QPointF(20.0, 20.0), QPointF(100.0, 40.0)), False)]
    assert update_calls == 1
