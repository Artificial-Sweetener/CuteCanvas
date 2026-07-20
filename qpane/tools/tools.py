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

"""Tool manager orchestration helpers."""

import logging
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, QPoint, QPointF, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QWheelEvent

from .base import BaseTool, CursorTool, ExtensionTool, PanZoomTool
from .move import MoveTool
from .ports import ToolActivationPorts
from .selection_shapes import (
    EllipseSelectionTool,
    LassoSelectionTool,
    RectangleSelectionTool,
)
from .transform import TransformTool

logger = logging.getLogger(__name__)


class ToolManagerSignals(QObject):
    """Qt signal bus that mirrors tool emissions for the QPane widget."""

    # PanZoomTool signals
    pan_requested = Signal(QPointF)
    zoom_requested = Signal(float, QPointF)
    zoom_snap_requested = Signal(float, QPointF, object)
    drag_start_maybe_requested = Signal(QMouseEvent)
    # BrushTool signals (qpane.masks.tools.brush; optional feature)
    stroke_applied = Signal(object)
    stroke_completed = Signal()
    stroke_cancelled = Signal()
    brush_size_changed = Signal(int)
    undo_state_push_requested = Signal()
    # SmartSelectTool signals (optional feature)
    region_selected_for_masking = Signal(np.ndarray, bool)
    mask_component_adjustment_requested = Signal(QPoint, bool)
    # Common signals
    repaint_overlay_requested = Signal()
    cursor_update_requested = Signal()


@dataclass
class ToolRegistration:
    """Descriptor for constructing a tool mode plus optional wiring hooks."""

    factory: Callable[[], ExtensionTool]
    on_connect: Callable[["ToolManagerSignals", ExtensionTool], None] | None = None
    on_disconnect: Callable[["ToolManagerSignals", ExtensionTool], None] | None = None


