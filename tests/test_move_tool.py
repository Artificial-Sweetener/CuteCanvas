#    QPane - High-performance PySide6 image viewer
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
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from qpane.tools import ToolDependencies
from qpane.tools.input import PointerDeviceKind, PointerPhase, PointerSample
from qpane.tools.move import MoveTool


def _sample(
    phase: PointerPhase,
    point: QPointF,
    device: PointerDeviceKind = PointerDeviceKind.TOUCH,
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
        modifiers=Qt.KeyboardModifier.NoModifier,
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
        ToolDependencies(
            begin_layer_move=lambda point: calls.append(("begin", point)) or True,
            update_layer_move=lambda point: calls.append(("update", point)) or True,
            finish_layer_move=lambda point: calls.append(("finish", point)) or True,
            cancel_layer_move=lambda: calls.append(("cancel", None)) or True,
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


def test_move_tool_cancels_transient_sequence_on_deactivation() -> None:
    """Changing tools should discard preview state without a placement commit."""
    cancelled: list[bool] = []
    tool = MoveTool()
    tool.activate(
        ToolDependencies(
            begin_layer_move=lambda _point: True,
            cancel_layer_move=lambda: cancelled.append(True) or True,
        )
    )

    assert tool.handle_pointer_sample(_sample(PointerPhase.BEGIN, QPointF()))
    tool.deactivate()

    assert cancelled == [True]


def test_move_tool_routes_mouse_drag_through_same_operations() -> None:
    """Mouse press, move, and release should preview and commit one movement."""
    calls: list[str] = []
    tool = MoveTool()
    tool.activate(
        ToolDependencies(
            begin_layer_move=lambda _point: calls.append("begin") or True,
            update_layer_move=lambda _point: calls.append("update") or True,
            finish_layer_move=lambda _point: calls.append("finish") or True,
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
    tool.activate(ToolDependencies(begin_layer_move=lambda _point: True))
    assert tool.getCursor().shape() == Qt.CursorShape.SizeAllCursor

    assert tool.handle_pointer_sample(_sample(PointerPhase.BEGIN, QPointF()))

    assert tool.getCursor().shape() == Qt.CursorShape.SizeAllCursor
