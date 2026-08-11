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

"""Interactive contract proof for unfinished polygon coverage authoring."""

from __future__ import annotations

from cutecanvas.edit_sessions import EditSessionKind
from cutecanvas.editor.session_coordination import EditSessionCoordinator
from cutecanvas.tools.polygon_coverage import PolygonCoverageTool
from cutecanvas.tools.ports import PixelSelectionInteractionPort
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from qpane.sdk.vector import VectorPathCommandKind


def test_prior_vertex_can_be_dragged_then_authoring_continues() -> None:
    """Placed geometry must remain editable without closing the open polygon."""
    commits = []
    tool = _tool(commits)
    _click(tool, QPointF(0.0, 0.0))
    _click(tool, QPointF(10.0, 0.0))
    _click(tool, QPointF(10.0, 10.0))

    _drag(tool, QPointF(0.0, 0.0), QPointF(-2.0, 1.0))
    _click(tool, QPointF(0.0, 10.0))
    _key(tool, Qt.Key.Key_Return)

    assert len(commits) == 1
    assert _path_points(commits[0]) == (
        QPointF(-2.0, 1.0),
        QPointF(10.0, 0.0),
        QPointF(10.0, 10.0),
        QPointF(0.0, 10.0),
    )


def test_segment_press_inserts_and_drags_before_more_points_are_added() -> None:
    """One press-drag on an established edge must insert a revisable vertex."""
    commits = []
    tool = _tool(commits)
    _click(tool, QPointF(0.0, 0.0))
    _click(tool, QPointF(20.0, 0.0))
    _click(tool, QPointF(20.0, 20.0))

    _drag(tool, QPointF(10.0, 0.0), QPointF(10.0, 4.0))
    _click(tool, QPointF(0.0, 20.0))
    _key(tool, Qt.Key.Key_Enter)

    assert len(commits) == 1
    assert _path_points(commits[0]) == (
        QPointF(0.0, 0.0),
        QPointF(10.0, 4.0),
        QPointF(20.0, 0.0),
        QPointF(20.0, 20.0),
        QPointF(0.0, 20.0),
    )


def test_clicking_first_vertex_finishes_once() -> None:
    """The first vertex is a close affordance rather than another duplicate."""
    commits = []
    tool = _tool(commits)
    for point in (QPointF(), QPointF(10.0, 0.0), QPointF(10.0, 10.0)):
        _click(tool, point)

    _click(tool, QPointF())

    assert len(commits) == 1
    assert not tool.authoring


def test_double_click_finishes_valid_unclosed_geometry() -> None:
    """Double click must publish the current valid vertices exactly once."""
    commits = []
    tool = _tool(commits)
    for point in (QPointF(), QPointF(10.0, 0.0), QPointF(10.0, 10.0)):
        _click(tool, point)

    tool.mouseDoubleClickEvent(
        _mouse(QEvent.Type.MouseButtonDblClick, QPointF(10.0, 10.0), True)
    )

    assert len(commits) == 1
    assert not tool.authoring


def test_delete_removes_selected_prior_vertex_before_finish() -> None:
    """Delete must remove a selected earlier vertex without ending authorship."""
    commits = []
    tool = _tool(commits)
    for point in (
        QPointF(),
        QPointF(10.0, 0.0),
        QPointF(10.0, 10.0),
        QPointF(0.0, 10.0),
    ):
        _click(tool, point)

    _click(tool, QPointF(10.0, 0.0))
    _key(tool, Qt.Key.Key_Delete)
    _key(tool, Qt.Key.Key_Enter)

    assert len(commits) == 1
    assert _path_points(commits[0]) == (
        QPointF(),
        QPointF(10.0, 10.0),
        QPointF(0.0, 10.0),
    )


def test_escape_discards_every_unfinished_revision() -> None:
    """Cancelling after point edits must publish no coverage or history request."""
    commits = []
    tool = _tool(commits)
    _click(tool, QPointF())
    _click(tool, QPointF(10.0, 0.0))
    _drag(tool, QPointF(), QPointF(2.0, 1.0))

    _key(tool, Qt.Key.Key_Escape)

    assert not commits
    assert not tool.authoring


def test_polygon_checkpoints_restore_topology_before_publication() -> None:
    """Unified Undo and Redo must revise open geometry without document edits."""
    commits: list[object] = []
    tool, sessions = _tool_with_sessions(commits)
    for point in (QPointF(0.0, 0.0), QPointF(10.0, 0.0)):
        _click(tool, point)
    assert sessions.snapshot is not None
    assert not sessions.snapshot.can_apply
    assert sessions.snapshot.can_cancel

    _click(tool, QPointF(10.0, 10.0))
    assert sessions.snapshot is not None and sessions.snapshot.can_apply
    _click(tool, QPointF(0.0, 10.0))

    assert sessions.snapshot is not None
    assert sessions.snapshot.undo_depth == 4
    assert sessions.undo(lambda: (_ for _ in ()).throw(AssertionError()))
    assert sessions.redo(lambda: (_ for _ in ()).throw(AssertionError()))
    assert sessions.undo(lambda: False)
    _key(tool, Qt.Key.Key_Return)

    assert len(commits) == 1
    assert _path_points(commits[0]) == (
        QPointF(0.0, 0.0),
        QPointF(10.0, 0.0),
        QPointF(10.0, 10.0),
    )


def _tool(commits: list[object]) -> PolygonCoverageTool:
    """Return one identity-projected polygon tool with a recording destination."""
    return _tool_with_sessions(commits)[0]


def _tool_with_sessions(
    commits: list[object],
) -> tuple[PolygonCoverageTool, EditSessionCoordinator]:
    """Return one polygon tool and its authoritative session coordinator."""
    sessions = EditSessionCoordinator(changed=lambda _state: None)
    tool = PolygonCoverageTool()
    tool.activate(
        PixelSelectionInteractionPort(
            panel_to_scene_point=lambda point: QPointF(point),
            commit_coverage_item=lambda item: commits.append(item) or True,
            edit_sessions=sessions,
            edit_session_kind=EditSessionKind.POLYGON_SELECTION,
            edit_session_tool_mode="select-polygon",
        )
    )
    return tool, sessions


def _click(tool: PolygonCoverageTool, point: QPointF) -> None:
    """Deliver one primary-button click."""
    tool.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, point, True))
    tool.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, point, False))


def _drag(tool: PolygonCoverageTool, start: QPointF, end: QPointF) -> None:
    """Deliver one primary-button drag."""
    tool.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, start, True))
    tool.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, end, True))
    tool.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, end, False))


def _mouse(event_type: QEvent.Type, point: QPointF, down: bool) -> QMouseEvent:
    """Build one detached mouse event."""
    return QMouseEvent(
        event_type,
        point,
        point,
        point,
        (
            Qt.MouseButton.LeftButton
            if event_type != QEvent.Type.MouseMove
            else Qt.MouseButton.NoButton
        ),
        Qt.MouseButton.LeftButton if down else Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _key(tool: PolygonCoverageTool, key: Qt.Key) -> None:
    """Deliver one key press to the active authoring session."""
    tool.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.NoModifier))


def _path_points(item: object) -> tuple[QPointF, ...]:
    """Return ordered anchor points from one committed polygon item."""
    return tuple(
        command.points[-1]
        for command in item.geometry.path
        if command.kind in {VectorPathCommandKind.MOVE, VectorPathCommandKind.LINE}
    )
