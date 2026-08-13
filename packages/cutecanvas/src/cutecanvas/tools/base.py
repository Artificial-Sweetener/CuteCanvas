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
"""Editor-only tool signals layered on QPane's viewer-tool contract."""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import QPoint, Signal

from qpane import CursorTool, PanZoomTool, ViewerTool, ViewerToolSignals

from .cursor_feedback import ToolCursorStyle


class ToolSignals(ViewerToolSignals):
    """Requests unique to CuteCanvas editing tools."""

    stroke_applied = Signal(object)
    stroke_completed = Signal()
    stroke_cancelled = Signal()
    brush_size_changed = Signal(int)
    smart_segmentation_requested = Signal(object)
    mask_component_adjustment_requested = Signal(QPoint, bool)
    undo_state_push_requested = Signal()


class BaseTool(ViewerTool):
    """Base for CuteCanvas tools that add editor-domain requests."""

    cursor_style: ClassVar[ToolCursorStyle] = ToolCursorStyle.DEFAULT
    supports_alt_erase_indicator: ClassVar[bool] = False

    def __init__(self) -> None:
        """Create the editor signal hub expected by built-in editor tools."""
        super().__init__()
        self.signals = ToolSignals()


__all__ = ["BaseTool", "CursorTool", "PanZoomTool", "ToolSignals"]
