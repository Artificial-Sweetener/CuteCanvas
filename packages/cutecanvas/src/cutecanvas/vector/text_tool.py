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
"""Focused canvas tool for creating and editing semantic text in place."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QCursor, QGuiApplication, QKeyEvent, QMouseEvent, QPainter

from ..tools.base import BaseTool
from ..tools.ports import VectorTextInteractionPort
from ..ui.vector_text import VectorTextOverlayRenderer

VECTOR_TEXT_MODE = "vector-text"


class VectorTextTool(BaseTool):
    """Translate canvas clicks and text keys into one domain-owned session."""

    def __init__(self) -> None:
        """Initialize an inert port and detached feedback renderer."""
        super().__init__()
        self._port = VectorTextInteractionPort()
        self._renderer = VectorTextOverlayRenderer()

    def activate(self, dependencies: VectorTextInteractionPort) -> None:
        """Capture the focused text-editing port."""
        self._port = dependencies

    def deactivate(self) -> None:
        """Retain domain-owned text state across temporary tool suspension."""
        self._port = VectorTextInteractionPort()

    def captures_space_key(self) -> bool:
        """Return whether Space belongs to active text rather than temporary pan."""
        return self._port.active()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Edit text under a primary click or start a new semantic text box."""
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        if self._port.begin_at(QPointF(event.position())):
            self.signals.repaint_overlay_requested.emit()
            event.accept()
        else:
            event.ignore()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Apply standard caret, deletion, paste, commit, and cancel behavior."""
        if not self._port.active():
            event.ignore()
            return
        modifiers = event.modifiers()
        control = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        if event.key() == Qt.Key.Key_Escape:
            changed = self._port.cancel()
        elif control and event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            changed = self._port.commit()
        elif control and event.key() == Qt.Key.Key_V:
            changed = self._port.insert(QGuiApplication.clipboard().text())
        elif event.key() == Qt.Key.Key_Backspace:
            changed = self._port.backspace()
        elif event.key() == Qt.Key.Key_Delete:
            changed = self._port.delete()
        elif event.key() == Qt.Key.Key_Left:
            changed = self._port.move_cursor(-1)
        elif event.key() == Qt.Key.Key_Right:
            changed = self._port.move_cursor(1)
        elif event.key() == Qt.Key.Key_Home:
            changed = self._port.move_cursor_to(0)
        elif event.key() == Qt.Key.Key_End:
            changed = self._port.move_cursor_to(self._port.text_length())
        elif event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            changed = self._port.insert("\n")
        elif event.text() and not control:
            changed = self._port.insert(event.text())
        else:
            event.ignore()
            return
        if changed:
            self.signals.repaint_overlay_requested.emit()
        event.accept()

    def draw_overlay(self, painter: QPainter) -> None:
        """Draw detached text-box and insertion-caret feedback."""
        self._renderer.draw(painter, self._port.overlay_state())

    def getCursor(self) -> QCursor | None:
        """Return the conventional text insertion cursor."""
        return QCursor(Qt.CursorShape.IBeamCursor)
