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

"""Input-lifecycle proof for the Shared Edge Resize tool."""

from __future__ import annotations

import uuid

import pytest
from cutecanvas.editor.shared_edge_pivot import SharedEdgeHandle
from cutecanvas.editor.shared_edge_presentation import (
    SharedEdgeHandlePresentation,
    SharedEdgePresentation,
)
from cutecanvas.tools.affine_ports import SharedEdgeResizePort
from cutecanvas.tools.shared_edge_resize import SharedEdgeResizeTool
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from qpane import PointerDeviceKind, PointerPhase, PointerSample


def test_mouse_drag_commits_one_coupled_session() -> None:
    """Primary press, motion, and release must use one atomic interaction path."""
    calls: list[str] = []
    tool = SharedEdgeResizeTool()
    tool.activate(_port(calls))

    tool.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, QPointF(50, 0)))
    tool.mouseMoveEvent(
        _mouse(
            QEvent.Type.MouseMove,
            QPointF(55, 5),
            button=Qt.MouseButton.NoButton,
            buttons=Qt.MouseButton.LeftButton,
        )
    )
    tool.mouseReleaseEvent(
        _mouse(
            QEvent.Type.MouseButtonRelease,
            QPointF(55, 5),
            buttons=Qt.MouseButton.NoButton,
        )
    )

    assert calls == ["begin", "update", "finish"]


def test_escape_and_deactivation_clear_transient_state() -> None:
    """Cancellation and tool switching must never leave a partial preview."""
    calls: list[str] = []
    tool = SharedEdgeResizeTool()
    tool.activate(_port(calls))
    tool.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, QPointF(50, 0)))

    tool.keyPressEvent(
        QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Escape,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    tool.deactivate()

    assert calls == ["begin", "cancel", "cancel"]


@pytest.mark.parametrize("device", (PointerDeviceKind.PEN, PointerDeviceKind.TOUCH))
def test_normalized_pointer_drag_uses_atomic_shared_edge_lifecycle(
    device: PointerDeviceKind,
) -> None:
    """Pen and touch input must reach the same paired gesture owner as mouse."""
    calls: list[str] = []
    tool = SharedEdgeResizeTool()
    tool.activate(_port(calls))

    assert tool.handle_pointer_sample(
        _pointer(device, PointerPhase.BEGIN, QPointF(50.0, 0.0))
    )
    assert tool.handle_pointer_sample(
        _pointer(device, PointerPhase.UPDATE, QPointF(55.0, 5.0))
    )
    assert tool.handle_pointer_sample(
        _pointer(device, PointerPhase.END, QPointF(55.0, 5.0))
    )

    assert calls == ["begin", "update", "finish"]


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    (
        (QPointF(50, 0), QPointF(50, 100), Qt.CursorShape.SizeHorCursor),
        (QPointF(0, 50), QPointF(100, 50), Qt.CursorShape.SizeVerCursor),
    ),
)
def test_focused_edge_uses_native_window_resize_cursor(
    start: QPointF,
    end: QPointF,
    expected: Qt.CursorShape,
) -> None:
    """Cursor direction must follow the resize normal using native OS shapes."""
    tool = SharedEdgeResizeTool()
    tool.activate(SharedEdgeResizePort(presentation=lambda: _presentation(start, end)))

    cursor = tool.getCursor()

    assert cursor is not None
    assert cursor.shape() is expected


@pytest.mark.parametrize(
    ("start", "end"),
    (
        (QPointF(0, 0), QPointF(100, 100)),
        (QPointF(0, 100), QPointF(100, 0)),
    ),
)
def test_angled_whole_edge_uses_forbidden_cursor(
    start: QPointF,
    end: QPointF,
) -> None:
    """Angled seam bodies must not advertise dormant parallel translation."""
    tool = SharedEdgeResizeTool()
    tool.activate(
        SharedEdgeResizePort(
            presentation=lambda: _presentation(
                start,
                end,
                middle_enabled=False,
            )
        )
    )

    cursor = tool.getCursor()

    assert cursor is not None
    assert cursor.shape() is Qt.CursorShape.ForbiddenCursor


def test_endpoint_cursor_distinguishes_valid_and_blocked_pivots() -> None:
    """Endpoint hover must advertise a real transform or the native no symbol."""
    valid = SharedEdgeHandlePresentation(
        (uuid.uuid4(), uuid.uuid4()),
        QPointF(50.0, 0.0),
        QPointF(50.0, 100.0),
        start_enabled=True,
        focused_handle=SharedEdgeHandle.START,
        focused_axis=QPointF(1.0, 0.0),
        hovered=True,
    )
    blocked = SharedEdgeHandlePresentation(
        valid.layer_ids,
        valid.start,
        valid.end,
        start_enabled=False,
        focused_handle=SharedEdgeHandle.START,
        hovered=True,
    )
    current = [valid]
    tool = SharedEdgeResizeTool()
    tool.activate(
        SharedEdgeResizePort(
            presentation=lambda: SharedEdgePresentation((current[0],)),
        )
    )

    valid_cursor = tool.getCursor()
    current[0] = blocked
    blocked_cursor = tool.getCursor()

    assert valid_cursor is not None
    assert valid_cursor.shape() is Qt.CursorShape.BitmapCursor
    assert blocked_cursor is not None
    assert blocked_cursor.shape() is Qt.CursorShape.ForbiddenCursor


def _port(calls: list[str]) -> SharedEdgeResizePort:
    """Return an observable port with one eligible seam."""
    return SharedEdgeResizePort(
        presentation=_presentation,
        update_hover=lambda _point: calls.append("hover") or True,
        begin=lambda _point: calls.append("begin") or True,
        update=lambda _point: calls.append("update") or True,
        finish=lambda _point: calls.append("finish") or True,
        cancel=lambda: calls.append("cancel") or True,
    )


def _presentation(
    start: QPointF | None = None,
    end: QPointF | None = None,
    *,
    middle_enabled: bool = True,
) -> SharedEdgePresentation:
    """Return two adjacent participant rectangles and their shared side."""
    seam_start = QPointF(50, 0) if start is None else QPointF(start)
    seam_end = QPointF(50, 100) if end is None else QPointF(end)
    return SharedEdgePresentation(
        (
            SharedEdgeHandlePresentation(
                (uuid.uuid4(), uuid.uuid4()),
                seam_start,
                seam_end,
                middle_enabled=middle_enabled,
                focused_handle=SharedEdgeHandle.MIDDLE,
                hovered=True,
            ),
        ),
    )


def _mouse(
    event_type: QEvent.Type,
    point: QPointF,
    *,
    button: Qt.MouseButton = Qt.MouseButton.LeftButton,
    buttons: Qt.MouseButton = Qt.MouseButton.LeftButton,
) -> QMouseEvent:
    """Build one detached mouse event."""
    return QMouseEvent(
        event_type,
        point,
        point,
        point,
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def _pointer(
    device: PointerDeviceKind,
    phase: PointerPhase,
    point: QPointF,
) -> PointerSample:
    """Build one normalized pen or touch sample."""
    return PointerSample(
        pointer_id=1,
        device=device,
        phase=phase,
        position=point,
        global_position=point,
        pressure=1.0,
        buttons=Qt.MouseButton.LeftButton,
        modifiers=Qt.KeyboardModifier.NoModifier,
        timestamp_ms=0,
    )
