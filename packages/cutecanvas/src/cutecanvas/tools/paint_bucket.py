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
"""One-click asynchronous Paint Bucket interaction."""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QCursor, QKeyEvent, QMouseEvent

from cutecanvas.coverage import CoverageCombineMode

from .base import BaseTool
from .coverage_operation import resolve_coverage_operation
from .cursor_feedback import ToolCursorStyle
from .modifier_snapshot import alt_is_active, shift_is_active
from .ports import PaintBucketInteractionPort


class PaintBucketTool(BaseTool):
    """Submit one stale-safe target fill per primary-button click."""

    cursor_style: ClassVar[ToolCursorStyle] = ToolCursorStyle.PRECISE
    supports_alt_erase_indicator: ClassVar[bool] = True

    def __init__(self) -> None:
        """Initialize inert dependencies for safe activation changes."""
        super().__init__()
        self._reset_dependencies()

    def activate(self, dependencies: PaintBucketInteractionPort) -> None:
        """Capture the active target and asynchronous fill boundary."""
        self._panel_to_target = dependencies.panel_to_target_point
        self._can_fill = dependencies.can_fill
        self._request_fill = dependencies.request_fill
        self._cancel_fill = dependencies.cancel_fill
        self._is_shift_held = dependencies.is_shift_held
        self._is_alt_held = dependencies.is_alt_held

    def deactivate(self) -> None:
        """Cancel unresolved work so a tool switch cannot publish stale output."""
        self._cancel_fill()
        self._reset_dependencies()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Submit a fill at one mapped target-local primary-button position."""
        if event.button() != Qt.MouseButton.LeftButton or not self._can_fill():
            event.ignore()
            return
        point = self._panel_to_target(QPointF(event.position()))
        if point is None or not self._request_fill(
            point,
            self._combine_mode(event.modifiers()),
        ):
            event.ignore()
            return
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Cancel unresolved evaluation with Escape."""
        if event.key() != Qt.Key.Key_Escape or not self._cancel_fill():
            event.ignore()
            return
        event.accept()

    def getCursor(self) -> QCursor | None:
        """Defer precise feedback while retaining unavailable-state ownership."""
        if self._can_fill():
            return None
        return QCursor(Qt.CursorShape.ForbiddenCursor)

    def _combine_mode(
        self,
        modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
    ) -> CoverageCombineMode:
        """Map familiar coverage modifiers to the shared algebra."""
        return resolve_coverage_operation(
            default=CoverageCombineMode.ADD,
            alt_held=alt_is_active(self._is_alt_held(), modifiers),
            shift_held=shift_is_active(self._is_shift_held(), modifiers),
        )

    def _reset_dependencies(self) -> None:
        """Install inert collaborators after construction or deactivation."""
        self._panel_to_target: Callable[[QPointF], QPointF | None] = lambda _point: None
        self._can_fill: Callable[[], bool] = lambda: False
        self._request_fill: Callable[[QPointF, CoverageCombineMode], bool] = (
            lambda _point, _mode: False
        )
        self._cancel_fill: Callable[[], bool] = lambda: False
        self._is_shift_held: Callable[[], bool] = lambda: False
        self._is_alt_held: Callable[[], bool] = lambda: False
