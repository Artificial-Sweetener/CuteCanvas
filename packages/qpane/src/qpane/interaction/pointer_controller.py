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

"""Qt pointer event normalization and direct-input sequence ownership."""

from __future__ import annotations

import math
import time
from dataclasses import replace

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import (
    QEnterEvent,
    QEventPoint,
    QInputDevice,
    QMouseEvent,
    QPointingDevice,
    QTabletEvent,
    QTouchEvent,
)
from PySide6.QtWidgets import QApplication

from .arena import TouchGestureArena, TouchGestureKind
from .pointer import PointerDeviceKind, PointerPhase, PointerSample
from .pointer_port import PointerInputPort
from .profile import ToolInputProfile
from .touch_navigation import TouchNavigationPort, TouchNavigationSession

_SYNTHETIC_MOUSE_DEDUP_SECONDS = 0.35
_SYNTHETIC_MOUSE_DEDUP_DISTANCE = 4.0


class PointerInputController(QObject):
    """Normalize direct input and coordinate ownership of active sequences."""

    def __init__(
        self,
        port: PointerInputPort,
    ) -> None:
        """Capture the host port and initialize empty input state."""
        super().__init__(port.widget)
        self._port = port
        self._active_device = PointerDeviceKind.MOUSE
        self._active_touches: dict[int, QPointF] = {}
        self._touch_sequence_claimed = False
        self._navigation = TouchNavigationSession(
            TouchNavigationPort(
                viewport=port.viewport,
                device_pixel_ratio=port.widget.devicePixelRatioF,
                physical_viewport_rect=port.physical_viewport_rect,
                inertia_enabled=port.touch_inertia_enabled,
                inertia_deceleration=port.touch_inertia_deceleration,
            )
        )
        self._touch_arena = TouchGestureArena()
        self._primary_touch_id: int | None = None
        self._primary_touch_origin: QPointF | None = None
        self._primary_touch_begin: PointerSample | None = None
        self._touch_max_contacts = 0
        self._touch_divider_claimed = False
        self._touch_preview_allowed = False
        self._touch_tool_active = False
        self._last_touch_position: QPointF | None = None
        self._last_touch_ended_at: float | None = None
        self._last_navigation_tap_at: float | None = None
        self._last_navigation_tap_position: QPointF | None = None
        self._pen_last_seen_at: float | None = None
        self._pen_contact_active = False
        self._pen_in_proximity = False
        self._application_filter_installed = False

    def set_application_observation(self, enabled: bool) -> None:
        """Observe global pen proximity only while the owning pane is visible."""
        requested = bool(enabled)
        if requested == self._application_filter_installed:
            return
        application = QApplication.instance()
        if application is None:
            return
        if requested:
            application.installEventFilter(self)
        else:
            application.removeEventFilter(self)
            self._pen_in_proximity = False
        self._application_filter_installed = requested

    @property
    def active_device(self) -> PointerDeviceKind:
        """Return the physical modality that most recently owned interaction."""
        return self._active_device

    @property
    def touch_sequence_claimed(self) -> bool:
        """Return whether CuteCanvas currently owns an active touch sequence."""
        return self._touch_sequence_claimed

    @property
    def cursor_suppressed(self) -> bool:
        """Return whether active direct input requires hiding QWidget's cursor."""
        pen_owns_proximity = self._pen_in_proximity and self._active_device in {
            PointerDeviceKind.PEN,
            PointerDeviceKind.ERASER,
        }
        return self._touch_sequence_claimed or pen_owns_proximity

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Observe application-level tablet proximity events for this pane."""
        del watched
        event_type = event.type()
        if event_type == QEvent.Type.TabletEnterProximity:
            self._pen_in_proximity = True
        elif event_type == QEvent.Type.TabletLeaveProximity:
            self._handle_pen_proximity_leave()
        return False

    def handle_touch_event(self, event: QTouchEvent) -> bool:
        """Arbitrate and route one complete touchscreen frame."""
        if event.type() == QEvent.Type.TouchCancel:
            claimed = self._touch_sequence_claimed
            self._remember_touch_end()
            if self._touch_divider_claimed:
                self._port.cancel_external_touch()
            self._cancel_touch_tool()
            self._clear_pointer_preview()
            self.cancel_touch_sequence()
            return claimed
        if event.type() == QEvent.Type.TouchBegin:
            self._begin_touch_sequence(event)
        if not self._touch_sequence_claimed:
            return False
        samples = {
            point.id(): self.touch_sample(point, event) for point in event.points()
        }
        frame_positions = dict(self._active_touches)
        for point in event.points():
            frame_positions[point.id()] = QPointF(point.position())
        self._touch_max_contacts = max(
            self._touch_max_contacts,
            len(frame_positions),
        )
        primary_sample = (
            samples.get(self._primary_touch_id)
            if self._primary_touch_id is not None
            else None
        )
        if primary_sample is not None:
            self._last_touch_position = QPointF(primary_sample.position)
        active_after_frame = {
            point_id: position
            for point_id, position in frame_positions.items()
            if samples.get(point_id, None) is None
            or samples[point_id].phase is not PointerPhase.END
        }
        if self._touch_divider_claimed:
            if primary_sample is not None:
                divider = self._port
                if primary_sample.phase is PointerPhase.END:
                    divider.finish_external_touch(primary_sample.position)
                else:
                    divider.update_external_touch(primary_sample.position)
            self._active_touches = active_after_frame
            if event.type() == QEvent.Type.TouchEnd:
                self.cancel_touch_sequence()
            return True
        ending = event.type() == QEvent.Type.TouchEnd or (
            primary_sample is not None and primary_sample.phase is PointerPhase.END
        )
        previous_kind = self._touch_arena.kind
        kind = self._touch_arena.evaluate(
            contact_count=max(len(active_after_frame), 1 if ending else 0),
            primary_distance=self._primary_touch_distance(primary_sample),
            ending=ending,
        )
        if previous_kind is TouchGestureKind.PENDING:
            if kind is TouchGestureKind.NAVIGATION:
                self._cancel_touch_tool()
                self._clear_pointer_preview()
                self._set_active_device(PointerDeviceKind.TOUCH)
            elif (
                kind is TouchGestureKind.PENDING
                and primary_sample is not None
                and self._touch_tool_active
                and primary_sample.phase is PointerPhase.UPDATE
            ):
                self._route_touch_tool(primary_sample, previous_kind)
            elif (
                kind is TouchGestureKind.PENDING
                and primary_sample is not None
                and self._touch_preview_allowed
            ):
                self._preview_pointer_sample(primary_sample)
        if kind is TouchGestureKind.NAVIGATION:
            if self._touch_navigation_allowed():
                self._navigation.update(
                    frame_positions,
                    timestamp_ms=max(
                        (sample.timestamp_ms for sample in samples.values()),
                        default=None,
                    ),
                )
        elif kind is TouchGestureKind.DIRECT_TOOL and primary_sample is not None:
            self._route_touch_tool(primary_sample, previous_kind)
        self._active_touches = active_after_frame
        if event.type() == QEvent.Type.TouchEnd:
            if kind is TouchGestureKind.NAVIGATION and primary_sample is not None:
                self._maybe_handle_navigation_tap(primary_sample)
                self._navigation.finish()
            self._remember_touch_end(
                None if primary_sample is None else primary_sample.position
            )
            self.cancel_touch_sequence()
        return True

    def handle_tablet_event(self, event: QTabletEvent) -> bool:
        """Route active-pen samples to tools that declare tablet support."""
        port = self._port
        profile = self._active_input_profile()
        if not profile.tablet:
            return False
        if profile.tablet_requires_host_enablement and not port.stylus_tool_enabled():
            return False
        sample = self.tablet_sample(event)
        self._pen_in_proximity = True
        self._set_active_device(sample.device)
        self._pen_last_seen_at = time.monotonic()
        self._pen_contact_active = sample.is_contact
        tool = port.active_tool()
        handler = getattr(tool, "handle_pointer_sample", None)
        if not callable(handler):
            return False
        handled = bool(handler(sample))
        if handled and sample.phase is PointerPhase.END and self._pen_in_proximity:
            device = event.pointingDevice()
            if device.capabilities() & QInputDevice.Capability.Hover:
                preview_handler = getattr(tool, "preview_pointer_sample", None)
                if callable(preview_handler):
                    preview_handler(
                        replace(
                            sample,
                            phase=PointerPhase.HOVER,
                            pressure=0.0,
                            buttons=Qt.MouseButton.NoButton,
                        )
                    )
        return handled

    def observe_mouse_event(self, event: QMouseEvent) -> bool:
        """Restore mouse ownership or reject a synthesized direct-input duplicate."""
        if event.source() == Qt.MouseEventSource.MouseEventNotSynthesized:
            self._adopt_mouse_modality()
            return True
        if self._active_device is PointerDeviceKind.TOUCH:
            if self._touch_sequence_claimed or not self._synthesized_mouse_is_distinct(
                event
            ):
                return False
            self._adopt_mouse_modality()
            return True
        if self._active_device in {
            PointerDeviceKind.PEN,
            PointerDeviceKind.ERASER,
        }:
            if self._synthesized_mouse_is_hover(event):
                self._adopt_mouse_modality()
                return True
            return False
        self._adopt_mouse_modality()
        return True

    def observe_enter_event(self, event: QEnterEvent) -> None:
        """Adopt mouse ownership when a hover-capable pointer enters the pane."""
        if self._pointing_event_uses_hover_device(event):
            self._adopt_mouse_modality()

    def pen_suppresses_touch_tool(self) -> bool:
        """Return whether recent active-pen activity should reject a palm contact."""
        if self._pen_contact_active or (
            self._pen_in_proximity
            and self._active_device in {PointerDeviceKind.PEN, PointerDeviceKind.ERASER}
        ):
            return True
        if self._pen_last_seen_at is None:
            return False
        rejection_window = max(0, int(self._port.palm_rejection_ms())) / 1000.0
        return time.monotonic() - self._pen_last_seen_at <= rejection_window

    def cancel_touch_sequence(self) -> None:
        """Release touch ownership and reset navigation state."""
        self._active_touches.clear()
        self._navigation.reset()
        self._touch_arena.reset()
        self._primary_touch_id = None
        self._primary_touch_origin = None
        self._primary_touch_begin = None
        self._touch_max_contacts = 0
        self._touch_divider_claimed = False
        self._touch_preview_allowed = False
        self._touch_tool_active = False
        self._set_touch_sequence_claimed(False)

    def cancel_active_sequences(self) -> None:
        """Cancel captured touch or pen work before a tool lifecycle transition."""
        self._cancel_touch_tool()
        tool = self._port.active_tool()
        cancel_pointer_stroke = getattr(tool, "cancel_pointer_stroke", None)
        if callable(cancel_pointer_stroke):
            cancel_pointer_stroke()
        self._clear_pointer_preview()
        self.cancel_touch_sequence()
        self._pen_contact_active = False
        self._pen_in_proximity = False
        self._set_active_device(PointerDeviceKind.UNKNOWN)

    def shutdown(self) -> None:
        """Release active sequences and the application-wide proximity filter."""
        self.cancel_active_sequences()
        self.set_application_observation(False)

    def handle_widget_leave(self) -> None:
        """Clear direct feedback when its position leaves the pane."""
        self._clear_pointer_preview()

    @staticmethod
    def touch_sample(point: QEventPoint, event: QTouchEvent) -> PointerSample:
        """Copy a Qt touch point into a stable device-neutral sample."""
        return PointerSample(
            pointer_id=point.id(),
            device=PointerDeviceKind.TOUCH,
            phase=_touch_phase(point.state()),
            position=QPointF(point.position()),
            global_position=QPointF(point.globalPosition()),
            pressure=float(point.pressure()),
            buttons=Qt.MouseButton.NoButton,
            modifiers=event.modifiers(),
            timestamp_ms=int(point.timestamp()),
        )

    @staticmethod
    def tablet_sample(event: QTabletEvent) -> PointerSample:
        """Copy a Qt tablet event into a stable device-neutral sample."""
        return PointerSample(
            pointer_id=int(event.point(0).id()),
            device=_tablet_device_kind(event.pointerType(), event.deviceType()),
            phase=_tablet_phase(event),
            position=QPointF(event.position()),
            global_position=QPointF(event.globalPosition()),
            pressure=float(event.pressure()),
            buttons=event.buttons(),
            modifiers=event.modifiers(),
            timestamp_ms=int(event.timestamp()),
            tilt_x=float(event.xTilt()),
            tilt_y=float(event.yTilt()),
            rotation=float(event.rotation()),
            tangential_pressure=float(event.tangentialPressure()),
            device_id=_tablet_device_id(event),
        )

    def _touch_navigation_allowed(self) -> bool:
        """Return whether the current CuteCanvas state permits one-finger navigation."""
        port = self._port
        if not port.has_renderable_content():
            return False
        if port.viewport().is_locked():
            return False
        return bool(port.touch_navigation_enabled())

    def _begin_touch_sequence(self, event: QTouchEvent) -> None:
        """Capture a supported sequence and seed its arbitration state."""
        port = self._port
        if not port.has_renderable_content():
            self._set_touch_sequence_claimed(False)
            return
        first_point = next(iter(event.points()), None)
        if first_point is None:
            self._set_touch_sequence_claimed(False)
            return
        divider = port
        if divider.claim_external_touch(first_point.position()):
            self._set_touch_sequence_claimed(True)
            self._touch_divider_claimed = True
            self._set_active_device(PointerDeviceKind.TOUCH)
            self._primary_touch_id = first_point.id()
            self._primary_touch_origin = QPointF(first_point.position())
            self._primary_touch_begin = replace(
                self.touch_sample(first_point, event),
                phase=PointerPhase.BEGIN,
            )
            self._touch_max_contacts = len(event.points())
            return
        profile = self._active_input_profile()
        navigation_mode = profile.navigation
        direct_tool_mode = profile.touch
        if not navigation_mode and not direct_tool_mode:
            self._set_touch_sequence_claimed(False)
            return
        if navigation_mode and not self._touch_navigation_allowed():
            self._set_touch_sequence_claimed(False)
            return
        self._set_touch_sequence_claimed(True)
        self._primary_touch_id = first_point.id()
        self._primary_touch_origin = QPointF(first_point.position())
        self._last_touch_position = QPointF(first_point.position())
        self._last_touch_ended_at = None
        self._primary_touch_begin = replace(
            self.touch_sample(first_point, event),
            phase=PointerPhase.BEGIN,
        )
        self._touch_max_contacts = len(event.points())
        direct_tool_allowed = direct_tool_mode and not self.pen_suppresses_touch_tool()
        if profile.touch_requires_host_enablement:
            direct_tool_allowed = direct_tool_allowed and bool(
                port.touch_tool_enabled()
            )
        self._touch_arena.begin(
            navigation_mode=navigation_mode,
            direct_tool_allowed=direct_tool_allowed,
        )
        self._touch_preview_allowed = profile.touch_preview and direct_tool_allowed
        if navigation_mode or direct_tool_allowed:
            self._set_active_device(PointerDeviceKind.TOUCH)
        if direct_tool_allowed and self._primary_touch_begin is not None:
            handler = self._active_pointer_handler()
            self._touch_tool_active = bool(
                handler(self._primary_touch_begin) if handler is not None else False
            )

    def _primary_touch_distance(self, sample: PointerSample | None) -> float:
        """Return primary movement from its initial contact in logical pixels."""
        if sample is None or self._primary_touch_origin is None:
            return 0.0
        delta = sample.position - self._primary_touch_origin
        return math.hypot(delta.x(), delta.y())

    def _route_touch_tool(
        self,
        sample: PointerSample,
        previous_kind: TouchGestureKind,
    ) -> None:
        """Forward the winning primary touch to the active direct tool."""
        handler = self._active_pointer_handler()
        if handler is None or self._primary_touch_begin is None:
            return
        if previous_kind is TouchGestureKind.PENDING and not self._touch_tool_active:
            handler(self._primary_touch_begin)
            if sample.phase is PointerPhase.BEGIN:
                return
        handler(sample)

    def _cancel_touch_tool(self) -> None:
        """Notify the active direct tool when its touch sequence is cancelled."""
        if (
            not self._touch_tool_active
            and self._touch_arena.kind is not TouchGestureKind.DIRECT_TOOL
        ):
            return
        handler = self._active_pointer_handler()
        if handler is None or self._primary_touch_begin is None:
            return
        handler(replace(self._primary_touch_begin, phase=PointerPhase.CANCEL))
        self._touch_tool_active = False

    def _active_pointer_handler(self):
        """Return the active built-in tool's normalized pointer entry point."""
        tool = self._port.active_tool()
        handler = getattr(tool, "handle_pointer_sample", None)
        return handler if callable(handler) else None

    def _active_input_profile(self):
        """Return capability metadata declared by the active tool."""
        tool = self._port.active_tool()
        return getattr(tool, "input_profile", ToolInputProfile())

    def _preview_pointer_sample(self, sample: PointerSample) -> bool:
        """Ask the active built-in tool to show feedback without editing."""
        tool = self._port.active_tool()
        handler = getattr(tool, "preview_pointer_sample", None)
        return bool(handler(sample)) if callable(handler) else False

    def _clear_pointer_preview(self) -> bool:
        """Ask the active built-in tool to clear direct-input feedback."""
        tool = self._port.active_tool()
        handler = getattr(tool, "clear_pointer_preview", None)
        return bool(handler()) if callable(handler) else False

    def _adopt_mouse_modality(self) -> None:
        """Clear direct feedback and publish mouse cursor ownership."""
        self._clear_pointer_preview()
        self._set_active_device(PointerDeviceKind.MOUSE)

    def _remember_touch_end(self, position: QPointF | None = None) -> None:
        """Record the final contact position used to reject promoted mouse events."""
        if position is not None:
            self._last_touch_position = QPointF(position)
        elif self._primary_touch_id is not None:
            remembered = self._active_touches.get(self._primary_touch_id)
            if remembered is not None:
                self._last_touch_position = QPointF(remembered)
        self._last_touch_ended_at = time.monotonic()

    def _synthesized_mouse_is_distinct(self, event: QMouseEvent) -> bool:
        """Return whether a synthesized event represents new mouse activity."""
        if (
            event.type() == QEvent.Type.MouseMove
            and event.buttons() == Qt.MouseButton.NoButton
        ):
            return True
        device = event.pointingDevice()
        if device is not None:
            if device.type() in {
                QInputDevice.DeviceType.Mouse,
                QInputDevice.DeviceType.TouchPad,
            }:
                return True
            if device.type() in {
                QInputDevice.DeviceType.TouchScreen,
                QInputDevice.DeviceType.Stylus,
            }:
                return False
        ended_at = self._last_touch_ended_at
        touch_position = self._last_touch_position
        if ended_at is None or touch_position is None:
            return False
        if time.monotonic() - ended_at > _SYNTHETIC_MOUSE_DEDUP_SECONDS:
            return True
        delta = event.position() - touch_position
        return math.hypot(delta.x(), delta.y()) > _SYNTHETIC_MOUSE_DEDUP_DISTANCE

    def _synthesized_mouse_is_hover(self, event: QMouseEvent) -> bool:
        """Return whether a synthesized event is mouse or touchpad hover motion."""
        return (
            event.type() == QEvent.Type.MouseMove
            and event.buttons() == Qt.MouseButton.NoButton
            and self._pointing_event_uses_hover_device(event)
        )

    @staticmethod
    def _pointing_event_uses_hover_device(
        event: QMouseEvent | QEnterEvent,
    ) -> bool:
        """Return whether Qt identifies the source as a mouse-like device."""
        device = event.pointingDevice()
        if device is None:
            return False
        return device.type() in {
            QInputDevice.DeviceType.Mouse,
            QInputDevice.DeviceType.TouchPad,
        }

    def _set_active_device(self, device: PointerDeviceKind) -> None:
        """Publish one stable modality transition to pointer-state observers."""
        if device is self._active_device:
            return
        self._active_device = device
        self._notify_pointer_state_changed()

    def _set_touch_sequence_claimed(self, claimed: bool) -> None:
        """Publish touch-contact cursor policy independently of last-device state."""
        if claimed is self._touch_sequence_claimed:
            return
        self._touch_sequence_claimed = claimed
        self._notify_pointer_state_changed()

    def _notify_pointer_state_changed(self) -> None:
        """Ask the interaction owner to reconcile cursor policy with input state."""
        if self._port.pointer_state_changed is not None:
            self._port.pointer_state_changed()

    def _handle_pen_proximity_leave(self) -> None:
        """Cancel incomplete pen work and remove feedback when the pen leaves range."""
        self._pen_in_proximity = False
        self._pen_contact_active = False
        if self._active_device not in {
            PointerDeviceKind.PEN,
            PointerDeviceKind.ERASER,
        }:
            return
        tool = self._port.active_tool()
        cancel_pointer_stroke = getattr(tool, "cancel_pointer_stroke", None)
        if callable(cancel_pointer_stroke):
            cancel_pointer_stroke()
        self._clear_pointer_preview()
        self._set_active_device(PointerDeviceKind.UNKNOWN)

    def _maybe_handle_navigation_tap(self, sample: PointerSample) -> None:
        """Recognize a platform-timed double tap and invoke pan/zoom toggling."""
        if self._touch_max_contacts != 1:
            return
        if self._primary_touch_distance(sample) > 6.0:
            return
        now = time.monotonic()
        interval_s = QApplication.doubleClickInterval() / 1000.0
        previous_at = self._last_navigation_tap_at
        previous_position = self._last_navigation_tap_position
        self._last_navigation_tap_at = now
        self._last_navigation_tap_position = QPointF(sample.position)
        if previous_at is None or previous_position is None:
            return
        if now - previous_at > interval_s:
            return
        delta = sample.position - previous_position
        if math.hypot(delta.x(), delta.y()) > 24.0:
            return
        tool = self._port.active_tool()
        handler = getattr(tool, "handle_double_tap", None)
        if callable(handler) and handler(sample.position):
            self._last_navigation_tap_at = None
            self._last_navigation_tap_position = None


