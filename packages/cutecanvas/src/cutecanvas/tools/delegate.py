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

"""Delegate handling CuteCanvas's widget interaction and tool coordination."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor, QKeySequence, QMouseEvent, QPen, QWheelEvent
from PySide6.QtWidgets import QApplication
from qpane import PointerInputPort
from qpane.sdk.overlays import OverlayDrawFn, SceneOverlayDrawFn
from qpane.sdk.ui import (
    apply_widget_defaults,
)

from ..core import CursorProvider
from ..editor import EditorOperation, EditorOperationTarget
from .activation import build_editor_tool_ports
from .cursor_controller import EditorCursorController
from .input import PointerInputController
from .overlay_controller import EditorOverlayController
from .tools import Tools

if TYPE_CHECKING:  # pragma: no cover - import guard for typing only

    from ..canvas import CuteCanvas
logger = logging.getLogger(__name__)


class ToolInteractionDelegate:
    """Encapsulate cursor, overlay, and tool input plumbing for :class:`CuteCanvas`."""

    def __init__(self, qpane: CuteCanvas) -> None:
        """Initialize the delegate with the owning CuteCanvas widget."""
        self._qpane = qpane
        self._tools_activated = False
        self._mode_before_pan: str | None = None
        self._preview_outline_pen = QPen(Qt.black, 1, Qt.SolidLine)
        self._preview_inline_pen = QPen(Qt.white, 1, Qt.DashLine)
        self._shift_key_held = False
        self._overlays = EditorOverlayController(qpane.update)
        self._pointer_input = PointerInputController(self._pointer_port())
        self._cursor = EditorCursorController(
            qpane,
            lambda: self._pointer_input.cursor_suppressed,
        )

    def _pointer_port(self) -> PointerInputPort:
        """Build QPane's source-neutral pointer boundary for this editor host."""
        qpane = self._qpane
        return PointerInputPort(
            widget=qpane,
            active_tool=lambda: qpane._tools_manager.get_active_tool(),
            viewport=lambda: qpane.view().viewport,
            physical_viewport_rect=qpane.physicalViewportRect,
            has_renderable_content=lambda: (
                not qpane._is_blank and qpane.view().has_renderable_content()
            ),
            touch_navigation_enabled=lambda: bool(
                qpane.settings.touch_navigation_enabled
            ),
            touch_tool_enabled=lambda: bool(qpane.settings.touch_paint_enabled),
            stylus_tool_enabled=lambda: bool(qpane.settings.stylus_paint_enabled),
            touch_inertia_enabled=lambda: bool(qpane.settings.touch_inertia_enabled),
            touch_inertia_deceleration=lambda: float(
                qpane.settings.touch_inertia_deceleration
            ),
            palm_rejection_ms=lambda: int(qpane.settings.palm_rejection_ms),
            pointer_state_changed=self._handle_pointer_state_changed,
        )

    def _viewport(self):
        """Return the viewport managed by the rendering stack."""
        return self._qpane.view().viewport

    @property
    def content_overlays(self) -> Mapping[str, OverlayDrawFn]:
        """Return overlay draw callbacks keyed by overlay name."""
        return self._overlays.content

    @property
    def scene_overlays(self) -> Mapping[str, SceneOverlayDrawFn]:
        """Return scene overlay callbacks keyed by overlay name."""
        return self._overlays.scene

    @property
    def custom_cursor(self):
        """Return the last cursor CuteCanvas forced while tools were active."""
        return self._cursor.custom_cursor

    @custom_cursor.setter
    def custom_cursor(self, cursor) -> None:
        """Record a custom cursor so mask workflows can restore it."""
        self._cursor.custom_cursor = cursor

    @property
    def brush_size(self) -> int:
        """Return the current brush diameter in device pixels."""
        return self._cursor.brush_size

    @brush_size.setter
    def brush_size(self, size: int) -> None:
        """Clamp and persist the brush size supplied by masks tools."""
        self._cursor.brush_size = max(1, int(size))

    @property
    def alt_key_held(self) -> bool:
        """Return True when the delegate detected an Alt press."""
        return self._cursor.alt_held

    @alt_key_held.setter
    def alt_key_held(self, value: bool) -> None:
        """Update the cached Alt state used by cursor providers."""
        self._cursor.alt_held = bool(value)

    @property
    def shift_key_held(self) -> bool:
        """Return True while the Shift modifier is pressed."""
        return self._shift_key_held

    @shift_key_held.setter
    def shift_key_held(self, value: bool) -> None:
        """Cache Shift state so tools can adjust behaviour."""
        self._shift_key_held = bool(value)

    @property
    def overlays_suspended(self) -> bool:
        """Report whether navigation temporarily hid overlays."""
        return self._overlays.suspended

    @overlays_suspended.setter
    def overlays_suspended(self, value: bool) -> None:
        """Track overlay suspension state for resume helpers."""
        self._overlays.suspended = bool(value)

    @property
    def overlays_resume_pending(self) -> bool:
        """Return True when overlays should resume after navigation."""
        return self._overlays.resume_pending

    @overlays_resume_pending.setter
    def overlays_resume_pending(self, value: bool) -> None:
        """Mark whether a resume call should run after navigation completes."""
        self._overlays.resume_pending = bool(value)

    def initialize_widget_properties(self) -> None:
        """Apply widget defaults for the CuteCanvas widget once."""
        qpane = self._qpane
        apply_widget_defaults(qpane)

    def connect_signals(self) -> None:
        """Wire viewport and tool-manager callbacks to the CuteCanvas."""
        qpane = self._qpane
        viewport = self._viewport()
        viewport.viewChanged.connect(qpane.onViewChanged)
        tools = qpane._tools_manager
        tm_signals = tools.signals
        tm_signals.pan_requested.connect(viewport.setPan)
        tm_signals.zoom_requested.connect(qpane._apply_zoom_interpolated)
        tm_signals.zoom_snap_requested.connect(qpane._apply_zoom_interpolated_with_mode)
        tm_signals.drag_out_requested.connect(self.handle_drag_start_request)
        tm_signals.cursor_update_requested.connect(self.update_cursor)
        tm_signals.repaint_overlay_requested.connect(qpane.update)
        tm_signals.navigation_started.connect(
            qpane.view().presenter.begin_navigation_interaction
        )
        tm_signals.navigation_finished.connect(
            qpane.view().presenter.finish_navigation_interaction
        )

    def registerOverlay(self, name: str, draw_fn: OverlayDrawFn) -> None:
        """Register an overlay draw hook under the provided identifier."""
        self._overlays.register_content(name, draw_fn)

    def unregisterOverlay(self, name: str) -> None:
        """Remove a previously registered overlay if it exists."""
        self._overlays.unregister_content(name)

    def content_overlays_snapshot(self) -> Mapping[str, OverlayDrawFn]:
        """Return a read-only snapshot of registered content overlays."""
        return self._overlays.content_snapshot()

    def registerSceneOverlay(self, name: str, draw_fn: SceneOverlayDrawFn) -> None:
        """Register a scene overlay draw hook under the provided identifier."""
        self._overlays.register_scene(name, draw_fn)

    def unregisterSceneOverlay(self, name: str) -> None:
        """Remove a previously registered scene overlay if it exists."""
        self._overlays.unregister_scene(name)

    def scene_overlays_snapshot(self) -> Mapping[str, SceneOverlayDrawFn]:
        """Return a read-only snapshot of registered scene overlays."""
        return self._overlays.scene_snapshot()

    def registerCursorProvider(self, mode: str, provider: CursorProvider) -> None:
        """Attach a cursor provider for the given mode and apply it immediately when active."""
        self._cursor.register_provider(mode, provider)

    def unregisterCursorProvider(self, mode: str) -> None:
        """Remove the cursor provider tied to the supplied control mode."""
        self._cursor.unregister_provider(mode)

    def suspend_overlays_for_navigation(self) -> None:
        """Flag content overlays as hidden until navigation completes."""
        self._pointer_input.cancel_active_sequences()
        self._overlays.suspend()

    def cancel_active_editor_input(self) -> None:
        """Cancel captured pointer work before host editor policy changes."""
        self._pointer_input.cancel_active_sequences()

    def resume_overlays(self) -> None:
        """Resume overlays immediately without forcing a repaint."""
        self._overlays.resume()

    def resume_overlays_and_update(self) -> None:
        """Resume overlays and schedule a CuteCanvas repaint."""
        self._overlays.resume(repaint=True)

    def maybe_resume_overlays(self) -> None:
        """Allow the UI helpers to resume overlays when pending."""
        if not (self._overlays.suspended and self._overlays.resume_pending):
            return
        current_id = self._qpane.currentCompositionID()
        try:
            activation_pending = self._qpane._masks_controller.is_activation_pending(
                current_id
            )
        except Exception:
            logger.exception(
                "Mask activation status failed; resuming overlays defensively."
            )
            self._overlays.resume()
            return
        if not activation_pending:
            self._overlays.resume()

    def blank(self) -> None:
        """Mark the CuteCanvas as blank while resetting cursor and overlay state.

        Forces pan/zoom mode, resumes overlays, and schedules a repaint so caches stay
        consistent.
        """
        qpane = self._qpane
        self._pointer_input.cancel_active_sequences()
        qpane._is_blank = True
        qpane.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.set_control_mode(Tools.CONTROL_MODE_PANZOOM)
        self.resume_overlays()
        qpane.update()

    def set_control_mode(self, mode: str) -> None:
        """Switch the active tool mode after validating feature availability.

        Args:
            mode: Control mode identifier exposed by Tools.

        Side effects:
            Verifies mask/SAM features before enabling their modes, builds the
            ToolDependencies payload from the viewport and CuteCanvas state, and forwards it
            to the tool manager.
        """
        qpane = self._qpane
        tools = qpane._tools_manager
        if mode in (
            Tools.CONTROL_MODE_DRAW_BRUSH,
            Tools.CONTROL_MODE_CLONE_STAMP,
        ):
            resolution = qpane.editorOperationResolver().resolve(EditorOperation.PAINT)
            mask_service = getattr(qpane, "mask_service", None)
            if (
                mode == Tools.CONTROL_MODE_DRAW_BRUSH
                and resolution.target is EditorOperationTarget.DEFAULT_PAINT_TARGET
                and mask_service is not None
            ):
                composition_id = qpane.currentCompositionID()
                if mask_service.ensureActiveMaskForComposition(composition_id):
                    mask_service.prepareBrushInteraction()
                    qpane.view().coordinate_scene_descriptor()
                    resolution = qpane.editorOperationResolver().resolve(
                        EditorOperation.PAINT
                    )
            if (
                mode == Tools.CONTROL_MODE_DRAW_BRUSH
                and resolution.allowed
                and mask_service is not None
            ):
                mask_service.prepareBrushInteraction()
        elif mode == Tools.CONTROL_MODE_SMART_SELECT:
            if not qpane.samFeatureAvailable():
                qpane.featureFallbacks().get("sam", "setControlMode", default=None)
                return
        ports = build_editor_tool_ports(
            qpane,
            is_alt_held=lambda: self.alt_key_held,
            is_shift_held=lambda: self._shift_key_held,
            get_brush_size=lambda: self.brush_size,
            get_preview_pens=lambda: (
                self._preview_outline_pen,
                self._preview_inline_pen,
            ),
        )

        if tools.get_control_mode() != mode:
            self._pointer_input.cancel_active_sequences()
        tools.set_mode(mode, ports)
        self._tools_activated = True

    def get_control_mode(self) -> str:
        """Return the current tool control mode."""
        return self._qpane._tools_manager.get_control_mode()

    def update_cursor(self) -> None:
        """Apply the cursor selected by the focused arbitration owner."""
        self._cursor.update()

    def update_brush_cursor(self, *, erase_indicator: bool = False) -> None:
        """Apply brush feedback selected by the focused cursor owner."""
        self._cursor.update_brush(erase_indicator=erase_indicator)

    def update_modifier_key_cursor(self) -> None:
        """Refresh mode-sensitive cursors when Alt or Shift toggles."""
        self._cursor.update_for_modifiers()

    def handle_drag_start_request(self, event: QMouseEvent | None) -> None:
        """Delegate source selection and MIME policy to the host-facing facade."""
        if not self._qpane._start_outbound_drag(event) and event is not None:
            event.ignore()

    def _forward_tool_event(
        self,
        handler: Callable[[object], None],
        event,
        *,
        guard_blank: bool = True,
        guard_image: bool = False,
    ) -> None:
        """Forward Qt events to the active tool while respecting blank/image guards.

        Args:
            handler: Callable on the tool manager that accepts the event.
            event: Qt event to dispatch.
            guard_blank: Skip dispatch when the CuteCanvas is blank.
            guard_image: Skip dispatch when no image is loaded.
        """
        qpane = self._qpane
        if guard_blank and qpane._is_blank:
            return
        if guard_image and not qpane.view().has_renderable_content():
            return
        handler(event)

    def handle_wheel_event(self, event: QWheelEvent) -> None:
        """Forward wheel events to the active tool when content exists."""
        self._forward_tool_event(
            self._qpane._tools_manager.wheelEvent, event, guard_image=True
        )

    def handle_touch_event(self, event) -> bool:
        """Route a touch frame through device-neutral input coordination."""
        return self._pointer_input.handle_touch_event(event)

    def handle_tablet_event(self, event) -> bool:
        """Route a tablet frame through device-neutral input coordination."""
        return self._pointer_input.handle_tablet_event(event)

    def handle_mouse_press(self, event: QMouseEvent) -> None:
        """Forward mouse press events to the active tool."""
        if not self._pointer_input.observe_mouse_event(event):
            event.accept()
            return
        self._forward_tool_event(self._qpane._tools_manager.mousePressEvent, event)
        self._synchronize_effective_cursor()

    def handle_mouse_move(self, event: QMouseEvent) -> None:
        """Forward mouse move events to the active tool."""
        if not self._pointer_input.observe_mouse_event(event):
            event.accept()
            return
        self._forward_tool_event(self._qpane._tools_manager.mouseMoveEvent, event)
        self._synchronize_effective_cursor()

    def handle_mouse_release(self, event: QMouseEvent) -> None:
        """Forward mouse release events to the active tool."""
        if not self._pointer_input.observe_mouse_event(event):
            event.accept()
            return
        self._forward_tool_event(self._qpane._tools_manager.mouseReleaseEvent, event)
        self._synchronize_effective_cursor()

    def handle_mouse_double_click(self, event: QMouseEvent) -> None:
        """Forward double-click events to the active tool."""
        if not self._pointer_input.observe_mouse_event(event):
            event.accept()
            return
        self._forward_tool_event(
            self._qpane._tools_manager.mouseDoubleClickEvent, event
        )
        self._synchronize_effective_cursor()

    def handle_enter_event(self, event) -> None:
        """Notify the active tool that the cursor entered the widget."""
        self._pointer_input.observe_enter_event(event)
        self.update_cursor()
        self._forward_tool_event(
            self._qpane._tools_manager.enterEvent, event, guard_blank=False
        )
        self._synchronize_effective_cursor()

    def handle_leave_event(self, event) -> None:
        """Notify the active tool that the cursor left the widget."""
        self._pointer_input.handle_widget_leave()
        self._forward_tool_event(
            self._qpane._tools_manager.leaveEvent, event, guard_blank=False
        )

    def _handle_pointer_state_changed(self) -> None:
        """Reconcile CuteCanvas's cursor with direct-input lifecycle state."""
        self.update_cursor()

    def _synchronize_effective_cursor(self) -> None:
        """Apply CuteCanvas's desired cursor to its active Qt window synchronously."""
        self._cursor.synchronize_window()

    def handle_show_event(self) -> None:
        """Ensure pan/zoom is active on first show and force view alignment."""
        self._pointer_input.set_application_observation(True)
        if not self._tools_activated:
            self.set_control_mode(Tools.CONTROL_MODE_PANZOOM)
            self._tools_activated = True
        self._qpane.view().ensure_view_alignment(force=True)

    def handle_hide_event(self) -> None:
        """Release application-wide pointer observation while hidden."""
        self._pointer_input.set_application_observation(False)
        self._pointer_input.cancel_active_sequences()

    def shutdown(self) -> None:
        """Release application-level input hooks owned by this delegate."""
        self._pointer_input.shutdown()

    def handle_key_press(self, event) -> bool:
        """Handle copy, modifier, and temporary pan shortcuts before delegating to Qt.

        Args:
            event: QKeyEvent raised by the CuteCanvas widget.

        Returns:
            bool: True when the delegate consumed the event.
        """
        qpane = self._qpane
        if qpane._is_blank:
            return True
        focused_widget = QApplication.focusWidget()
        if event.matches(QKeySequence.StandardKey.Copy):
            if qpane.isAncestorOf(focused_widget):
                event.ignore()
                qpane._tools_manager.keyPressEvent(event)
            else:
                super(type(qpane), qpane).keyPressEvent(event)
            return event.isAccepted()
        if event.key() == Qt.Key_Shift:
            if not event.isAutoRepeat():
                self._shift_key_held = True
                qpane.update()
            event.accept()
            return True
        if event.key() == Qt.Key_Alt:
            if not event.isAutoRepeat():
                self.alt_key_held = True
                self.update_modifier_key_cursor()
            event.accept()
            return True
        if event.key() == Qt.Key_Space:
            active_tool = qpane._tools_manager.get_active_tool()
            captures_space = getattr(active_tool, "captures_space_key", None)
            if callable(captures_space) and captures_space():
                event.ignore()
                qpane._tools_manager.keyPressEvent(event)
                return event.isAccepted()
            if not event.isAutoRepeat():
                current_mode = self.get_control_mode()
                if current_mode != Tools.CONTROL_MODE_PANZOOM:
                    suspend = getattr(
                        active_tool,
                        "suspend_for_temporary_navigation",
                        None,
                    )
                    if callable(suspend):
                        suspend()
                    self._mode_before_pan = current_mode
                    self.set_control_mode(Tools.CONTROL_MODE_PANZOOM)
            event.accept()
            return True
        event.ignore()
        qpane._tools_manager.keyPressEvent(event)
        return event.isAccepted()

    def handle_key_release(self, event) -> bool:
        """Reset Alt/Shift/Space state and report whether the event was consumed.

        Args:
            event: QKeyEvent raised by the CuteCanvas widget.

        Returns:
            bool: True when the delegate handled the event.
        """
        if event.key() == Qt.Key_Space:
            if not event.isAutoRepeat() and self._mode_before_pan is not None:
                self.set_control_mode(self._mode_before_pan)
                self._mode_before_pan = None
            event.accept()
            return True
        if event.key() == Qt.Key_Alt:
            if not event.isAutoRepeat():
                self.alt_key_held = False
                self.update_modifier_key_cursor()
            event.accept()
            return True
        if event.key() == Qt.Key_Shift:
            if not event.isAutoRepeat():
                self._shift_key_held = False
                self._qpane.update()
            event.accept()
            return True
        event.ignore()
        self._qpane._tools_manager.keyReleaseEvent(event)
        return event.isAccepted()
