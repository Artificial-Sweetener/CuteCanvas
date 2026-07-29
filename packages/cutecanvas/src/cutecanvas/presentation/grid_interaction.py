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

"""Arbitrate click, drag-out, and context gestures for grid targets."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import cast

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QContextMenuEvent, QMouseEvent
from PySide6.QtWidgets import QApplication


class GridTargetGestureController:
    """Resolve each grid gesture to one target without permitting navigation."""

    def __init__(
        self,
        *,
        targets: Mapping[QObject, uuid.UUID],
        activate: Callable[[uuid.UUID], None],
        request_context: Callable[[QObject, QPoint], None],
    ) -> None:
        """Store the target mapping and presentation-owned callbacks."""

        self._targets = dict(targets)
        self._activate = activate
        self._request_context = request_context
        self._pressed_target: uuid.UUID | None = None
        self._press_position: QPoint | None = None
        self._dragged = False

    def handle_event(self, watched: QObject, event: QEvent) -> bool:
        """Track click candidates and route grid context requests deterministically."""

        target_id = self._targets.get(watched)
        if target_id is None:
            return False
        if event.type() is QEvent.Type.ContextMenu:
            context_event = cast(QContextMenuEvent, event)
            self._request_context(watched, context_event.globalPos())
            context_event.accept()
            return True
        if event.type() is QEvent.Type.MouseButtonPress:
            self._begin_click_candidate(target_id, cast(QMouseEvent, event))
        elif event.type() is QEvent.Type.MouseMove:
            self._update_click_candidate(cast(QMouseEvent, event))
        elif event.type() is QEvent.Type.MouseButtonRelease:
            self._complete_click_candidate(target_id, cast(QMouseEvent, event))
        return False

    def _begin_click_candidate(
        self,
        target_id: uuid.UUID,
        event: QMouseEvent,
    ) -> None:
        """Remember a primary-button press until it resolves as click or drag."""

        if event.button() is not Qt.MouseButton.LeftButton:
            return
        self._pressed_target = target_id
        self._press_position = event.position().toPoint()
        self._dragged = False

    def _update_click_candidate(self, event: QMouseEvent) -> None:
        """Mark the active press as a drag after Qt's platform threshold."""

        origin = self._press_position
        if (
            origin is None
            or self._dragged
            or not event.buttons() & Qt.MouseButton.LeftButton
        ):
            return
        application = QApplication.instance()
        threshold = 10 if application is None else application.startDragDistance()
        if (event.position().toPoint() - origin).manhattanLength() >= threshold:
            self._dragged = True

    def _complete_click_candidate(
        self,
        target_id: uuid.UUID,
        event: QMouseEvent,
    ) -> None:
        """Activate only a released primary click that did not become a drag."""

        pressed_target = self._pressed_target
        dragged = self._dragged
        self._clear_click_candidate()
        if (
            event.button() is Qt.MouseButton.LeftButton
            and pressed_target == target_id
            and not dragged
        ):
            self._activate(target_id)

    def _clear_click_candidate(self) -> None:
        """Release all transient state from the previous pointer gesture."""

        self._pressed_target = None
        self._press_position = None
        self._dragged = False