def _touch_phase(state: QEventPoint.State) -> PointerPhase:
    """Map a Qt touch-point state to the normalized lifecycle."""
    if state == QEventPoint.State.Pressed:
        return PointerPhase.BEGIN
    if state == QEventPoint.State.Released:
        return PointerPhase.END
    return PointerPhase.UPDATE


def _tablet_phase(event: QTabletEvent) -> PointerPhase:
    """Map a Qt tablet event type and contact state to the normalized lifecycle."""
    if event.type() == QEvent.Type.TabletPress:
        return PointerPhase.BEGIN
    if event.type() == QEvent.Type.TabletRelease:
        return PointerPhase.END
    if event.pressure() <= 0 and event.buttons() == Qt.MouseButton.NoButton:
        return PointerPhase.HOVER
    return PointerPhase.UPDATE


def _tablet_device_kind(
    pointer_type: QPointingDevice.PointerType,
    device_type: QInputDevice.DeviceType,
) -> PointerDeviceKind:
    """Map Qt pointer identity to the normalized device category."""
    if pointer_type == QPointingDevice.PointerType.Pen:
        return PointerDeviceKind.PEN
    if pointer_type == QPointingDevice.PointerType.Eraser:
        return PointerDeviceKind.ERASER
    if device_type == QInputDevice.DeviceType.Stylus:
        return PointerDeviceKind.PEN
    return PointerDeviceKind.UNKNOWN


def _tablet_device_id(event: QTabletEvent) -> str:
    """Return a stable detached tablet identifier when Qt supplies one."""
    device = event.pointingDevice()
    if device is None:
        return ""
    unique_id = device.uniqueId()
    return str(unique_id.numericId())
