#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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
from cutecanvas.tools import ToolDependencies
from cutecanvas.tools.base import BaseTool
from cutecanvas.tools.ports import (
    CursorInteractionPort,
    MoveInteractionPort,
    NavigationInteractionPort,
    PaintingInteractionPort,
    PixelSelectionInteractionPort,
    SmartSelectionInteractionPort,
    ToolActivationPorts,
    TransformInteractionPort,
    tool_activation_ports,
)
from cutecanvas.tools.tools import Tools
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from qpane import CursorTool, PanZoomTool, ViewerTool

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


class EmptyTool(ViewerTool):
    def __init__(self) -> None:
        super().__init__()


def test_extension_tool_defaults_are_inert(qapp):
    manager = Tools()
    manager.registerTool("empty", EmptyTool)
    manager.set_mode("empty", ToolActivationPorts())
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
    manager.set_mode("inspect", ToolActivationPorts())
    assert "connected" in events
    assert isinstance(manager.get_active_tool(), DummyTool)
    with pytest.raises(RuntimeError):
        manager.unregisterTool("inspect")
    manager.set_mode(manager.CONTROL_MODE_PANZOOM, ToolActivationPorts())
    manager.unregisterTool("inspect")
    assert "disconnected" in events
    assert manager.get_active_tool() is not None


def test_custom_tool_receives_frozen_dependency_mapping_projection(qapp) -> None:
    """Custom tools should retain the public mapping activation contract."""
    manager = Tools()
    manager.registerTool("inspect", DummyTool)
    ports = tool_activation_ports(
        cursor=CursorInteractionPort(),
        navigation=NavigationInteractionPort(get_zoom=lambda: 2.0),
        movement=MoveInteractionPort(),
        transform=TransformInteractionPort(),
        pixel_selection=PixelSelectionInteractionPort(),
        painting=PaintingInteractionPort(get_brush_size=lambda: 31),
        smart_selection=SmartSelectionInteractionPort(),
    )

    manager.set_mode("inspect", ports)

    tool = manager.get_active_tool()
    assert isinstance(tool, DummyTool)
    assert tool.received_dependencies["get_zoom"]() == 2.0
    assert tool.received_dependencies["get_brush_size"]() == 31


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
    manager.set_mode("exploding", ToolActivationPorts())
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
    manager.set_mode("warn", ToolActivationPorts())
    signal = manager.get_active_tool().signals.cursor_update_requested
    signal_cls = type(signal)
    original_disconnect = signal_cls.disconnect

    def boom(self, slot):  # pragma: no cover - exercised via manager disconnect
        raise TypeError("already disconnected")

    monkeypatch.setattr(signal_cls, "disconnect", boom, raising=False)
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        manager.set_mode(manager.CONTROL_MODE_PANZOOM, ToolActivationPorts())
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
        ToolActivationPorts(
            cursor=CursorInteractionPort(
                is_drag_out_allowed=lambda: True,
                is_content_empty=lambda: False,
            ),
        ),
    )
    tool = manager.get_active_tool()
    assert isinstance(tool, CursorTool)
    assert tool.getCursor().shape() == Qt.CursorShape.ArrowCursor
    assert manager.get_control_mode() == Tools.CONTROL_MODE_CURSOR
    assert tool._port.is_drag_out_allowed()
    assert not tool._port.is_content_empty()
    assert tool._drag_start_position is None
    manager_drag_events = []
    tool_drag_events = []
    manager.signals.drag_out_requested.connect(manager_drag_events.append)
    tool.signals.drag_out_requested.connect(tool_drag_events.append)
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(0, 0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    tool.mousePressEvent(press)
    assert tool._drag_start_position is not None
    start_distance = QApplication.instance().startDragDistance()
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(start_distance + 1, 0),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert (
        move.position().toPoint() - tool._drag_start_position
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
        ToolActivationPorts(
            navigation=NavigationInteractionPort(
                is_navigation_locked=lambda: False,
                is_content_empty=lambda: False,
                is_drag_out_allowed=lambda: True,
            ),
        ),
    )
    tool = manager.get_active_tool()
    assert isinstance(tool, PanZoomTool)
    manager_drag_events = []
    tool_drag_events = []
    manager.signals.drag_out_requested.connect(manager_drag_events.append)
    tool.signals.drag_out_requested.connect(tool_drag_events.append)
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(0, 0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    tool.mousePressEvent(press)
    assert tool._drag_start_position is not None
    start_distance = QApplication.instance().startDragDistance()
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(start_distance + 1, 0),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    tool.mouseMoveEvent(move)
    assert tool._drag_start_position is None
    assert tool_drag_events, "Pan/zoom tool should emit drag-out attempts"
    assert manager_drag_events, "Pan/zoom drag-out should reach manager signals"
