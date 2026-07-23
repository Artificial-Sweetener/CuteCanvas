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
"""Inert QPane cursor tool with optional host drag-out promotion."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from .ports import CursorInteractionPort
from .tool import ViewerTool


class CursorTool(ViewerTool):
    """Leave canvas interaction inert while permitting configured drag-out."""

    def __init__(self) -> None:
        """Prepare empty drag tracking."""
        super().__init__()
        self._reset_state()

    def activate(self, dependencies: object) -> None:
        """Capture the focused cursor port supplied by the viewer host."""
        if not isinstance(dependencies, CursorInteractionPort):
            raise TypeError("CursorTool requires CursorInteractionPort")
        self._port = dependencies

    def deactivate(self) -> None:
        """Release captured collaborators and pointer state."""
        self._reset_state()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Remember a content press for possible drag-out promotion."""
        if (
            event.button() is Qt.MouseButton.LeftButton
            and not self._port.is_content_empty()
        ):
            self._drag_start_position = event.position().toPoint()
        event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Promote a sufficiently large configured content drag."""
        origin = self._drag_start_position
        if (
            origin is not None
            and self._port.is_drag_out_allowed()
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            application = QApplication.instance()
            threshold = 10 if application is None else application.startDragDistance()
            if (event.position().toPoint() - origin).manhattanLength() >= threshold:
                self._drag_start_position = None
                self.signals.drag_out_requested.emit(event)
        event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Clear drag tracking after a primary-button release."""
        if event.button() is Qt.MouseButton.LeftButton:
            self._drag_start_position = None
        event.ignore()

    def _reset_state(self) -> None:
        """Restore inert dependencies and pointer state."""
        self._port = CursorInteractionPort()
        self._drag_start_position: QPoint | None = None
