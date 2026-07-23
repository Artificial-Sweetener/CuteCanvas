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
"""Editor cursor arbitration and brush-feedback ownership."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor

from ..core import CursorProvider
from ..editor import EditorOperation
from .tools import Tools

if TYPE_CHECKING:
    from ..canvas import CuteCanvas

logger = logging.getLogger(__name__)


class EditorCursorController:
    """Choose one effective cursor from input, divider, tool, and paint policy."""

    def __init__(
        self,
        canvas: CuteCanvas,
        cursor_suppressed: Callable[[], bool],
    ) -> None:
        """Capture the editor host and direct-input suppression boundary."""
        self._canvas = canvas
        self._cursor_suppressed = cursor_suppressed
        self._providers: dict[str, CursorProvider] = {}
        self.custom_cursor: QCursor | None = None
        self.brush_size = max(1, int(canvas.settings.default_brush_size))
        self.alt_held = False

    def register_provider(self, mode: str, provider: CursorProvider) -> None:
        """Register one mode-specific cursor provider and refresh if active."""
        self._providers[mode] = provider
        if self._canvas._tools_manager.get_control_mode() == mode:
            self.update()

    def unregister_provider(self, mode: str) -> None:
        """Remove one mode-specific provider and refresh if active."""
        self._providers.pop(mode, None)
        if self._canvas._tools_manager.get_control_mode() == mode:
            self.update()

    def update(self) -> None:
        """Apply the highest-priority cursor for the current editor state."""
        canvas = self._canvas
        if canvas._is_blank:
            canvas.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            return
        if self._cursor_suppressed():
            canvas.setCursor(QCursor(Qt.CursorShape.BlankCursor))
            return
        divider_cursor = canvas.comparisonDividerInteraction().cursor()
        if divider_cursor is not None:
            canvas.setCursor(divider_cursor)
            return
        active_tool = canvas._tools_manager.get_active_tool()
        if active_tool and hasattr(active_tool, "getCursor"):
            try:
                cursor = active_tool.getCursor()
            except Exception:
                logger.exception("Active tool failed to provide cursor")
            else:
                if cursor is not None:
                    canvas.setCursor(cursor)
                    return
        mode = canvas._tools_manager.get_control_mode()
        provider = self._providers.get(mode)
        if provider is not None:
            try:
                cursor = provider(canvas)
            except Exception:
                logger.exception("Cursor provider failed for mode %s", mode)
            else:
                if cursor is not None:
                    canvas.setCursor(cursor)
                    return
        if mode == Tools.CONTROL_MODE_DRAW_BRUSH:
            self.update_brush(erase_indicator=self.alt_held)
        elif mode == Tools.CONTROL_MODE_SMART_SELECT:
            canvas.setCursor(
                canvas.cursor_builder.create_smart_select_cursor(
                    erase_indicator=self.alt_held
                )
            )
        else:
            canvas.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def update_brush(self, *, erase_indicator: bool = False) -> None:
        """Render target-neutral brush feedback for the active paint destination."""
        canvas = self._canvas
        resolution = canvas.editorOperationResolver().resolve(EditorOperation.PAINT)
        if not resolution.allowed:
            self.custom_cursor = None
            canvas.setCursor(QCursor(Qt.CursorShape.ForbiddenCursor))
            return
        color = canvas.paintingCoordinator().preview_color()
        if color is None:
            self.custom_cursor = None
            canvas.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            return
        zoom = max(1e-6, float(canvas.view().viewport.zoom))
        dpr = max(1e-6, float(canvas.devicePixelRatioF()))
        logical_size = max(1, int(self.brush_size)) * zoom / dpr
        viewport_size = canvas.size()
        if logical_size > min(viewport_size.width(), viewport_size.height()):
            self.custom_cursor = None
            canvas.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            return
        cursor = canvas.cursor_builder.create_brush_cursor(
            max(2, round(logical_size)),
            color,
            erase_indicator=erase_indicator,
        )
        self.custom_cursor = cursor
        canvas.setCursor(cursor)

    def update_for_modifiers(self) -> None:
        """Refresh cursor feedback when mode-sensitive modifiers change."""
        if self._canvas._tools_manager.get_control_mode() in (
            Tools.CONTROL_MODE_DRAW_BRUSH,
            Tools.CONTROL_MODE_SMART_SELECT,
        ):
            self.update()

    def synchronize_window(self) -> None:
        """Apply the desired widget cursor to the active Qt window immediately."""
        top_level = self._canvas.window()
        window = top_level.windowHandle() if top_level is not None else None
        if window is None:
            return
        desired = self._canvas.cursor()
        if self._states_match(window.cursor(), desired):
            return
        window.setCursor(desired)

    @staticmethod
    def _states_match(current: QCursor, desired: QCursor) -> bool:
        """Return whether two Qt cursors have the same observable appearance."""
        if current.shape() != desired.shape():
            return False
        if desired.shape() != Qt.CursorShape.BitmapCursor:
            return True
        return (
            current.pixmap().cacheKey() == desired.pixmap().cacheKey()
            and current.hotSpot() == desired.hotSpot()
        )
