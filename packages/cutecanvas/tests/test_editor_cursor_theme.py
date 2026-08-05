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

"""Verify semantic editor cursor arbitration and host theming."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from cutecanvas.cursor import EditorCursorIntent
from cutecanvas.tools.cursor_controller import EditorCursorController
from cutecanvas.tools.smart_segmentation import SmartMaskTool, SmartSelectTool
from cutecanvas.ui.cursor_builder import CursorBuilder
from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from cutecanvas.canvas import CuteCanvas


class _IntentTool:
    """Expose one semantic intent without choosing cursor artwork."""

    def cursor_intent(self) -> EditorCursorIntent:
        """Request selection-boundary translation feedback."""

        return EditorCursorIntent.SELECTION_TRANSLATE


class _CursorTheme:
    """Record semantic requests and return one recognizable cursor."""

    def __init__(self) -> None:
        """Initialize an empty resolution history."""

        self.requests: list[tuple[EditorCursorIntent, float]] = []

    def resolve_cursor(
        self,
        intent: EditorCursorIntent,
        *,
        device_pixel_ratio: float,
    ) -> QCursor | None:
        """Resolve translation to a test cursor and defer every other intent."""

        self.requests.append((intent, device_pixel_ratio))
        if intent is EditorCursorIntent.SELECTION_TRANSLATE:
            return QCursor(Qt.CursorShape.PointingHandCursor)
        return None


class _CursorCanvas(QWidget):
    """Mount the real QWidget cursor boundary around a deterministic active tool."""

    def __init__(self, active_tool: object | None = None) -> None:
        """Provide only the collaborators used by semantic arbitration."""

        super().__init__()
        self._is_blank = False
        self.settings = SimpleNamespace(default_brush_size=20)
        self.cursor_builder = CursorBuilder()
        tool = _IntentTool() if active_tool is None else active_tool
        self._tools_manager = SimpleNamespace(
            get_active_tool=lambda: tool,
            get_control_mode=lambda: "selection",
        )


def test_host_theme_resolves_semantic_cursor_before_portable_default(qapp) -> None:
    """The host theme should control artwork without owning interaction state."""

    canvas = _CursorCanvas()
    controller = EditorCursorController(
        cast("CuteCanvas", canvas),
        cursor_suppressed=lambda: False,
    )
    theme = _CursorTheme()

    controller.set_theme(theme)

    assert canvas.cursor().shape() is Qt.CursorShape.PointingHandCursor
    assert theme.requests == [
        (EditorCursorIntent.SELECTION_TRANSLATE, canvas.devicePixelRatioF())
    ]


def test_missing_host_artwork_falls_back_to_portable_selection_cursor(qapp) -> None:
    """A partial host theme must preserve complete CuteCanvas cursor behavior."""

    canvas = _CursorCanvas()
    controller = EditorCursorController(
        cast("CuteCanvas", canvas),
        cursor_suppressed=lambda: False,
    )

    controller.update()

    assert canvas.cursor().shape() is Qt.CursorShape.SizeAllCursor


@pytest.mark.parametrize("tool_type", (SmartSelectTool, SmartMaskTool))
def test_smart_segmentation_tools_resolve_selection_crosshair(
    qapp,
    tool_type: type[SmartSelectTool | SmartMaskTool],
) -> None:
    """Smart segmentation modes must not fall through to QPane's arrow cursor."""

    canvas = _CursorCanvas(tool_type())
    controller = EditorCursorController(
        cast("CuteCanvas", canvas),
        cursor_suppressed=lambda: False,
    )

    controller.update()

    assert canvas.cursor().shape() is Qt.CursorShape.BitmapCursor
