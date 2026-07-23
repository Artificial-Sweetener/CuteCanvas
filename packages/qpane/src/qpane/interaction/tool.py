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
"""Public viewer-tool contract shared by QPane and editor extensions."""

from __future__ import annotations

import abc

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, Signal
from PySide6.QtGui import (
    QCursor,
    QEnterEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QWheelEvent,
)

from .profile import ToolInputProfile


class ViewerToolSignals(QObject):
    """Signal hub through which a viewer tool requests host work."""

    pan_requested = Signal(QPointF)
    zoom_requested = Signal(float, QPointF)
    zoom_snap_requested = Signal(float, QPointF, object)
    drag_out_requested = Signal(QMouseEvent)
    repaint_overlay_requested = Signal()
    cursor_update_requested = Signal()


class ViewerTool(abc.ABC):
    """Extensible input and overlay behavior hosted by QPane."""

    input_profile = ToolInputProfile()

    def __init__(self) -> None:
        """Create the signal hub available to subclasses."""
        self.signals = ViewerToolSignals()

    def activate(self, dependencies: object) -> None:
        """Receive a focused activation port when the tool becomes active."""

    def deactivate(self) -> None:
        """Release transient state when the tool stops being active."""

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Ignore pointer presses unless a subclass consumes them."""
        event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Ignore pointer movement unless a subclass consumes it."""
        event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Ignore pointer releases unless a subclass consumes them."""
        event.ignore()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Ignore double-clicks unless a subclass consumes them."""
        event.ignore()

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Ignore wheel input unless a subclass consumes it."""
        event.ignore()

    def enterEvent(self, event: QEnterEvent) -> None:
        """Ignore pointer entry unless a subclass consumes it."""
        event.ignore()

    def leaveEvent(self, event: QEvent) -> None:
        """Ignore pointer exit unless a subclass consumes it."""
        event.ignore()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Ignore key presses unless a subclass consumes them."""
        event.ignore()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        """Ignore key releases unless a subclass consumes them."""
        event.ignore()

    def draw_overlay(self, painter: QPainter) -> None:
        """Draw tool feedback after scene content."""

    def getCursor(self) -> QCursor | None:
        """Return the desired cursor or ``None`` to defer to another provider."""
        return QCursor(Qt.CursorShape.ArrowCursor)
