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
"""Fault-contained lifecycle and event dispatch for QPane-hosted tools."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QPointF, Signal
from PySide6.QtGui import QEnterEvent, QKeyEvent, QMouseEvent, QPainter, QWheelEvent

from .tool import ViewerTool

logger = logging.getLogger(__name__)


class ToolManagerSignals(QObject):
    """Publish source-neutral requests from the active viewer tool."""

    pan_requested = Signal(QPointF)
    zoom_requested = Signal(float, QPointF)
    zoom_snap_requested = Signal(float, QPointF, object)
    drag_out_requested = Signal(QMouseEvent)
    repaint_overlay_requested = Signal()
    cursor_update_requested = Signal()
    mode_changed = Signal(str)


@dataclass(frozen=True, slots=True)
class ToolRegistration:
    """Construct one tool mode and resolve its focused activation port."""

    factory: Callable[[], ViewerTool]
    dependencies: Callable[[], object]
    on_connect: Callable[[ToolManagerSignals, ViewerTool], None] | None = None
    on_disconnect: Callable[[ToolManagerSignals, ViewerTool], None] | None = None


class ToolManager(QObject):
    """Own viewer-tool registration, activation, dispatch, and signal routing."""

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        signals: ToolManagerSignals | None = None,
    ) -> None:
        """Create an empty manager with no implicit domain-specific tools."""
        super().__init__(parent)
        self.signals = ToolManagerSignals() if signals is None else signals
        self._registrations: dict[str, ToolRegistration] = {}
        self._instances: dict[str, ViewerTool] = {}
        self._active_mode: str | None = None
        self._active_tool: ViewerTool | None = None

    def register(
        self,
        mode: str,
        factory: Callable[[], ViewerTool],
        dependencies: Callable[[], object],
        *,
        on_connect: Callable[[ToolManagerSignals, ViewerTool], None] | None = None,
        on_disconnect: Callable[[ToolManagerSignals, ViewerTool], None] | None = None,
    ) -> None:
        """Register a lazily constructed tool mode."""
        if not mode:
            raise ValueError("Tool mode must not be empty")
        if mode in self._registrations:
            raise ValueError(f"Tool mode {mode!r} is already registered")
        self._registrations[mode] = ToolRegistration(
            factory,
            dependencies,
            on_connect,
            on_disconnect,
        )

    def unregister(self, mode: str) -> None:
        """Remove an inactive tool registration and its cached instance."""
        if mode == self._active_mode:
            raise RuntimeError("Cannot unregister the active tool")
        self._registrations.pop(mode, None)
        tool = self._instances.pop(mode, None)
        if tool is not None:
            self._safe_invoke("deactivate", tool.deactivate)

    def activate(self, mode: str, *, force: bool = False) -> None:
        """Transactionally activate one mode using a freshly resolved port.

        Args:
            mode: Registered tool identifier.
            force: Rebuild the activation boundary even when the mode is unchanged.
        """
        registration = self._registrations.get(mode)
        if registration is None:
            raise ValueError(f"Unknown tool mode: {mode}")
        if self._active_mode == mode and not force:
            return
        tool = self._instances.get(mode)
        created = tool is None
        if tool is None:
            tool = registration.factory()
            if not isinstance(tool, ViewerTool):
                raise TypeError("Tool factories must return ViewerTool instances")
        dependencies = registration.dependencies()
        tool.activate(dependencies)
        if created:
            self._instances[mode] = tool
        if self._active_mode == mode:
            self.signals.cursor_update_requested.emit()
            return
        if self._active_tool is not None and self._active_mode is not None:
            self._disconnect(self._active_mode, self._active_tool)
            self._safe_invoke("deactivate", self._active_tool.deactivate)
        self._connect(mode, tool)
        self._active_mode = mode
        self._active_tool = tool
        self.signals.cursor_update_requested.emit()
        self.signals.mode_changed.emit(mode)

    @property
    def active_mode(self) -> str | None:
        """Return the active mode identifier."""
        return self._active_mode

    @property
    def active_tool(self) -> ViewerTool | None:
        """Return the active tool instance."""
        return self._active_tool

    def available_modes(self) -> tuple[str, ...]:
        """Return registered identifiers in deterministic insertion order."""
        return tuple(self._registrations)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Dispatch one mouse press to the active tool."""
        self._dispatch("mousePressEvent", event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Dispatch one mouse move to the active tool."""
        self._dispatch("mouseMoveEvent", event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Dispatch one mouse release to the active tool."""
        self._dispatch("mouseReleaseEvent", event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Dispatch one mouse double-click to the active tool."""
        self._dispatch("mouseDoubleClickEvent", event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Dispatch one wheel event to the active tool."""
        self._dispatch("wheelEvent", event)

    def enterEvent(self, event: QEnterEvent) -> None:
        """Dispatch one pointer-entry event to the active tool."""
        self._dispatch("enterEvent", event)

    def leaveEvent(self, event: QEvent) -> None:
        """Dispatch one pointer-exit event to the active tool."""
        self._dispatch("leaveEvent", event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Dispatch one key press to the active tool."""
        self._dispatch("keyPressEvent", event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        """Dispatch one key release to the active tool."""
        self._dispatch("keyReleaseEvent", event)

    def draw_overlay(self, painter: QPainter) -> None:
        """Ask the active tool to draw its scene feedback."""
        self._dispatch("draw_overlay", painter)

    def shutdown(self) -> None:
        """Deactivate tools and release cached instances during host teardown."""
        if self._active_tool is not None and self._active_mode is not None:
            self._disconnect(self._active_mode, self._active_tool)
            self._safe_invoke("deactivate", self._active_tool.deactivate)
        self._active_tool = None
        self._active_mode = None
        self._instances.clear()
        self._registrations.clear()

    def _dispatch(self, method_name: str, argument: object) -> None:
        """Fault-contain one active-tool callback."""
        tool = self._active_tool
        if tool is None:
            return
        handler = getattr(tool, method_name)
        self._safe_invoke(method_name, handler, argument)

    def _safe_invoke(
        self,
        method_name: str,
        handler: Callable[..., None],
        *arguments: object,
    ) -> None:
        """Log extension failures without tearing down the Qt event loop."""
        try:
            handler(*arguments)
        except Exception:
            logger.exception("Tool %r raised during %s", self._active_mode, method_name)

    def _connect(self, mode: str, tool: ViewerTool) -> None:
        """Route the active tool's source-neutral requests through the manager."""
        mappings = (
            (tool.signals.pan_requested, self.signals.pan_requested),
            (tool.signals.zoom_requested, self.signals.zoom_requested),
            (tool.signals.zoom_snap_requested, self.signals.zoom_snap_requested),
            (tool.signals.drag_out_requested, self.signals.drag_out_requested),
            (
                tool.signals.repaint_overlay_requested,
                self.signals.repaint_overlay_requested,
            ),
            (
                tool.signals.cursor_update_requested,
                self.signals.cursor_update_requested,
            ),
        )
        for source, target in mappings:
            source.connect(target)
        registration = self._registrations[mode]
        if registration.on_connect is not None:
            self._safe_invoke(
                "connect",
                registration.on_connect,
                self.signals,
                tool,
            )

    def _disconnect(self, mode: str, tool: ViewerTool) -> None:
        """Detach all manager routes from a previously active tool."""
        mappings = (
            (tool.signals.pan_requested, self.signals.pan_requested),
            (tool.signals.zoom_requested, self.signals.zoom_requested),
            (tool.signals.zoom_snap_requested, self.signals.zoom_snap_requested),
            (tool.signals.drag_out_requested, self.signals.drag_out_requested),
            (
                tool.signals.repaint_overlay_requested,
                self.signals.repaint_overlay_requested,
            ),
            (
                tool.signals.cursor_update_requested,
                self.signals.cursor_update_requested,
            ),
        )
        for source, target in mappings:
            try:
                source.disconnect(target)
            except (RuntimeError, TypeError):
                logger.warning(
                    "Failed to disconnect signal for tool %r", self._active_mode
                )
        registration = self._registrations.get(mode)
        if registration is not None and registration.on_disconnect is not None:
            self._safe_invoke(
                "disconnect",
                registration.on_disconnect,
                self.signals,
                tool,
            )