class Tools(QObject):
    """Manage tool lifecycle, signal wiring, and event dispatch for the QPane.

    Transitions follow deactivate -> disconnect -> activate -> connect so every tool sees a
    consistent lifecycle. The first registration becomes the default control mode while
    additional tools may register later and activate on demand.
    """

    CONTROL_MODE_PANZOOM = "panzoom"
    CONTROL_MODE_CURSOR = "cursor"
    CONTROL_MODE_MOVE = "move"
    CONTROL_MODE_TRANSFORM = "transform"
    CONTROL_MODE_DRAW_BRUSH = "draw-brush"
    CONTROL_MODE_SMART_SELECT = "smart-select"
    CONTROL_MODE_SELECT_RECTANGLE = "select-rectangle"
    CONTROL_MODE_SELECT_ELLIPSE = "select-ellipse"
    CONTROL_MODE_SELECT_LASSO = "select-lasso"

    def __init__(self, parent=None):
        """Seed the manager with the default pan/zoom tool registration."""
        super().__init__(parent)
        from ..painting.tools import (
            BrushTool,
            connect_brush_signals,
            disconnect_brush_signals,
        )

        self.signals = ToolManagerSignals()
        self._registrations: dict[str, ToolRegistration] = {}
        self._tools: dict[str, ExtensionTool] = {}
        self._control_mode: str | None = None
        self._active_tool: ExtensionTool | None = None
        self._tool_connections: dict[
            ExtensionTool, list[tuple[object, object, str, str]]
        ] = {}
        self.registerTool(
            self.CONTROL_MODE_PANZOOM,
            PanZoomTool,
            on_connect=self._connect_panzoom_signals,
            on_disconnect=self._disconnect_panzoom_signals,
        )
        self.registerTool(
            self.CONTROL_MODE_CURSOR,
            CursorTool,
            on_connect=self._connect_cursor_signals,
            on_disconnect=self._disconnect_cursor_signals,
        )
        self.registerTool(self.CONTROL_MODE_MOVE, MoveTool)
        self.registerTool(self.CONTROL_MODE_TRANSFORM, TransformTool)
        self.registerTool(self.CONTROL_MODE_SELECT_RECTANGLE, RectangleSelectionTool)
        self.registerTool(self.CONTROL_MODE_SELECT_ELLIPSE, EllipseSelectionTool)
        self.registerTool(self.CONTROL_MODE_SELECT_LASSO, LassoSelectionTool)
        self.registerTool(
            self.CONTROL_MODE_DRAW_BRUSH,
            BrushTool,
            on_connect=connect_brush_signals,
            on_disconnect=disconnect_brush_signals,
        )

    def _ensure_tool(self, mode: str) -> ExtensionTool:
        """Instantiate and cache the tool for the requested mode."""
        registration = self._registrations.get(mode)
        if registration is None:
            raise ValueError(f"Invalid control mode: {mode}")
        tool = self._tools.get(mode)
        if tool is None:
            tool = registration.factory()
            self._tools[mode] = tool
        return tool

    def registerTool(
        self,
        mode: str,
        factory: Callable[[], ExtensionTool],
        *,
        on_connect: Callable[[ToolManagerSignals, ExtensionTool], None] | None = None,
        on_disconnect: (
            Callable[[ToolManagerSignals, ExtensionTool], None] | None
        ) = None,
    ) -> None:
        """Register a new tool mode.

        Args:
            mode: Unique identifier for the control mode.
            factory: Callable that constructs the tool instance.
            on_connect: Optional hook that runs after shared signal wiring.
            on_disconnect: Optional hook that runs during teardown after shared disconnects.

        Raises:
            ValueError: If mode is already registered.

        Side effects:
            The first registration becomes the manager's default control mode.
        """
        if mode in self._registrations:
            raise ValueError(f"Tool mode '{mode}' already registered")
        self._registrations[mode] = ToolRegistration(
            factory=factory,
            on_connect=on_connect,
            on_disconnect=on_disconnect,
        )
        if self._control_mode is None:
            self._control_mode = mode

    def unregisterTool(self, mode: str) -> None:
        """Remove a tool mode after ensuring it is neither the default nor currently active."""
        if mode == self.CONTROL_MODE_PANZOOM:
            raise ValueError("Pan/zoom tool cannot be unregistered")
        if mode not in self._registrations:
            return
        if self._control_mode == mode:
            raise RuntimeError("Cannot unregister the active tool; switch modes first")
        tool = self._tools.pop(mode, None)
        if tool is not None:
            self._disconnect_tool_signals(mode, tool)
            tool.deactivate()
        del self._registrations[mode]

    def available_modes(self) -> tuple[str, ...]:
        """Return registered control mode identifiers in registration order."""
        return tuple(self._registrations.keys())

    def set_mode(self, mode: str, ports: ToolActivationPorts | None = None) -> None:
        """Activate a tool mode and wire its dependencies.

        Args:
            mode: Control mode to activate.
            ports: Focused activation ports for built-ins and custom tools.

        Raises:
            ValueError: If mode has not been registered.

        Side effects:
            Deactivates and disconnects the current tool before wiring the new one and
            emitting cursor_update_requested.
        """
        tool = self._ensure_tool(mode)
        if self._active_tool and self._control_mode:
            self._disconnect_tool_signals(self._control_mode, self._active_tool)
            self._active_tool.deactivate()
        self._control_mode = mode
        self._active_tool = tool
        activation_ports = ToolActivationPorts() if ports is None else ports
        tool.activate(activation_ports.for_mode(mode))
        self._connect_tool_signals(mode, tool)
        self.signals.cursor_update_requested.emit()

    def _connect_tool_signals(self, mode: str, tool: ExtensionTool) -> None:
        """Connect shared tool signals and invoke any mode-specific on_connect hook."""
        connections = self._tool_connections.setdefault(tool, [])
        if hasattr(tool.signals, "cursor_update_requested"):
            tool.signals.cursor_update_requested.connect(
                self.signals.cursor_update_requested
            )
            connections.append(
                (
                    tool.signals.cursor_update_requested,
                    self.signals.cursor_update_requested,
                    mode,
                    "cursor_update_requested",
                )
            )
        if hasattr(tool.signals, "repaint_overlay_requested"):
            tool.signals.repaint_overlay_requested.connect(
                self.signals.repaint_overlay_requested
            )
            connections.append(
                (
                    tool.signals.repaint_overlay_requested,
                    self.signals.repaint_overlay_requested,
                    mode,
                    "repaint_overlay_requested",
                )
            )
        registration = self._registrations.get(mode)
        if registration and registration.on_connect:
            try:
                registration.on_connect(self.signals, tool)
            except Exception:
                logger.exception("Tool '%s' on_connect hook raised", mode)

    @staticmethod
    def _disconnect_signal(
        signal,
        slot,
        *,
        mode: str,
        signal_name: str,
    ) -> None:
        """Detach a signal-slot pair while logging failures."""
        try:
            signal.disconnect(slot)
        except (TypeError, RuntimeError) as exc:
            logger.warning(
                "Failed to disconnect signal '%s' for mode '%s': %s",
                signal_name,
                mode,
                exc,
            )

    def _disconnect_tool_signals(self, mode: str, tool: ExtensionTool) -> None:
        """Detach shared tool signals and run the mode's on_disconnect hook."""
        connections = self._tool_connections.pop(tool, [])
        for signal, slot, conn_mode, signal_name in connections:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError) as exc:
                logger.warning(
                    "Failed to disconnect signal '%s' for mode '%s': %s",
                    signal_name,
                    conn_mode,
                    exc,
                )
        registration = self._registrations.get(mode)
        if registration and registration.on_disconnect:
            try:
                registration.on_disconnect(self.signals, tool)
            except Exception:
                logger.exception("Tool '%s' on_disconnect hook raised", mode)

    @staticmethod
    def _connect_panzoom_signals(
        manager_signals: ToolManagerSignals, tool: BaseTool
    ) -> None:
        """Wire pan/zoom tool signals to the shared bus."""
        tool.signals.pan_requested.connect(manager_signals.pan_requested)
        tool.signals.zoom_requested.connect(manager_signals.zoom_requested)
        tool.signals.zoom_snap_requested.connect(manager_signals.zoom_snap_requested)
        tool.signals.drag_start_maybe_requested.connect(
            manager_signals.drag_start_maybe_requested
        )

    @staticmethod
    def _disconnect_panzoom_signals(
        manager_signals: ToolManagerSignals, tool: BaseTool
    ) -> None:
        """Detach pan/zoom signals while logging failures."""
        mappings = (
            (
                "pan_requested",
                tool.signals.pan_requested,
                manager_signals.pan_requested,
            ),
            (
                "zoom_requested",
                tool.signals.zoom_requested,
                manager_signals.zoom_requested,
            ),
            (
                "zoom_snap_requested",
                tool.signals.zoom_snap_requested,
                manager_signals.zoom_snap_requested,
            ),
            (
                "drag_start_maybe_requested",
                tool.signals.drag_start_maybe_requested,
                manager_signals.drag_start_maybe_requested,
            ),
        )
        for signal_name, signal, slot in mappings:
            Tools._disconnect_signal(
                signal,
                slot,
                mode=Tools.CONTROL_MODE_PANZOOM,
                signal_name=signal_name,
            )

    @staticmethod
    def _connect_cursor_signals(
        manager_signals: ToolManagerSignals, tool: BaseTool
    ) -> None:
        """Wire cursor tool drag-out attempts to the shared bus."""
        tool.signals.drag_start_maybe_requested.connect(
            manager_signals.drag_start_maybe_requested
        )

    @staticmethod
    def _disconnect_cursor_signals(
        manager_signals: ToolManagerSignals, tool: BaseTool
    ) -> None:
        """Detach cursor tool drag-out wiring while logging failures."""
        Tools._disconnect_signal(
            tool.signals.drag_start_maybe_requested,
            manager_signals.drag_start_maybe_requested,
            mode=Tools.CONTROL_MODE_CURSOR,
            signal_name="drag_start_maybe_requested",
        )

    def get_active_tool(self) -> ExtensionTool | None:
        """Return the currently active tool, if any."""
        return self._active_tool

    def get_control_mode(self) -> str:
        """Return the current control mode, defaulting to pan/zoom."""
        return self._control_mode or self.CONTROL_MODE_PANZOOM

    def draw_overlay(self, painter: QPainter) -> None:
        """Delegate overlay drawing to the active tool with fault tolerance."""
        tool = self._active_tool
        if tool is None:
            return
        self._invoke_tool("draw_overlay", tool.draw_overlay, painter)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Forward wheel events to the active tool."""
        tool = self._active_tool
        if tool is None:
            return
        self._invoke_tool("wheelEvent", tool.wheelEvent, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Forward mouse press events to the active tool."""
        tool = self._active_tool
        if tool is None:
            return
        self._invoke_tool("mousePressEvent", tool.mousePressEvent, event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Forward mouse move events to the active tool."""
        tool = self._active_tool
        if tool is None:
            return
        self._invoke_tool("mouseMoveEvent", tool.mouseMoveEvent, event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Forward mouse release events to the active tool."""
        tool = self._active_tool
        if tool is None:
            return
        self._invoke_tool("mouseReleaseEvent", tool.mouseReleaseEvent, event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Forward mouse double-clicks to the active tool."""
        tool = self._active_tool
        if tool is None:
            return
        self._invoke_tool("mouseDoubleClickEvent", tool.mouseDoubleClickEvent, event)

    def enterEvent(self, event) -> None:
        """Forward enter events to the active tool."""
        tool = self._active_tool
        if tool is None:
            return
        self._invoke_tool("enterEvent", tool.enterEvent, event)

    def leaveEvent(self, event) -> None:
        """Forward leave events to the active tool."""
        tool = self._active_tool
        if tool is None:
            return
        self._invoke_tool("leaveEvent", tool.leaveEvent, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Forward key presses to the active tool."""
        tool = self._active_tool
        if tool is None:
            return
        self._invoke_tool("keyPressEvent", tool.keyPressEvent, event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        """Forward key releases to the active tool."""
        tool = self._active_tool
        if tool is None:
            return
        self._invoke_tool("keyReleaseEvent", tool.keyReleaseEvent, event)

    def _invoke_tool(
        self, method_name: str, handler: Callable[..., None], *args
    ) -> None:
        """Invoke a tool handler and log failures to keep QPane responsive."""
        try:
            handler(*args)
        except Exception:
            logger.exception(
                "Tool '%s' raised during %s", self._control_mode, method_name
            )
