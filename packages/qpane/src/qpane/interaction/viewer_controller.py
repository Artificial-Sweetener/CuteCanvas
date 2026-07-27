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
"""Built-in and extensible interaction lifecycle for the QPane viewer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QCursor,
    QEnterEvent,
    QKeyEvent,
    QMouseEvent,
    QTabletEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from ..core.config import Config
from ..rendering.viewport import Viewport, ViewportZoomMode
from .cursor_tool import CursorTool
from .navigation_tool import PanZoomTool
from .pointer_controller import PointerInputController
from .pointer_port import PointerInputPort
from .ports import CursorInteractionPort, NavigationInteractionPort
from .tool import ViewerTool
from .tool_manager import ToolManager


def _false_point(_point: QPointF) -> bool:
    """Decline an optional point interaction."""
    return False


def _ignore_point(_point: QPointF) -> None:
    """Ignore an optional point update."""


def _false_mouse(_event: QMouseEvent) -> bool:
    """Decline an optional mouse interaction."""
    return False


def _no_cursor() -> QCursor | None:
    """Return no optional cursor override."""
    return None


def _nothing() -> None:
    """Perform no optional host work."""


@dataclass(frozen=True, slots=True)
class ViewerInteractionHost:
    """Supply viewer state and outward notifications to interaction owners."""

    widget: QWidget
    viewport: Viewport
    settings: Callable[[], Config]
    is_content_empty: Callable[[], bool]
    physical_viewport_rect: Callable[[], QRectF]
    is_drag_out_allowed: Callable[[], bool]
    repaint: Callable[[], None]
    emit_mode_changed: Callable[[str], None]
    emit_drag_out_requested: Callable[[object], None]
    claim_external_touch: Callable[[QPointF], bool] = _false_point
    update_external_touch: Callable[[QPointF], None] = _ignore_point
    finish_external_touch: Callable[[QPointF], None] = _ignore_point
    cancel_external_touch: Callable[[], None] = _nothing
    handle_external_mouse_press: Callable[[QMouseEvent], bool] = _false_mouse
    handle_external_mouse_move: Callable[[QMouseEvent], bool] = _false_mouse
    handle_external_mouse_release: Callable[[QMouseEvent], bool] = _false_mouse
    external_cursor: Callable[[], QCursor | None] = _no_cursor
    begin_navigation: Callable[[], None] = _nothing
    finish_navigation: Callable[[], None] = _nothing


class ViewerInteractionController:
    """Own QPane tool dispatch, pointer normalization, and cursor arbitration."""

    PAN_ZOOM_MODE = "panzoom"
    CURSOR_MODE = "cursor"

    def __init__(self, host: ViewerInteractionHost) -> None:
        """Install the built-in tools and normalized pointer pipeline."""
        self._host = host
        self._tools = ToolManager(host.widget)
        self._install_viewer_tools()
        self._pointer = PointerInputController(self._pointer_port())
        self._tools.activate(self.PAN_ZOOM_MODE)

    @property
    def tools(self) -> ToolManager:
        """Return the authoritative generic tool manager."""
        return self._tools

    def register_tool(
        self,
        mode: str,
        factory: Callable[[], ViewerTool],
        dependencies: Callable[[], object] | None = None,
    ) -> None:
        """Register one lazy viewer-tool factory."""
        self._tools.register(mode, factory, dependencies or dict)

    def unregister_tool(self, mode: str) -> None:
        """Remove one inactive non-built-in viewer tool."""
        if mode in {self.PAN_ZOOM_MODE, self.CURSOR_MODE}:
            raise ValueError("Built-in viewer tools cannot be unregistered")
        self._tools.unregister(mode)

    def activate(self, mode: str) -> None:
        """Activate one registered viewer tool."""
        self._tools.activate(mode)

    def active_mode(self) -> str:
        """Return the active mode identifier."""
        return self._tools.active_mode or self.PAN_ZOOM_MODE

    def available_modes(self) -> tuple[str, ...]:
        """Return registered tool mode identifiers."""
        return self._tools.available_modes()

    def draw_overlay(self, painter: object) -> None:
        """Delegate one overlay pass to the active tool."""
        self._tools.draw_overlay(painter)

    def set_navigation_locked(self, locked: bool) -> None:
        """Set viewport navigation policy and cancel captured input."""
        self._host.viewport.set_locked(bool(locked))
        self._pointer.cancel_active_sequences()
        self.refresh_cursor()

    def set_visible(self, visible: bool) -> None:
        """Limit application-wide pointer observation to a visible viewer."""
        self._pointer.set_application_observation(visible)
        if not visible:
            self._pointer.cancel_active_sequences()

    def handle_event(self, event: QEvent) -> bool:
        """Route a Qt touch frame through normalized input."""
        if event.type() not in {
            QEvent.Type.TouchBegin,
            QEvent.Type.TouchUpdate,
            QEvent.Type.TouchEnd,
            QEvent.Type.TouchCancel,
        }:
            return False
        return self._pointer.handle_touch_event(event)

    def handle_tablet(self, event: QTabletEvent) -> bool:
        """Route a tablet sample through normalized input."""
        return self._pointer.handle_tablet_event(event)

    def handle_wheel(self, event: QWheelEvent) -> None:
        """Route wheel input to the active tool."""
        self._tools.wheelEvent(event)

    def handle_mouse_press(self, event: QMouseEvent) -> None:
        """Arbitrate external interaction before active-tool press handling."""
        if not self._pointer.observe_mouse_event(event):
            event.accept()
            return
        if not self._host.handle_external_mouse_press(event):
            self._tools.mousePressEvent(event)
        self.refresh_cursor()

    def handle_mouse_move(self, event: QMouseEvent) -> None:
        """Update external hover and active-tool movement."""
        if not self._pointer.observe_mouse_event(event):
            event.accept()
            return
        if not self._host.handle_external_mouse_move(event):
            self._tools.mouseMoveEvent(event)
        self.refresh_cursor()

    def handle_mouse_release(self, event: QMouseEvent) -> None:
        """Finish external or active-tool mouse capture."""
        if not self._pointer.observe_mouse_event(event):
            event.accept()
            return
        if not self._host.handle_external_mouse_release(event):
            self._tools.mouseReleaseEvent(event)
        self.refresh_cursor()

    def handle_mouse_double_click(self, event: QMouseEvent) -> None:
        """Route accepted mouse double-click input to the active tool."""
        if not self._pointer.observe_mouse_event(event):
            event.accept()
            return
        self._tools.mouseDoubleClickEvent(event)

    def handle_enter(self, event: QEnterEvent) -> None:
        """Reconcile pointer modality, cursor, and active-tool entry."""
        self._pointer.observe_enter_event(event)
        self.refresh_cursor()
        self._tools.enterEvent(event)

    def handle_leave(self, event: QEvent) -> None:
        """Release transient hover feedback and notify the active tool."""
        self._pointer.handle_widget_leave()
        self._host.cancel_external_touch()
        self._tools.leaveEvent(event)
        self.refresh_cursor()

    def handle_key_press(self, event: QKeyEvent) -> None:
        """Route a key press to the active tool."""
        self._tools.keyPressEvent(event)

    def handle_key_release(self, event: QKeyEvent) -> None:
        """Route a key release to the active tool."""
        self._tools.keyReleaseEvent(event)

    def refresh_cursor(self) -> None:
        """Apply pointer modality, external, and active-tool cursor priority."""
        widget = self._host.widget
        if self._pointer.cursor_suppressed:
            widget.setCursor(Qt.CursorShape.BlankCursor)
            return
        cursor = self._host.external_cursor()
        if cursor is None:
            tool = self._tools.active_tool
            cursor = None if tool is None else tool.getCursor()
        widget.unsetCursor() if cursor is None else widget.setCursor(cursor)

    def shutdown(self) -> None:
        """Release active pointer sequences and tool instances."""
        self._pointer.shutdown()
        self._tools.shutdown()

    def _install_viewer_tools(self) -> None:
        """Install built-in tools and their source-neutral request signals."""
        self._tools.register(
            self.PAN_ZOOM_MODE,
            PanZoomTool,
            self._navigation_port,
        )
        self._tools.register(
            self.CURSOR_MODE,
            CursorTool,
            self._cursor_port,
        )
        signals = self._tools.signals
        signals.pan_requested.connect(self._host.viewport.setPan)
        signals.zoom_requested.connect(self._apply_tool_zoom)
        signals.zoom_snap_requested.connect(self._apply_tool_zoom_snap)
        signals.repaint_overlay_requested.connect(self._host.repaint)
        signals.cursor_update_requested.connect(self.refresh_cursor)
        signals.drag_out_requested.connect(self._host.emit_drag_out_requested)
        signals.mode_changed.connect(self._host.emit_mode_changed)
        signals.navigation_started.connect(self._host.begin_navigation)
        signals.navigation_finished.connect(self._host.finish_navigation)

    def _navigation_port(self) -> NavigationInteractionPort:
        """Resolve current viewport behavior for built-in navigation."""
        viewport = self._host.viewport
        return NavigationInteractionPort(
            is_navigation_locked=viewport.is_locked,
            is_content_empty=self._host.is_content_empty,
            is_drag_out_allowed=self._host.is_drag_out_allowed,
            can_pan=viewport.can_pan,
            get_pan=lambda: QPointF(viewport.pan),
            get_zoom=lambda: float(viewport.zoom),
            get_native_zoom=viewport.nativeZoom,
            get_fit_zoom=viewport.computeFitZoom,
            get_zoom_mode=viewport.get_zoom_mode,
            set_zoom_fit=viewport.setZoomFit,
            set_zoom_fit_interpolated=viewport.setZoomFitInterpolated,
            set_zoom_one_to_one=viewport.setZoom1To1,
            set_zoom_one_to_one_interpolated=viewport.setZoom1To1Interpolated,
            get_dpr=self._host.widget.devicePixelRatioF,
        )

    def _cursor_port(self) -> CursorInteractionPort:
        """Resolve content and drag policy for the built-in cursor tool."""
        return CursorInteractionPort(
            is_drag_out_allowed=self._host.is_drag_out_allowed,
            is_content_empty=self._host.is_content_empty,
        )

    def _apply_tool_zoom(self, zoom: float, anchor: QPointF) -> None:
        """Apply tool zoom through the configured smooth viewport path."""
        viewport = self._host.viewport
        if bool(self._host.settings().smooth_zoom_enabled):
            viewport.applyZoomInterpolated(zoom, anchor)
        else:
            viewport.applyZoom(zoom, anchor)

    def _apply_tool_zoom_snap(
        self,
        zoom: float,
        anchor: QPointF,
        mode: object,
    ) -> None:
        """Apply a semantic wheel snap without losing its zoom mode."""
        viewport = self._host.viewport
        if mode is ViewportZoomMode.FIT:
            viewport.setZoomFitInterpolated()
        elif mode is ViewportZoomMode.ONE_TO_ONE:
            viewport.setZoom1To1Interpolated(anchor)
        else:
            self._apply_tool_zoom(zoom, anchor)

    def _pointer_port(self) -> PointerInputPort:
        """Build the normalized direct-input boundary."""
        settings = self._host.settings
        return PointerInputPort(
            widget=self._host.widget,
            active_tool=lambda: self._tools.active_tool,
            viewport=lambda: self._host.viewport,
            physical_viewport_rect=self._host.physical_viewport_rect,
            has_renderable_content=lambda: not self._host.is_content_empty(),
            touch_navigation_enabled=lambda: bool(settings().touch_navigation_enabled),
            touch_inertia_enabled=lambda: bool(settings().touch_inertia_enabled),
            touch_inertia_deceleration=lambda: float(
                settings().touch_inertia_deceleration
            ),
            palm_rejection_ms=lambda: int(settings().palm_rejection_ms),
            claim_external_touch=self._host.claim_external_touch,
            update_external_touch=self._host.update_external_touch,
            finish_external_touch=self._host.finish_external_touch,
            cancel_external_touch=self._host.cancel_external_touch,
            pointer_state_changed=self.refresh_cursor,
        )
