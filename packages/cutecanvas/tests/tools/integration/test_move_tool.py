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

"""Tests for generic scene-layer direct movement input."""

from __future__ import annotations

import pytest
from cutecanvas.cursor import EditorCursorIntent
from cutecanvas.tools.move import MoveTool
from cutecanvas.tools.ports import MoveInteractionPort
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from qpane import PointerDeviceKind, PointerPhase, PointerSample


def _sample(
    phase: PointerPhase,
    point: QPointF,
    device: PointerDeviceKind = PointerDeviceKind.TOUCH,
    modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
) -> PointerSample:
    """Build one normalized touch sample for move-tool tests."""
    return PointerSample(
        pointer_id=1,
        device=device,
        phase=phase,
        position=point,
        global_position=point,
        pressure=1.0,
        buttons=Qt.MouseButton.LeftButton,
        modifiers=modifiers,
        timestamp_ms=0,
    )


def _mouse_event(
    event_type: QEvent.Type,
    point: QPointF,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
) -> QMouseEvent:
    """Build one mouse event for direct movement tests."""
    return QMouseEvent(
        event_type,
        point,
        point,
        point,
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


@pytest.mark.parametrize(
    "device",
    (PointerDeviceKind.TOUCH, PointerDeviceKind.PEN),
)
def test_move_tool_routes_normalized_sequence_through_generic_operations(
    device: PointerDeviceKind,
) -> None:
    """Touch and tablet samples should share one movement operation path."""
    calls: list[tuple[str, QPointF | None]] = []
    tool = MoveTool()
    tool.activate(
        MoveInteractionPort(
            begin_move=lambda point, _copy, _extend, _toggle: (
                calls.append(("begin", point)) or True
            ),
            update_move=lambda point, _suppress: (
                calls.append(("update", point)) or True
            ),
            finish_move=lambda point, _suppress: (
                calls.append(("finish", point)) or True
            ),
            cancel_move=lambda: calls.append(("cancel", None)) or True,
        )
    )

    assert tool.input_profile.touch
    assert tool.input_profile.tablet
    assert tool.handle_pointer_sample(
        _sample(PointerPhase.BEGIN, QPointF(5, 6), device)
    )
    assert tool.handle_pointer_sample(
        _sample(PointerPhase.UPDATE, QPointF(8, 10), device)
    )
    assert tool.handle_pointer_sample(_sample(PointerPhase.END, QPointF(9, 12), device))
    assert calls == [
        ("begin", QPointF(5, 6)),
        ("update", QPointF(8, 10)),
        ("finish", QPointF(9, 12)),
    ]


def test_move_tool_forwards_alt_as_copy_intent() -> None:
    """Alt at lift time should request a non-destructive floating copy."""
    copy_intents: list[bool] = []
    tool = MoveTool()
    tool.activate(
        MoveInteractionPort(
            begin_move=lambda _point, copy, _extend, _toggle: (
                copy_intents.append(copy) or True
            ),
        )
    )

    assert tool.handle_pointer_sample(
        _sample(
            PointerPhase.BEGIN,
            QPointF(4, 5),
            modifiers=Qt.KeyboardModifier.AltModifier,
        )
    )

    assert copy_intents == [True]


def test_move_tool_suspends_pointer_sequence_without_cancelling_floating_edit() -> None:
    """Temporary tool changes must release input without discarding editor state."""
    cancelled: list[bool] = []
    suspended: list[bool] = []
    tool = MoveTool()
    tool.activate(
        MoveInteractionPort(
            begin_move=lambda _point, _copy, _extend, _toggle: True,
            cancel_move=lambda: cancelled.append(True) or True,
            suspend_move=lambda: suspended.append(True) or True,
        )
    )

    assert tool.handle_pointer_sample(_sample(PointerPhase.BEGIN, QPointF()))
    tool.deactivate()

    assert suspended == [True]
    assert cancelled == []


def test_move_tool_routes_mouse_drag_through_same_operations() -> None:
    """Mouse press, move, and release should preview and commit one movement."""
    calls: list[str] = []
    tool = MoveTool()
    tool.activate(
        MoveInteractionPort(
            begin_move=lambda _point, _copy, _extend, _toggle: (
                calls.append("begin") or True
            ),
            update_move=lambda _point, _suppress: calls.append("update") or True,
            finish_move=lambda _point, _suppress: calls.append("finish") or True,
        )
    )
    press = _mouse_event(
        QEvent.Type.MouseButtonPress,
        QPointF(2, 3),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
    )
    move = _mouse_event(
        QEvent.Type.MouseMove,
        QPointF(5, 7),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
    )
    release = _mouse_event(
        QEvent.Type.MouseButtonRelease,
        QPointF(5, 7),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
    )

    tool.mousePressEvent(press)
    tool.mouseMoveEvent(move)
    tool.mouseReleaseEvent(release)

    assert calls == ["begin", "update", "finish"]
    assert press.isAccepted()
    assert move.isAccepted()
    assert release.isAccepted()


def test_move_tool_uses_four_direction_cursor_during_drag() -> None:
    """Move mode should retain its four-direction cursor while active."""
    tool = MoveTool()
    tool.activate(
        MoveInteractionPort(
            begin_move=lambda _point, _copy, _extend, _toggle: True,
            move_target_available=lambda: True,
        )
    )
    assert tool.getCursor().shape() == Qt.CursorShape.SizeAllCursor

    assert tool.handle_pointer_sample(_sample(PointerPhase.BEGIN, QPointF()))

    assert tool.getCursor().shape() == Qt.CursorShape.SizeAllCursor


def test_move_tool_updates_hover_without_starting_a_drag() -> None:
    """Pointer motion should preview its movable target until the widget is left."""
    hovered: list[QPointF] = []
    cleared: list[bool] = []
    tool = MoveTool()
    tool.activate(
        MoveInteractionPort(
            update_move_hover=lambda point: hovered.append(point) or True,
            clear_move_hover=lambda: cleared.append(True) or True,
        )
    )
    move = _mouse_event(
        QEvent.Type.MouseMove,
        QPointF(7.0, 9.0),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
    )

    tool.mouseMoveEvent(move)
    tool.leaveEvent(QEvent(QEvent.Type.Leave))

    assert hovered == [QPointF(7.0, 9.0)]
    assert cleared == [True]


def test_move_tool_constrains_shift_drag_to_nearest_45_degree_axis() -> None:
    """Shift should constrain pointer movement without changing editor ownership."""
    updates: list[QPointF] = []
    tool = MoveTool()
    tool.activate(
        MoveInteractionPort(
            begin_move=lambda _point, _copy, _extend, _toggle: True,
            update_move=lambda point, _suppress: updates.append(point) or True,
        )
    )

    assert tool.handle_pointer_sample(_sample(PointerPhase.BEGIN, QPointF(2, 3)))
    assert tool.handle_pointer_sample(
        _sample(
            PointerPhase.UPDATE,
            QPointF(12, 5),
            modifiers=Qt.KeyboardModifier.ShiftModifier,
        )
    )

    assert updates[0].y() == pytest.approx(3.0)
    assert updates[0].x() > 12.0


def test_move_tool_nudges_one_or_ten_pixels_with_arrow_keys() -> None:
    """Arrow keys should use standard one-pixel and Shift ten-pixel increments."""
    nudges: list[tuple[int, int]] = []
    tool = MoveTool()
    tool.activate(
        MoveInteractionPort(nudge_move=lambda x, y: nudges.append((x, y)) or True)
    )
    right = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Right,
        Qt.KeyboardModifier.NoModifier,
    )
    up_fast = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Up,
        Qt.KeyboardModifier.ShiftModifier,
    )

    tool.keyPressEvent(right)
    tool.keyPressEvent(up_fast)

    assert right.isAccepted()
    assert up_fast.isAccepted()
    assert nudges == [(1, 0), (0, -10)]


def test_move_tool_resolves_or_cancels_released_floating_pixels() -> None:
    """Enter and Escape should act on a floating edit after pointer release."""
    actions: list[str] = []
    tool = MoveTool()
    tool.activate(
        MoveInteractionPort(
            anchor_move=lambda: actions.append("anchor") or True,
            cancel_move=lambda: actions.append("cancel") or True,
        )
    )
    enter = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.NoModifier,
    )
    escape = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Escape,
        Qt.KeyboardModifier.NoModifier,
    )

    tool.keyPressEvent(enter)
    tool.keyPressEvent(escape)

    assert enter.isAccepted()
    assert escape.isAccepted()
    assert actions == ["anchor", "cancel"]


def test_move_tool_delegates_semantic_cursor_to_movement_resolver() -> None:
    """Cursor artwork must consume the authoritative selected-pixel hover result."""
    intent = EditorCursorIntent.MOVE_CUT
    tool = MoveTool()
    tool.activate(MoveInteractionPort(move_cursor_intent=lambda: intent))

    assert tool.cursor_intent() is EditorCursorIntent.MOVE_CUT
