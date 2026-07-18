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

"""Tests for tool manager lifecycle and error handling."""

import logging

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from qpane.tools import ToolDependencies
from qpane.tools.base import BaseTool, CursorTool, ExtensionTool, PanZoomTool
from qpane.tools.tools import Tools

pytestmark = [
    pytest.mark.filterwarnings("ignore:Failed to disconnect.*"),
    pytest.mark.filterwarnings("ignore:.*QMouseEvent.*deprecated.*:DeprecationWarning"),
]


class DummyTool(BaseTool):
    def __init__(self):
        super().__init__()
        self.activated = False
        self.deactivated = False
        self.received_dependencies = None

    def activate(self, dependencies: ToolDependencies) -> None:
        self.activated = True
        self.received_dependencies = dependencies

    def deactivate(self):
        self.deactivated = True

    def mousePressEvent(self, event):
        return None

    def mouseMoveEvent(self, event):
        return None

    def mouseReleaseEvent(self, event):
        return None

    def wheelEvent(self, event):
        return None


class EmptyTool(ExtensionTool):
    def __init__(self) -> None:
        super().__init__()


def test_extension_tool_defaults_are_inert(qapp):
    manager = Tools()
    manager.registerTool("empty", EmptyTool)
    manager.set_mode("empty", ToolDependencies())
    tool = manager.get_active_tool()
    assert isinstance(tool, EmptyTool)

    class DummyEvent:
        def __init__(self) -> None:
            self.ignored = False

        def ignore(self) -> None:
            self.ignored = True

    mouse_event = DummyEvent()
    wheel_event = DummyEvent()
    enter_event = DummyEvent()
    leave_event = DummyEvent()

    manager.mousePressEvent(mouse_event)
    manager.mouseMoveEvent(DummyEvent())
    manager.mouseReleaseEvent(DummyEvent())
    manager.mouseDoubleClickEvent(DummyEvent())
    manager.wheelEvent(wheel_event)
    manager.enterEvent(enter_event)
    manager.leaveEvent(leave_event)
    manager.keyPressEvent(DummyEvent())
    manager.keyReleaseEvent(DummyEvent())
    manager.draw_overlay(object())

    assert mouse_event.ignored is True
    assert wheel_event.ignored is True
    assert enter_event.ignored is True
    assert leave_event.ignored is True


def test_tool_manager_register_and_unregister(qapp):
    manager = Tools()
    events = []

    def on_connect(signals, tool):
        events.append("connected")
        assert isinstance(tool, DummyTool)

    def on_disconnect(signals, tool):
        events.append("disconnected")
        assert isinstance(tool, DummyTool)

    manager.registerTool(
        "inspect",
        DummyTool,
        on_connect=on_connect,
        on_disconnect=on_disconnect,
    )
    manager.set_mode("inspect", ToolDependencies())
    assert "connected" in events
    assert isinstance(manager.get_active_tool(), DummyTool)
    with pytest.raises(RuntimeError):
        manager.unregisterTool("inspect")
    manager.set_mode(manager.CONTROL_MODE_PANZOOM, ToolDependencies())
    manager.unregisterTool("inspect")
    assert "disconnected" in events
    assert manager.get_active_tool() is not None


def test_tool_manager_rejects_duplicate_mode_registration(qapp):
    manager = Tools()
    manager.registerTool("duplicate", DummyTool)
    with pytest.raises(ValueError):
        manager.registerTool("duplicate", DummyTool)


def test_tool_manager_swallows_tool_exception(qapp, caplog):
    manager = Tools()

    class ExplodingTool(BaseTool):
        def __init__(self):
            super().__init__()

        def activate(self, dependencies: ToolDependencies) -> None:
            return None

        def deactivate(self):
            return None

        def mousePressEvent(self, event):
            raise RuntimeError("boom")

        def mouseMoveEvent(self, event):
            return None

        def mouseReleaseEvent(self, event):
            return None

        def wheelEvent(self, event):
            return None

    manager.registerTool("exploding", ExplodingTool)
    manager.set_mode("exploding", ToolDependencies())
    caplog.clear()
    with caplog.at_level(logging.ERROR):
        manager.mousePressEvent(object())
    assert any(
        record.levelname == "ERROR"
        and "Tool 'exploding' raised during mousePressEvent" in record.getMessage()
        for record in caplog.records
    )


