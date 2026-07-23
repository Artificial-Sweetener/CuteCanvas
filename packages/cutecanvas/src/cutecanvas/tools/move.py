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

"""Selection-aware direct-manipulation tool for editor content."""

from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QCursor, QKeyEvent, QMouseEvent
from qpane import PointerPhase, PointerSample, ToolInputProfile

from .base import BaseTool
from .ports import MoveInteractionPort


class MoveTool(BaseTool):
    """Move selected pixels first, or a policy-enabled layer without a selection."""

    input_profile = ToolInputProfile(touch=True, tablet=True)

    def __init__(self) -> None:
        """Initialize inert movement callbacks and sequence state."""
        super().__init__()
        self._reset_state()

    def activate(self, dependencies: MoveInteractionPort) -> None:
        """Capture movement operations supplied by the CuteCanvas facade."""
        self._begin_move = dependencies.begin_move
        self._update_move = dependencies.update_move
        self._finish_move = dependencies.finish_move
        self._suspend_move = dependencies.suspend_move
        self._cancel_move = dependencies.cancel_move
        self._anchor_move = dependencies.anchor_move
        self._update_hover = dependencies.update_move_hover
        self._clear_hover = dependencies.clear_move_hover
        self._target_available = dependencies.move_target_available
        self._nudge_move = dependencies.nudge_move

    def deactivate(self) -> None:
        """Release pointer ownership without resolving editor-owned state."""
        self._suspend_active_move()
        self._clear_hover()
        self._reset_state()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Begin a left-button movement sequence on a selectable layer."""
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        point = QPointF(event.position())
        self._active = bool(
            self._begin_move(
                point,
                bool(event.modifiers() & Qt.KeyboardModifier.AltModifier),
            )
        )
        if self._active:
            self._origin = point
            self.signals.cursor_update_requested.emit()
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Update transient placement while a mouse drag is active."""
        if not self._active:
            if self._update_hover(QPointF(event.position())):
                self.signals.repaint_overlay_requested.emit()
                self.signals.cursor_update_requested.emit()
            event.ignore()
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            event.ignore()
            return
        self._update_and_repaint(
            self._constrained_point(QPointF(event.position()), event.modifiers()),
            _snap_suppressed(event.modifiers()),
        )
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Commit a left-button movement sequence."""
        if event.button() != Qt.MouseButton.LeftButton or not self._active:
            event.ignore()
            return
        self._active = False
        self._finish_move(
            self._constrained_point(QPointF(event.position()), event.modifiers()),
            _snap_suppressed(event.modifiers()),
        )
        self._origin = QPointF()
        self.signals.repaint_overlay_requested.emit()
        self.signals.cursor_update_requested.emit()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Cancel previews or nudge editor content with standard movement keys."""
        if event.key() == Qt.Key.Key_Escape:
            if self._cancel_active_move():
                event.accept()
            else:
                event.ignore()
            return
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            if self._active or not self._anchor_move():
                event.ignore()
                return
            self.signals.repaint_overlay_requested.emit()
            self.signals.cursor_update_requested.emit()
            event.accept()
            return
        direction = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }.get(event.key())
        if direction is None or self._active:
            event.ignore()
            return
        distance = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        if not self._nudge_move(direction[0] * distance, direction[1] * distance):
            event.ignore()
            return
        self.signals.repaint_overlay_requested.emit()
        event.accept()

    def leaveEvent(self, event: QEvent) -> None:
        """Clear hover feedback when the pointer leaves the widget."""
        if self._clear_hover():
            self.signals.repaint_overlay_requested.emit()
        event.ignore()

    def handle_pointer_sample(self, sample: PointerSample) -> bool:
        """Handle normalized touch and tablet movement sequences."""
        if sample.phase is PointerPhase.BEGIN:
            self._active = bool(
                self._begin_move(
                    QPointF(sample.position),
                    bool(sample.modifiers & Qt.KeyboardModifier.AltModifier),
                )
            )
            if self._active:
                self._origin = QPointF(sample.position)
                self.signals.cursor_update_requested.emit()
            return self._active
        if sample.phase is PointerPhase.UPDATE:
            if not self._active:
                return False
            self._update_and_repaint(
                self._constrained_point(sample.position, sample.modifiers),
                _snap_suppressed(sample.modifiers),
            )
            return True
        if sample.phase is PointerPhase.END:
            if not self._active:
                return False
            self._active = False
            self._finish_move(
                self._constrained_point(sample.position, sample.modifiers),
                _snap_suppressed(sample.modifiers),
            )
            self._origin = QPointF()
            self.signals.repaint_overlay_requested.emit()
            self.signals.cursor_update_requested.emit()
            return True
        if sample.phase is PointerPhase.CANCEL:
            return self._suspend_active_move()
        return False

    def getCursor(self) -> QCursor | None:
        """Return the four-direction layer-movement cursor."""
        shape = (
            Qt.CursorShape.SizeAllCursor
            if self._active or self._target_available()
            else Qt.CursorShape.ArrowCursor
        )
        return QCursor(shape)

    def _constrained_point(
        self,
        point: QPointF,
        modifiers: Qt.KeyboardModifier,
    ) -> QPointF:
        """Constrain Shift drags to the nearest 45-degree direction."""
        if not modifiers & Qt.KeyboardModifier.ShiftModifier:
            return QPointF(point)
        delta = point - self._origin
        length = math.hypot(delta.x(), delta.y())
        if length == 0.0:
            return QPointF(point)
        angle = round(math.atan2(delta.y(), delta.x()) / (math.pi / 4.0)) * (
            math.pi / 4.0
        )
        return self._origin + QPointF(
            math.cos(angle) * length, math.sin(angle) * length
        )

    def _update_and_repaint(self, point: QPointF, suppress_snap: bool) -> None:
        """Update preview geometry and request repaint when it changed."""
        if self._update_move(QPointF(point), suppress_snap):
            self.signals.repaint_overlay_requested.emit()

    def _cancel_active_move(self) -> bool:
        """Cancel current movement and refresh interaction feedback."""
        was_active = self._active
        self._active = False
        self._origin = QPointF()
        changed = self._cancel_move()
        if changed or was_active:
            self.signals.repaint_overlay_requested.emit()
            self.signals.cursor_update_requested.emit()
        return changed or was_active

    def _suspend_active_move(self) -> bool:
        """Release the current pointer sequence while preserving floating edits."""
        was_active = self._active
        self._active = False
        self._origin = QPointF()
        changed = self._suspend_move()
        if changed or was_active:
            self.signals.repaint_overlay_requested.emit()
            self.signals.cursor_update_requested.emit()
        return changed or was_active

    def _reset_state(self) -> None:
        """Restore inert dependencies and clear sequence ownership."""
        self._active = False
        self._origin = QPointF()
        self._begin_move: Callable[[QPointF, bool], bool] = lambda _point, _copy: False
        self._update_move: Callable[[QPointF, bool], bool] = (
            lambda _point, _suppress: False
        )
        self._finish_move: Callable[[QPointF, bool], bool] = (
            lambda _point, _suppress: False
        )
        self._suspend_move: Callable[[], bool] = lambda: False
        self._cancel_move: Callable[[], bool] = lambda: False
        self._anchor_move: Callable[[], bool] = lambda: False
        self._update_hover: Callable[[QPointF], bool] = lambda _point: False
        self._clear_hover: Callable[[], bool] = lambda: False
        self._target_available: Callable[[], bool] = lambda: False
        self._nudge_move: Callable[[int, int], bool] = lambda _x, _y: False


def _snap_suppressed(modifiers: Qt.KeyboardModifier) -> bool:
    """Return whether the standard temporary snap override is held."""
    return bool(modifiers & Qt.KeyboardModifier.ControlModifier)
