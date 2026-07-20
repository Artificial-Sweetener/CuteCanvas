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

"""Delegate handling QPane's widget interaction and tool coordination."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QCursor,
    QKeySequence,
    QMouseEvent,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import QApplication

from .. import ui
from ..core import CursorProvider, OverlayDrawFn, SceneOverlayDrawFn
from ..editor import EditorOperation, EditorOperationTarget
from ..ui import (
    apply_widget_defaults,
)
from ..vector.public import VectorShapeKind
from .input import PointerInputController
from .ports import (
    CursorInteractionPort,
    MoveInteractionPort,
    NavigationInteractionPort,
    PaintingInteractionPort,
    PixelSelectionInteractionPort,
    SmartSelectionInteractionPort,
    TransformInteractionPort,
    VectorInteractionPort,
    VectorNodeInteractionPort,
    VectorTextInteractionPort,
    tool_activation_ports,
)
from .tools import Tools

if TYPE_CHECKING:  # pragma: no cover - import guard for typing only

    from ..qpane import QPane
logger = logging.getLogger(__name__)


class ToolInteractionDelegate:
    """Encapsulate cursor, overlay, and tool input plumbing for :class:`QPane`."""

    def __init__(self, qpane: QPane) -> None:
        """Initialize the delegate with the owning QPane widget."""
        self._qpane = qpane
        self._tools_activated = False
        self._mode_before_pan: str | None = None
        self._custom_cursor = None
        self._preview_outline_pen = QPen(Qt.black, 1, Qt.SolidLine)
        self._preview_inline_pen = QPen(Qt.white, 1, Qt.DashLine)
        self._brush_size = qpane.settings.default_brush_size
        self._alt_key_held = False
        self._shift_key_held = False
        self._content_overlays: dict[str, OverlayDrawFn] = {}
        self._scene_overlays: dict[str, SceneOverlayDrawFn] = {}
        self._cursor_providers: dict[str, CursorProvider] = {}
        self._overlays_suspended = False
        self._overlays_resume_pending = False
        self._drag_request_handler = None
        self._copy_image_handler = None
        self._pointer_input = PointerInputController(
            qpane,
            on_pointer_state_changed=self._handle_pointer_state_changed,
        )

    def _viewport(self):
        """Return the viewport managed by the rendering stack."""
        return self._qpane.view().viewport

    @property
    def content_overlays(self) -> dict[str, OverlayDrawFn]:
        """Return overlay draw callbacks keyed by overlay name."""
        return self._content_overlays

    @property
    def scene_overlays(self) -> dict[str, SceneOverlayDrawFn]:
        """Return scene overlay callbacks keyed by overlay name."""
        return self._scene_overlays

    @property
    def custom_cursor(self):
        """Return the last cursor QPane forced while tools were active."""
        return self._custom_cursor

    @custom_cursor.setter
    def custom_cursor(self, cursor) -> None:
        """Record a custom cursor so mask workflows can restore it."""
        self._custom_cursor = cursor

    @property
    def brush_size(self) -> int:
        """Return the current brush diameter in device pixels."""
        return self._brush_size

    @brush_size.setter
    def brush_size(self, size: int) -> None:
        """Clamp and persist the brush size supplied by masks tools."""
        self._brush_size = max(1, int(size))

    @property
    def alt_key_held(self) -> bool:
        """Return True when the delegate detected an Alt press."""
        return self._alt_key_held

    @alt_key_held.setter
    def alt_key_held(self, value: bool) -> None:
        """Update the cached Alt state used by cursor providers."""
        self._alt_key_held = bool(value)

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
        return self._overlays_suspended

    @overlays_suspended.setter
    def overlays_suspended(self, value: bool) -> None:
        """Track overlay suspension state for resume helpers."""
        self._overlays_suspended = bool(value)

    @property
    def overlays_resume_pending(self) -> bool:
        """Return True when overlays should resume after navigation."""
        return self._overlays_resume_pending

    @overlays_resume_pending.setter
    def overlays_resume_pending(self, value: bool) -> None:
        """Mark whether a resume call should run after navigation completes."""
        self._overlays_resume_pending = bool(value)

    def initialize_widget_properties(self) -> None:
        """Apply widget defaults for the QPane widget once."""
        qpane = self._qpane
        apply_widget_defaults(qpane)

    def connect_signals(self) -> None:
        """Wire viewport, catalog, and tool-manager callbacks to the QPane.

        Hooks viewChanged, caches catalog drag/copy helpers, and relays tool-manager
        signals so initialization only needs to happen once.
        """
        qpane = self._qpane
        viewport = self._viewport()
        viewport.viewChanged.connect(qpane.onViewChanged)
        tools = qpane._tools_manager
        tm_signals = tools.signals
        tm_signals.pan_requested.connect(viewport.setPan)
        tm_signals.zoom_requested.connect(qpane._apply_zoom_interpolated)
        tm_signals.zoom_snap_requested.connect(qpane._apply_zoom_interpolated_with_mode)
        catalog = qpane.catalog()
        self._drag_request_handler = catalog.handleDragRequest
        self._copy_image_handler = catalog.copyCurrentImageToClipboard
        tm_signals.drag_start_maybe_requested.connect(self.handle_drag_start_request)
        tm_signals.cursor_update_requested.connect(self.update_cursor)
        tm_signals.repaint_overlay_requested.connect(qpane.update)

    def registerOverlay(self, name: str, draw_fn: OverlayDrawFn) -> None:
        """Register an overlay draw hook under the provided identifier."""
        if name in self._content_overlays:
            raise ValueError(f"Overlay '{name}' already registered")
        self._content_overlays[name] = draw_fn

    def unregisterOverlay(self, name: str) -> None:
        """Remove a previously registered overlay if it exists."""
        self._content_overlays.pop(name, None)

    def content_overlays_snapshot(self) -> Mapping[str, OverlayDrawFn]:
        """Return a read-only snapshot of registered content overlays."""
        return MappingProxyType(dict(self._content_overlays))

    def registerSceneOverlay(self, name: str, draw_fn: SceneOverlayDrawFn) -> None:
        """Register a scene overlay draw hook under the provided identifier."""
        if name in self._scene_overlays:
            raise ValueError(f"Scene overlay '{name}' already registered")
        self._scene_overlays[name] = draw_fn

    def unregisterSceneOverlay(self, name: str) -> None:
        """Remove a previously registered scene overlay if it exists."""
        self._scene_overlays.pop(name, None)

    def scene_overlays_snapshot(self) -> Mapping[str, SceneOverlayDrawFn]:
        """Return a read-only snapshot of registered scene overlays."""
        return MappingProxyType(dict(self._scene_overlays))

    def registerCursorProvider(self, mode: str, provider: CursorProvider) -> None:
        """Attach a cursor provider for the given mode and apply it immediately when active."""
        self._cursor_providers[mode] = provider
        if self._qpane._tools_manager.get_control_mode() == mode:
            self.update_cursor()

    def unregisterCursorProvider(self, mode: str) -> None:
        """Remove the cursor provider tied to the supplied control mode."""
        self._cursor_providers.pop(mode, None)
        if self._qpane._tools_manager.get_control_mode() == mode:
            self.update_cursor()

    def suspend_overlays_for_navigation(self) -> None:
        """Flag content overlays as hidden until navigation completes."""
        self._pointer_input.cancel_active_sequences()
        self._overlays_suspended = True
        self._overlays_resume_pending = True

    def cancel_active_editor_input(self) -> None:
        """Cancel captured pointer work before host editor policy changes."""
        self._pointer_input.cancel_active_sequences()

    def resume_overlays(self) -> None:
        """Resume overlays immediately without forcing a repaint."""
        ui.resume_overlays(self)

    def resume_overlays_and_update(self) -> None:
        """Resume overlays and schedule a QPane repaint."""
        ui.resume_overlays_and_update(self._qpane, self)

    def maybe_resume_overlays(self) -> None:
        """Allow the UI helpers to resume overlays when pending."""
        ui.maybe_resume_overlays(self._qpane, self)

    def blank(self) -> None:
        """Mark the QPane as blank while resetting cursor and overlay state.

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
            ToolDependencies payload from the viewport and QPane state, and forwards it
            to the tool manager.
        """
        qpane = self._qpane
        catalog = qpane.catalog()
        placeholder_policy = catalog.placeholderPolicy()
        if catalog.placeholderActive():
            panzoom_enabled = bool(
                getattr(placeholder_policy, "panzoom_enabled", False)
            )
            mask_modes = {
                Tools.CONTROL_MODE_DRAW_BRUSH,
                Tools.CONTROL_MODE_SMART_SELECT,
            }
            if not panzoom_enabled:
                mode = Tools.CONTROL_MODE_CURSOR
            elif mode in mask_modes:
                mode = Tools.CONTROL_MODE_PANZOOM
        tools = qpane._tools_manager
        viewport = self._viewport()
        if mode == Tools.CONTROL_MODE_DRAW_BRUSH:
            resolution = qpane.editorOperationResolver().resolve(EditorOperation.PAINT)
            mask_service = getattr(qpane, "mask_service", None)
            if (
                resolution.target is EditorOperationTarget.DEFAULT_PAINT_TARGET
                and mask_service is not None
            ):
                current_image_id = qpane.catalog().currentImageID()
                if mask_service.ensureTopMaskActiveForImage(current_image_id):
                    mask_service.prepareBrushInteraction()
                    qpane.view().coordinate_scene_descriptor()
                    resolution = qpane.editorOperationResolver().resolve(
                        EditorOperation.PAINT
                    )
            if resolution.allowed and mask_service is not None:
                mask_service.prepareBrushInteraction()
        elif mode == Tools.CONTROL_MODE_SMART_SELECT:
            if not qpane.samFeatureAvailable():
                qpane.featureFallbacks().get("sam", "setControlMode", default=None)
                return
        is_image_null = lambda: not qpane.view().has_renderable_content()
        can_pan = lambda: (
            False
            if is_image_null()
            else viewport.can_pan(
                zoom=viewport.zoom,
                image_size=qpane.view().content_rect().size(),
                panel_size=qpane.physicalViewportRect().size(),
            )
        )
        active_mask_color = lambda: (
            qpane.mask_service.getActiveMaskColor() if qpane.mask_service else None
        )
        panel_to_active_mask = qpane.activeMaskLayerCoordinates().panel_to_source
        active_mask_to_panel = qpane.activeMaskLayerCoordinates().source_to_panel
        cursor_port = CursorInteractionPort(
            is_drag_out_allowed=qpane.isDragOutAllowed,
            is_image_null=is_image_null,
        )
        navigation_port = NavigationInteractionPort(
            is_pan_zoom_locked=viewport.is_locked,
            is_image_null=is_image_null,
            is_drag_out_allowed=qpane.isDragOutAllowed,
            can_pan=can_pan,
            get_pan=lambda: viewport.pan,
            get_zoom=lambda: viewport.zoom,
            get_native_zoom=viewport.nativeZoom,
            get_fit_zoom=viewport.computeFitZoom,
            get_zoom_mode=viewport.get_zoom_mode,
            set_zoom_fit=viewport.setZoomFit,
            set_zoom_fit_interpolated=qpane._apply_zoom_fit_interpolated,
            set_zoom_one_to_one=viewport.setZoom1To1,
            set_zoom_one_to_one_interpolated=(
                qpane._apply_zoom_one_to_one_interpolated
            ),
            get_dpr=qpane.devicePixelRatioF,
        )
        movement = qpane.editorMovementInteraction()
        movement_port = MoveInteractionPort(
            begin_move=movement.begin,
            update_move=movement.update,
            finish_move=movement.finish,
            suspend_move=movement.suspend,
            cancel_move=movement.cancel,
            anchor_move=movement.anchor_floating_pixels,
            update_move_hover=movement.update_hover,
            clear_move_hover=movement.clear_hover,
            move_target_available=lambda: movement.target_available,
            nudge_move=movement.nudge,
        )
        transform = qpane.sceneLayerTransformInteraction()
        transform_port = TransformInteractionPort(
            transform_presentation=transform.presentation,
            begin_transform=transform.begin,
            update_transform=transform.update,
            end_transform_gesture=transform.end_gesture,
            commit_transform=transform.commit,
            cancel_transform=transform.cancel,
            suspend_transform=transform.suspend,
        )
        selection_port = PixelSelectionInteractionPort(
            panel_to_scene_point=qpane.view().panel_to_scene_point,
            can_select=lambda: qpane.editorOperationResolver()
            .resolve(EditorOperation.SELECT_PIXELS)
            .allowed,
            commit_pixel_selection=(
                qpane.editorInteraction().commit_active_pixel_selection
            ),
            is_shift_held=lambda: self._shift_key_held,
            is_alt_held=lambda: self._alt_key_held,
        )
        painting_port = PaintingInteractionPort(
            is_alt_held=lambda: self._alt_key_held,
            is_shift_held=lambda: self._shift_key_held,
            can_paint=lambda: qpane.editorOperationResolver()
            .resolve(EditorOperation.PAINT)
            .allowed,
            get_brush_size=lambda: self._brush_size,
            get_preview_pens=lambda: (
                self._preview_outline_pen,
                self._preview_inline_pen,
            ),
            panel_hit_test=qpane.panelHitTest,
            panel_hit_test_precise=viewport.panel_hit_test,
            panel_to_content_point=viewport.panel_to_content_point,
            image_to_panel_point=viewport.content_to_panel_point,
            panel_to_target_point=qpane.paintingCoordinator().panel_to_target,
            target_to_panel_point=qpane.paintingCoordinator().target_to_panel,
            is_point_in_widget=lambda point: qpane.rect().contains(point),
            get_image_rect=qpane.view().content_rect,
            get_brush_increment=lambda: qpane.settings.brush_scroll_increment,
            get_pen_pressure_min_ratio=(lambda: qpane.settings.pen_pressure_min_ratio),
            get_pen_pressure_gamma=lambda: qpane.settings.pen_pressure_gamma,
            get_pen_pressure_enabled=(lambda: qpane.settings.pen_pressure_enabled),
            get_pressure_diameter=qpane.paintingCoordinator().diameter_for_pressure,
            get_smoothing=lambda: qpane.paintingCoordinator().preset.smoothing,
            get_zoom=lambda: viewport.zoom,
            get_dpr=qpane.devicePixelRatioF,
            get_preview_color=qpane.paintingCoordinator().preview_color,
            request_overlay_update=qpane.update,
        )
        smart_selection_port = SmartSelectionInteractionPort(
            is_alt_held=lambda: self._alt_key_held,
            get_dpr=qpane.devicePixelRatioF,
            panel_to_content_point=viewport.panel_to_content_point,
            image_to_panel_point=viewport.content_to_panel_point,
            panel_to_active_mask_point=panel_to_active_mask,
            active_mask_to_panel_point=active_mask_to_panel,
            get_min_selection_size=(lambda: qpane.settings.smart_select_min_size),
            get_active_mask_color=active_mask_color,
        )
        vector_interaction = qpane._vector_interaction_controller()
        vector_port = VectorInteractionPort(
            panel_to_source=vector_interaction.panel_to_active_source,
            commit_shape=vector_interaction.commit_shape,
            commit_path=lambda points, closed: vector_interaction.commit_path(
                points,
                closed=closed,
            ),
            shape_is_ellipse=lambda: (
                vector_interaction.shape is VectorShapeKind.ELLIPSE
            ),
        )
        vector_nodes = qpane._vector_node_controller()
        vector_node_port = VectorNodeInteractionPort(
            begin=vector_nodes.begin,
            update=vector_nodes.update,
            finish=vector_nodes.finish,
            cancel=vector_nodes.cancel,
            overlay_state=vector_nodes.overlay_state,
        )
        vector_text = qpane._vector_text_controller()
        vector_text_port = VectorTextInteractionPort(
            begin_at=vector_text.begin_at,
            insert=vector_text.insert,
            backspace=vector_text.backspace,
            delete=vector_text.delete,
            move_cursor=vector_text.move_cursor,
            move_cursor_to=vector_text.move_cursor_to,
            text_length=lambda: (
                0 if vector_text.state() is None else len(vector_text.state().text)
            ),
            commit=vector_text.commit,
            cancel=vector_text.cancel,
            active=lambda: vector_text.active,
            overlay_state=vector_text.overlay_state,
        )
        ports = tool_activation_ports(
            cursor=cursor_port,
            navigation=navigation_port,
            movement=movement_port,
            transform=transform_port,
            pixel_selection=selection_port,
            painting=painting_port,
            smart_selection=smart_selection_port,
            domain_ports={
                qpane.CONTROL_MODE_VECTOR_SHAPE: vector_port,
                qpane.CONTROL_MODE_VECTOR_PATH: vector_port,
                qpane.CONTROL_MODE_VECTOR_NODE: vector_node_port,
                qpane.CONTROL_MODE_VECTOR_TEXT: vector_text_port,
            },
        )

        if tools.get_control_mode() != mode:
            self._pointer_input.cancel_active_sequences()
        tools.set_mode(mode, ports)
        self._tools_activated = True

    def get_control_mode(self) -> str:
        """Return the current tool control mode."""
        return self._qpane._tools_manager.get_control_mode()

    def update_cursor(self) -> None:
        """Compute and apply the cursor for the active tool or registered providers.

        Prefers the active tool's getCursor(), then any registered provider, and finally
        mask/smart-select cursors or the default arrow.
        """
        qpane = self._qpane
        if qpane._is_blank:
            qpane.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            return
        if self._pointer_input.cursor_suppressed:
            qpane.setCursor(QCursor(Qt.CursorShape.BlankCursor))
            return
        try:
            divider_cursor = qpane.comparisonDividerInteraction().cursor()
        except AttributeError:
            divider_cursor = None
        if divider_cursor is not None:
            qpane.setCursor(divider_cursor)
            return
        tools = qpane._tools_manager
        active_tool = tools.get_active_tool()
        if active_tool and hasattr(active_tool, "getCursor"):
            try:
                cursor = active_tool.getCursor()
            except Exception:
                logger.exception("Active tool failed to provide cursor")
                cursor = None
            if cursor is not None:
                qpane.setCursor(cursor)
                return
        control_mode = tools.get_control_mode()
        provider = self._cursor_providers.get(control_mode)
        if provider is not None:
            custom_cursor = provider(qpane)
            if custom_cursor is not None:
                qpane.setCursor(custom_cursor)
                return
        if control_mode == Tools.CONTROL_MODE_DRAW_BRUSH:
            self.update_brush_cursor(erase_indicator=self._alt_key_held)
        elif control_mode == Tools.CONTROL_MODE_SMART_SELECT:
            cursor = qpane.cursor_builder.create_smart_select_cursor(
                erase_indicator=self._alt_key_held
            )
            qpane.setCursor(cursor)
        else:
            qpane.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def update_brush_cursor(self, *, erase_indicator: bool = False) -> None:
        """Render target-neutral brush feedback for the active paint destination."""
        qpane = self._qpane
        resolution = qpane.editorOperationResolver().resolve(EditorOperation.PAINT)
        if not resolution.allowed:
            qpane.interaction.custom_cursor = None
            qpane.setCursor(QCursor(Qt.CursorShape.ForbiddenCursor))
            return
        color = qpane.paintingCoordinator().preview_color()
        if color is None:
            qpane.interaction.custom_cursor = None
            qpane.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            return
        zoom = max(1e-6, float(qpane.view().viewport.zoom))
        dpr = max(1e-6, float(qpane.devicePixelRatioF()))
        source_size = max(1, int(qpane.interaction.brush_size))
        logical_size = source_size * zoom / dpr
        viewport_size = qpane.size()
        if logical_size > min(viewport_size.width(), viewport_size.height()):
            qpane.interaction.custom_cursor = None
            qpane.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            return
        cursor = qpane.cursor_builder.create_brush_cursor(
            max(2, round(logical_size)),
            color,
            erase_indicator=erase_indicator,
        )
        qpane.interaction.custom_cursor = cursor
        qpane.setCursor(cursor)

    def update_modifier_key_cursor(self) -> None:
        """Refresh mode-sensitive cursors when Alt or Shift toggles."""
        mode = self.get_control_mode()
        if mode in (
            Tools.CONTROL_MODE_DRAW_BRUSH,
            Tools.CONTROL_MODE_SMART_SELECT,
        ):
            self.update_cursor()

    def handle_drag_start_request(self, event: QMouseEvent | None) -> None:
        """Trigger and cache the catalog drag handler for the current image."""
        handler = self._drag_request_handler
        if handler is None:
            handler = self._qpane.catalog().handleDragRequest
            self._drag_request_handler = handler
        handler(event)

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
            guard_blank: Skip dispatch when the QPane is blank.
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
        if self._qpane.comparisonDividerInteraction().handle_mouse_press(event):
            self._synchronize_effective_cursor()
            return
        self._forward_tool_event(self._qpane._tools_manager.mousePressEvent, event)
        self._synchronize_effective_cursor()

    def handle_mouse_move(self, event: QMouseEvent) -> None:
        """Forward mouse move events to the active tool."""
        if not self._pointer_input.observe_mouse_event(event):
            event.accept()
            return
        divider = self._qpane.comparisonDividerInteraction()
        had_divider_cursor = divider.owns_cursor()
        if divider.handle_mouse_move(event):
            self.update_cursor()
            self._synchronize_effective_cursor()
            return
        if had_divider_cursor or divider.owns_cursor():
            self.update_cursor()
        self._forward_tool_event(self._qpane._tools_manager.mouseMoveEvent, event)
        self._synchronize_effective_cursor()

    def handle_mouse_release(self, event: QMouseEvent) -> None:
        """Forward mouse release events to the active tool."""
        if not self._pointer_input.observe_mouse_event(event):
            event.accept()
            return
        if self._qpane.comparisonDividerInteraction().handle_mouse_release(event):
            self.update_cursor()
            self._synchronize_effective_cursor()
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

    def handle_leave_event(self, event) -> None:
        """Notify the active tool that the cursor left the widget."""
        self._pointer_input.handle_widget_leave()
        self._qpane.comparisonDividerInteraction().cancel_drag()
        self._qpane.update()
        self._forward_tool_event(
            self._qpane._tools_manager.leaveEvent, event, guard_blank=False
        )

    def _handle_pointer_state_changed(self) -> None:
        """Reconcile QPane's cursor with direct-input lifecycle state."""
        self.update_cursor()

    def _synchronize_effective_cursor(self) -> None:
        """Apply QPane's desired cursor to its active Qt window synchronously."""
        top_level = self._qpane.window()
        window = top_level.windowHandle() if top_level is not None else None
        if window is None:
            return
        desired = self._qpane.cursor()
        if self._cursor_states_match(window.cursor(), desired):
            return
        window.setCursor(desired)

    @staticmethod
    def _cursor_states_match(current: QCursor, desired: QCursor) -> bool:
        """Return whether two Qt cursors have the same observable appearance."""
        if current.shape() != desired.shape():
            return False
        if desired.shape() != Qt.CursorShape.BitmapCursor:
            return True
        current_pixmap = current.pixmap()
        desired_pixmap = desired.pixmap()
        return (
            current_pixmap.cacheKey() == desired_pixmap.cacheKey()
            and current.hotSpot() == desired.hotSpot()
        )

    def handle_show_event(self) -> None:
        """Ensure pan/zoom is active on first show and force view alignment."""
        if not self._tools_activated:
            self.set_control_mode(Tools.CONTROL_MODE_PANZOOM)
            self._tools_activated = True
        self._qpane.view().ensure_view_alignment(force=True)

    def handle_key_press(self, event) -> bool:
        """Handle copy, modifier, and temporary pan shortcuts before delegating to Qt.

        Args:
            event: QKeyEvent raised by the QPane widget.

        Returns:
            bool: True when the delegate consumed the event.
        """
        qpane = self._qpane
        if qpane._is_blank:
            return True
        focused_widget = QApplication.focusWidget()
        if event.matches(QKeySequence.StandardKey.Copy):
            if qpane.isAncestorOf(focused_widget):
                handler = self._copy_image_handler
                if handler is None:
                    handler = qpane.catalog().copyCurrentImageToClipboard
                    self._copy_image_handler = handler
                handler()
            else:
                super(type(qpane), qpane).keyPressEvent(event)
            return True
        if event.key() == Qt.Key_Shift:
            if not event.isAutoRepeat():
                self._shift_key_held = True
                qpane.update()
            event.accept()
            return True
        if event.key() == Qt.Key_Alt:
            if not event.isAutoRepeat():
                self._alt_key_held = True
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
            event: QKeyEvent raised by the QPane widget.

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
                self._alt_key_held = False
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
