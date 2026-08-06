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
"""Route editor keyboard events through focused state and command owners."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QApplication, QWidget

from .selection_shortcuts import EditorSelectionShortcuts
from .shortcuts import EditorHistoryShortcuts
from .transient_input import TransientToolInput

if TYPE_CHECKING:  # pragma: no cover - typing-only dependency
    from ..canvas import CuteCanvas

logger = logging.getLogger(__name__)


class EditorKeyboardInputController:
    """Own Qt key classification, focus lifetime, and tool forwarding."""

    def __init__(
        self,
        canvas: CuteCanvas,
        *,
        transient: TransientToolInput,
        history: EditorHistoryShortcuts,
        selection: EditorSelectionShortcuts,
        forward_widget_press: Callable[[QKeyEvent], None],
    ) -> None:
        """Bind one canvas and its keyboard-domain collaborators."""
        self._canvas = canvas
        self._transient = transient
        self._history = history
        self._selection = selection
        self._forward_widget_press = forward_widget_press
        self._shutdown = False
        QApplication.instance().focusChanged.connect(self._handle_focus_changed)

    def handle_press(self, event: QKeyEvent) -> bool:
        """Route one key press and report whether the canvas consumed it."""
        canvas = self._canvas
        if canvas._is_blank:
            return True
        if event.matches(QKeySequence.StandardKey.Copy):
            focused_widget = QApplication.focusWidget()
            if focused_widget is not None and canvas.isAncestorOf(focused_widget):
                event.ignore()
                canvas._tools_manager.keyPressEvent(event)
            else:
                self._forward_widget_press(event)
            return event.isAccepted()
        if self._history.handle(event):
            return True
        if self._selection.handle(event):
            return True
        if event.key() == Qt.Key.Key_Shift:
            self._transient.press_shift(auto_repeat=event.isAutoRepeat())
        elif event.key() == Qt.Key.Key_Alt:
            self._transient.press_alt(auto_repeat=event.isAutoRepeat())
        elif event.key() == Qt.Key.Key_Space:
            if not self._transient.press_space(auto_repeat=event.isAutoRepeat()):
                event.ignore()
                canvas._tools_manager.keyPressEvent(event)
                return event.isAccepted()
        else:
            event.ignore()
            canvas._tools_manager.keyPressEvent(event)
            return event.isAccepted()
        event.accept()
        return True

    def handle_release(self, event: QKeyEvent) -> bool:
        """Route one key release and report whether the canvas consumed it."""
        if event.key() == Qt.Key.Key_Space:
            self._transient.release_space(auto_repeat=event.isAutoRepeat())
        elif event.key() == Qt.Key.Key_Alt:
            self._transient.release_alt(auto_repeat=event.isAutoRepeat())
        elif event.key() == Qt.Key.Key_Shift:
            self._transient.release_shift(auto_repeat=event.isAutoRepeat())
        else:
            event.ignore()
            self._canvas._tools_manager.keyReleaseEvent(event)
            return event.isAccepted()
        event.accept()
        return True

    def reset(self) -> None:
        """Clear transient state after visibility or focus loss."""
        self._transient.reset()

    def shutdown(self) -> None:
        """Detach application focus observation before the canvas is destroyed."""
        if self._shutdown:
            return
        self._shutdown = True
        app = QApplication.instance()
        if app is None:
            return
        try:
            app.focusChanged.disconnect(self._handle_focus_changed)
        except RuntimeError as error:
            logger.debug("Focus observer was already detached: %s", error)

    def _handle_focus_changed(
        self,
        old: QWidget | None,
        new: QWidget | None,
    ) -> None:
        """Clear modifiers when focus leaves this canvas subtree."""
        if self._shutdown or old is None:
            return
        canvas = self._canvas
        owned_old = old is canvas or canvas.isAncestorOf(old)
        owned_new = new is canvas or (new is not None and canvas.isAncestorOf(new))
        if owned_old and not owned_new:
            self._transient.reset()
