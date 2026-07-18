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

"""Generic direct-manipulation tool for movable scene layers."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QCursor, QKeyEvent, QMouseEvent

from .base import BaseTool
from .dependencies import ToolDependencies
from .input.model import PointerPhase, PointerSample
from .input.profile import ToolInputProfile


class MoveTool(BaseTool):
    """Translate policy-enabled layers through the generic movement boundary."""

    input_profile = ToolInputProfile(touch=True, tablet=True)

    def __init__(self) -> None:
        """Initialize inert movement callbacks and sequence state."""
        super().__init__()
        self._reset_state()

    def activate(self, dependencies: ToolDependencies) -> None:
        """Capture movement operations supplied by the QPane facade."""
        self._begin_move = dependencies.get("begin_layer_move", lambda _point: False)
        self._update_move = dependencies.get("update_layer_move", lambda _point: False)
        self._finish_move = dependencies.get("finish_layer_move", lambda _point: False)
        self._cancel_move = dependencies.get("cancel_layer_move", lambda: False)

    def deactivate(self) -> None:
        """Cancel transient movement before releasing dependencies."""
        self._cancel_active_move()
        self._reset_state()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Begin a left-button movement sequence on a selectable layer."""
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        self._active = bool(self._begin_move(QPointF(event.position())))
        if self._active:
            self.signals.cursor_update_requested.emit()
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Update transient placement while a mouse drag is active."""
        if not self._active or not (event.buttons() & Qt.MouseButton.LeftButton):
            event.ignore()
            return
        self._update_and_repaint(QPointF(event.position()))
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Commit a left-button movement sequence."""
        if event.button() != Qt.MouseButton.LeftButton or not self._active:
            event.ignore()
            return
        self._active = False
        self._finish_move(QPointF(event.position()))
        self.signals.repaint_overlay_requested.emit()
        self.signals.cursor_update_requested.emit()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Cancel the current preview when Escape is pressed."""
        if event.key() != Qt.Key.Key_Escape or not self._active:
            event.ignore()
            return
        self._cancel_active_move()
        event.accept()

    def handle_pointer_sample(self, sample: PointerSample) -> bool:
        """Handle normalized touch and tablet movement sequences."""
        if sample.phase is PointerPhase.BEGIN:
            self._active = bool(self._begin_move(QPointF(sample.position)))
            if self._active:
                self.signals.cursor_update_requested.emit()
            return self._active
        if sample.phase is PointerPhase.UPDATE:
            if not self._active:
                return False
            self._update_and_repaint(sample.position)
            return True
        if sample.phase is PointerPhase.END:
            if not self._active:
                return False
            self._active = False
            self._finish_move(QPointF(sample.position))
            self.signals.repaint_overlay_requested.emit()
            self.signals.cursor_update_requested.emit()
            return True
        if sample.phase is PointerPhase.CANCEL:
            return self._cancel_active_move()
        return False

    def getCursor(self) -> QCursor | None:
        """Return the four-direction layer-movement cursor."""
        return QCursor(Qt.CursorShape.SizeAllCursor)

    def _update_and_repaint(self, point: QPointF) -> None:
        """Update preview geometry and request repaint when it changed."""
        if self._update_move(QPointF(point)):
            self.signals.repaint_overlay_requested.emit()

    def _cancel_active_move(self) -> bool:
        """Cancel current movement and refresh interaction feedback."""
        was_active = self._active
        self._active = False
        changed = self._cancel_move()
        if changed or was_active:
            self.signals.repaint_overlay_requested.emit()
            self.signals.cursor_update_requested.emit()
        return changed or was_active

    def _reset_state(self) -> None:
        """Restore inert dependencies and clear sequence ownership."""
        self._active = False
        self._begin_move: Callable[[QPointF], bool] = lambda _point: False
        self._update_move: Callable[[QPointF], bool] = lambda _point: False
        self._finish_move: Callable[[QPointF], bool] = lambda _point: False
        self._cancel_move: Callable[[], bool] = lambda: False
