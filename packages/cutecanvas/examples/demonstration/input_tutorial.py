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
"""Teach application-level shortcuts without duplicating CuteCanvas input."""

from __future__ import annotations

import logging
from collections.abc import Callable

from cutecanvas import CuteCanvas
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

logger = logging.getLogger(__name__)


class ApplicationInputTutorial(QObject):
    """Own global demo shortcuts that sit outside CuteCanvas tool dispatch."""

    def __init__(
        self,
        canvas: CuteCanvas,
        window: QWidget,
        zoom_editor: QLineEdit,
        *,
        open_images: Callable[[], None],
        enter_zoom_edit: Callable[[], None],
        apply_zoom_edit: Callable[[], None],
        resize_zoom_editor: Callable[[], None],
        resize_zoom_toggle: Callable[[], None],
    ) -> None:
        """Install one application filter using narrow shell callbacks."""
        super().__init__(window)
        self._canvas = canvas
        self._window = window
        self._zoom_editor = zoom_editor
        self._open_images = open_images
        self._enter_zoom_edit = enter_zoom_edit
        self._apply_zoom_edit = apply_zoom_edit
        self._resize_zoom_editor = resize_zoom_editor
        self._resize_zoom_toggle = resize_zoom_toggle
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Route only the application gestures demonstrated by this module."""
        try:
            if self._handle_zoom_editor_events(watched, event):
                return True
            if self._handle_open_image_event(watched, event):
                return True
        except Exception:
            logger.exception(
                "Global event filter failed (type=%s, watched=%s)",
                event.type(),
                type(watched).__name__,
            )
        return False

    def canvas_under_cursor(self, canvas: CuteCanvas) -> bool:
        """Return whether the global pointer currently targets the canvas."""
        cursor_position = QCursor.pos()
        widget = QApplication.widgetAt(cursor_position)
        if widget is not None:
            try:
                if widget is canvas or canvas.isAncestorOf(widget):
                    return True
            except RuntimeError:
                return False
        top_left = canvas.mapToGlobal(QPoint(0, 0))
        return QRect(top_left, canvas.size()).contains(cursor_position)

    def close(self) -> None:
        """Remove the application filter before the window is destroyed."""
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

    def _handle_zoom_editor_events(self, watched: QObject, event: QEvent) -> bool:
        """Enter or leave explicit zoom editing from ordinary focus events."""
        if watched is not self._zoom_editor:
            return False
        if event.type() == QEvent.Type.MouseButtonDblClick:
            self._enter_zoom_edit()
            return True
        if event.type() == QEvent.Type.FocusOut and not self._zoom_editor.isReadOnly():
            self._apply_zoom_edit()
            return False
        if event.type() == QEvent.Type.FontChange:
            self._resize_zoom_editor()
            self._resize_zoom_toggle()
        return False

    def _handle_open_image_event(self, watched: QObject, event: QEvent) -> bool:
        """Open the image picker from the canvas context-click gesture."""
        if event.type() != QEvent.Type.MouseButtonPress:
            return False
        if not isinstance(event, QMouseEvent):
            return False
        if event.button() != Qt.MouseButton.RightButton:
            return False
        if self._is_canvas_target(watched):
            self._open_images()
            event.accept()
            return True
        return False

    def _is_canvas_target(self, watched: QObject) -> bool:
        """Return whether one watched object belongs to the editor canvas."""
        return watched is self._canvas or (
            isinstance(watched, QWidget) and self._canvas.isAncestorOf(watched)
        )
