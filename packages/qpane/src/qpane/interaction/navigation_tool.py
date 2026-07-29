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
"""QPane's opinionated built-in pan and zoom interaction."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QCursor, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from ..rendering.viewport import ViewportZoomMode
from .ports import NavigationInteractionPort
from .profile import ToolInputProfile
from .tool import ViewerTool


class PanZoomTool(ViewerTool):
    """Pan by dragging and zoom around the pointer with historical snap behavior."""

    _WHEEL_UNITS_PER_STEP = 120.0
    _WHEEL_ZOOM_IN_FACTOR = 1.25
    _WHEEL_ZOOM_OUT_FACTOR = 0.8
    input_profile = ToolInputProfile(navigation=True)

    def __init__(self) -> None:
        """Prepare empty navigation state."""
        super().__init__()
        self._reset_state()

    def activate(self, dependencies: object) -> None:
        """Capture the navigation port supplied by the viewer host."""
        if not isinstance(dependencies, NavigationInteractionPort):
            raise TypeError("PanZoomTool requires NavigationInteractionPort")
        self._port = dependencies

    def deactivate(self) -> None:
        """Release captured collaborators and transient pointer state."""
        self._reset_state()

    def getCursor(self) -> QCursor:
        """Return an open or closed hand only when panning is available."""
        if self._panning:
            return QCursor(Qt.CursorShape.ClosedHandCursor)
        if (
            not self._port.is_content_empty()
            and self._port.can_pan()
            and not self._port.is_drag_out_allowed()
        ):
            return QCursor(Qt.CursorShape.OpenHandCursor)
        return QCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Begin panning or retain the origin for a possible drag-out."""
        if self._port.is_navigation_locked():
            return
        if event.button() is not Qt.MouseButton.LeftButton:
            return
        if self._port.is_content_empty():
            return
        position = event.position().toPoint()
        self._drag_start_position = position
        self._last_position = position
        if not self._port.is_drag_out_allowed() and self._port.can_pan():
            self._panning = True
            self.signals.navigation_started.emit()
            self.signals.cursor_update_requested.emit()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Promote drag-out or emit a physical-pixel pan request."""
        if self._port.is_navigation_locked():
            return
        if self._drag_out_threshold_crossed(event):
            self.signals.drag_out_requested.emit(event)
            return
        if (
            event.buttons() & Qt.MouseButton.LeftButton
            and self._last_position is not None
            and not self._port.is_drag_out_allowed()
            and self._port.can_pan()
        ):
            logical_delta = event.position() - self._last_position
            dpr = self._safe_dpr()
            pan = self._port.get_pan() + QPointF(
                logical_delta.x() * dpr,
                logical_delta.y() * dpr,
            )
            self.signals.pan_requested.emit(pan)
        self._last_position = event.position().toPoint()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """End panning and clear the drag origin."""
        if self._port.is_navigation_locked():
            return
        if event.button() is Qt.MouseButton.LeftButton:
            was_panning = self._panning
            self._panning = False
            if was_panning:
                self.signals.navigation_finished.emit()
            self.signals.cursor_update_requested.emit()
        self._last_position = None
        self._drag_start_position = None

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Toggle between Fit and 1:1 around the clicked point."""
        if self.handle_double_tap(event.position()):
            event.accept()

    def handle_double_tap(self, position: QPointF) -> bool:
        """Apply the historical Fit/1:1 toggle for normalized direct input."""
        if self._port.is_navigation_locked() or self._port.is_content_empty():
            return False
        get_mode = self._port.get_zoom_mode
        mode = ViewportZoomMode.FIT if get_mode is None else get_mode()
        if mode is not ViewportZoomMode.FIT:
            setter = self._port.set_zoom_fit_interpolated
            (self._port.set_zoom_fit if setter is None else setter)()
            return True
        setter_1_to_1 = self._port.set_zoom_one_to_one_interpolated
        if setter_1_to_1 is None:
            self._port.set_zoom_one_to_one(position)
        else:
            setter_1_to_1(position)
        return True

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Zoom by wheel magnitude and snap when crossing Fit or 1:1."""
        if self._port.is_navigation_locked() or self._port.is_content_empty():
            return
        angle = event.angleDelta().y()
        if angle == 0:
            return
        steps = abs(angle) / self._WHEEL_UNITS_PER_STEP
        step_factor = (
            self._WHEEL_ZOOM_IN_FACTOR if angle > 0 else self._WHEEL_ZOOM_OUT_FACTOR
        )
        old_zoom = self._port.get_zoom()
        anchor = event.position()
        new_zoom, snap_mode = self._snap_zoom(
            old_zoom,
            old_zoom * step_factor**steps,
            anchor,
        )
        if snap_mode is None:
            self.signals.zoom_requested.emit(new_zoom, anchor)
        else:
            self.signals.zoom_snap_requested.emit(new_zoom, anchor, snap_mode)
        if hasattr(event, "accept"):
            event.accept()

    def _reset_state(self) -> None:
        """Restore inert dependencies and pointer state."""
        self._port = NavigationInteractionPort()
        self._panning = False
        self._drag_start_position: QPoint | None = None
        self._last_position: QPoint | None = None

    def _drag_out_threshold_crossed(self, event: QMouseEvent) -> bool:
        """Return whether a drag-enabled host should begin dragging content out."""
        origin = self._drag_start_position
        if origin is None or not self._port.is_drag_out_allowed():
            return False
        if not event.buttons() & Qt.MouseButton.LeftButton:
            return False
        application = QApplication.instance()
        threshold = 10 if application is None else application.startDragDistance()
        if (event.position().toPoint() - origin).manhattanLength() < threshold:
            return False
        self._drag_start_position = None
        return True

    def _safe_dpr(self) -> float:
        """Return a positive device-pixel ratio from the host port."""
        try:
            dpr = float(self._port.get_dpr())
        except (TypeError, ValueError):
            return 1.0
        return dpr if dpr > 0 else 1.0

    def _snap_zoom(
        self,
        old_zoom: float,
        requested_zoom: float,
        anchor: QPointF,
    ) -> tuple[float, ViewportZoomMode | None]:
        """Snap a wheel transition when it crosses Fit or native scale."""
        try:
            native_zoom = float(self._port.get_native_zoom(anchor))
            fit_zoom = float(self._port.get_fit_zoom())
        except (TypeError, ValueError):
            return requested_zoom, None

        def crosses(target: float) -> bool:
            """Return whether the requested transition crosses ``target``."""
            return target > 0 and (
                old_zoom < target <= requested_zoom
                or old_zoom > target >= requested_zoom
            )

        crosses_native = crosses(native_zoom)
        crosses_fit = crosses(fit_zoom)
        if crosses_native:
            return native_zoom, ViewportZoomMode.ONE_TO_ONE
        if crosses_fit:
            return fit_zoom, ViewportZoomMode.FIT
        return requested_zoom, None