def test_tool_manager_logs_disconnect_warning(qapp, caplog, monkeypatch):
    manager = Tools()

    class WarnTool(BaseTool):
        def __init__(self):
            super().__init__()

        def activate(self, dependencies: ToolDependencies) -> None:
            return None

        def deactivate(self):
            return None

        def mousePressEvent(self, event):
            return None

        def mouseMoveEvent(self, event):
            return None

        def mouseReleaseEvent(self, event):
            return None

        def wheelEvent(self, event):
            return None

    manager.registerTool("warn", WarnTool)
    manager.set_mode("warn", ToolDependencies())
    signal = manager.get_active_tool().signals.cursor_update_requested
    signal_cls = type(signal)
    original_disconnect = signal_cls.disconnect

    def boom(self, slot):  # pragma: no cover - exercised via manager disconnect
        raise TypeError("already disconnected")

    monkeypatch.setattr(signal_cls, "disconnect", boom, raising=False)
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        manager.set_mode(manager.CONTROL_MODE_PANZOOM, ToolDependencies())
    assert any(
        record.levelname == "WARNING"
        and "Failed to disconnect signal" in record.getMessage()
        and "warn" in record.getMessage()
        for record in caplog.records
    )
    monkeypatch.setattr(signal_cls, "disconnect", original_disconnect, raising=False)
    manager.unregisterTool("warn")


def test_cursor_tool_is_registered_and_inert(qapp):
    manager = Tools()
    manager.set_mode(
        Tools.CONTROL_MODE_CURSOR,
        ToolDependencies(
            is_drag_out_allowed=lambda: True,
            is_image_null=lambda: False,
        ),
    )
    tool = manager.get_active_tool()
    assert isinstance(tool, CursorTool)
    assert tool.getCursor().shape() == Qt.CursorShape.ArrowCursor
    assert manager.get_control_mode() == Tools.CONTROL_MODE_CURSOR
    assert tool._is_drag_out_allowed()
    assert not tool._is_image_null()
    assert tool._drag_start_pos is None
    manager_drag_events = []
    tool_drag_events = []
    manager.signals.drag_start_maybe_requested.connect(manager_drag_events.append)
    tool.signals.drag_start_maybe_requested.connect(tool_drag_events.append)
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(0, 0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    tool.mousePressEvent(press)
    assert tool._drag_start_pos is not None
    start_distance = QApplication.instance().startDragDistance()
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(start_distance + 1, 0),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert (
        move.position().toPoint() - tool._drag_start_pos
    ).manhattanLength() >= start_distance
    tool.mouseMoveEvent(move)
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(0, 0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    tool.mouseReleaseEvent(release)
    tool.mouseDoubleClickEvent(press)
    tool.wheelEvent(move)
    assert tool_drag_events, "Cursor tool should emit drag-out attempts"
    assert manager_drag_events, "Cursor tool drag-out should reach manager signals"


def test_panzoom_tool_emits_drag_out_via_shared_path(qapp):
    manager = Tools()
    manager.set_mode(
        Tools.CONTROL_MODE_PANZOOM,
        ToolDependencies(
            is_pan_zoom_locked=lambda: False,
            is_image_null=lambda: False,
            is_drag_out_allowed=lambda: True,
        ),
    )
    tool = manager.get_active_tool()
    assert isinstance(tool, PanZoomTool)
    manager_drag_events = []
    tool_drag_events = []
    manager.signals.drag_start_maybe_requested.connect(manager_drag_events.append)
    tool.signals.drag_start_maybe_requested.connect(tool_drag_events.append)
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(0, 0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    tool.mousePressEvent(press)
    assert tool.drag_start_pos is not None
    start_distance = QApplication.instance().startDragDistance()
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(start_distance + 1, 0),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    tool.mouseMoveEvent(move)
    assert tool.drag_start_pos is None
    assert tool_drag_events, "Pan/zoom tool should emit drag-out attempts"
    assert manager_drag_events, "Pan/zoom drag-out should reach manager signals"
