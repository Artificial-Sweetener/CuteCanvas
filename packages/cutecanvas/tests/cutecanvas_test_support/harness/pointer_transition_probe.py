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

"""Record post-delivery pointer state from an offscreen production CuteCanvas."""

from __future__ import annotations

from dataclasses import dataclass

from cutecanvas import CuteCanvas
from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QMouseEvent, QPointerEvent
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True, slots=True)
class PointerEventObservation:
    """Describe one Qt pointer event after CuteCanvas finished handling it."""

    sequence: int
    event_type: str
    receiver_type: str
    source: str | None
    device_type: str | None
    accepted_before: bool
    accepted_after: bool
    active_device: str
    touch_claimed: bool
    cursor_suppressed: bool
    cursor_shape: str
    cursor_size: tuple[int, int]
    cursor_hotspot: tuple[int, int]
    effective_cursor_shape: str | None
    effective_cursor_size: tuple[int, int]
    effective_cursor_hotspot: tuple[int, int]


class PointerTransitionProbe:
    """Deliver Qt events and record CuteCanvas's exact post-handler state."""

    def __init__(self, viewer: CuteCanvas) -> None:
        """Bind the probe to a production viewer and its QApplication."""
        self._viewer = viewer
        application = QApplication.instance()
        if application is None:
            raise RuntimeError("PointerTransitionProbe requires a QApplication")
        self._application = application
        self._sequence = 0
        self._observations: list[PointerEventObservation] = []

    def deliver(
        self,
        event: QEvent,
        *,
        receiver: QObject | None = None,
    ) -> PointerEventObservation:
        """Send one event normally and record acceptance, modality, and cursor."""
        target = self._viewer if receiver is None else receiver
        accepted_before = event.isAccepted()
        self._application.sendEvent(target, event)
        self._sequence += 1
        observation = self._observation(
            sequence=self._sequence,
            receiver=target,
            event=event,
            accepted_before=accepted_before,
        )
        self._observations.append(observation)
        return observation

    def drain(self) -> tuple[PointerEventObservation, ...]:
        """Return observations accumulated since the last drain."""
        observations = tuple(self._observations)
        self._observations.clear()
        return observations

    def close(self) -> None:
        """Discard retained observations before the viewer is disposed."""
        self._observations.clear()

    def _observation(
        self,
        *,
        sequence: int,
        receiver: QObject,
        event: QEvent,
        accepted_before: bool,
    ) -> PointerEventObservation:
        """Snapshot controller and cursor state after one synchronous delivery."""
        cursor = self._viewer.cursor()
        pixmap = cursor.pixmap()
        hotspot = cursor.hotSpot()
        top_level = self._viewer.window()
        window = top_level.windowHandle() if top_level is not None else None
        effective_cursor = window.cursor() if window is not None else None
        effective_pixmap = (
            effective_cursor.pixmap() if effective_cursor is not None else None
        )
        effective_hotspot = (
            effective_cursor.hotSpot() if effective_cursor is not None else None
        )
        pointer_input = self._viewer.interaction._pointer_input
        source = event.source().name if isinstance(event, QMouseEvent) else None
        device_type = None
        if isinstance(event, QPointerEvent):
            device = event.pointingDevice()
            if device is not None:
                device_type = device.type().name
        return PointerEventObservation(
            sequence=sequence,
            event_type=event.type().name,
            receiver_type=type(receiver).__name__,
            source=source,
            device_type=device_type,
            accepted_before=accepted_before,
            accepted_after=event.isAccepted(),
            active_device=pointer_input.active_device.value,
            touch_claimed=pointer_input.touch_sequence_claimed,
            cursor_suppressed=pointer_input.cursor_suppressed,
            cursor_shape=cursor.shape().name,
            cursor_size=(pixmap.width(), pixmap.height()),
            cursor_hotspot=(hotspot.x(), hotspot.y()),
            effective_cursor_shape=(
                effective_cursor.shape().name if effective_cursor is not None else None
            ),
            effective_cursor_size=(
                (effective_pixmap.width(), effective_pixmap.height())
                if effective_pixmap is not None
                else (0, 0)
            ),
            effective_cursor_hotspot=(
                (effective_hotspot.x(), effective_hotspot.y())
                if effective_hotspot is not None
                else (0, 0)
            ),
        )
