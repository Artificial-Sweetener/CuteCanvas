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

"""Demo-only tools used to showcase CuteCanvas's hook-based tool registration."""

from __future__ import annotations

from qpane import ViewerTool


def build_custom_cursor_tool(qpane_widget):
    """Return an inert tool that relies on hook-provided cursors and overlays."""

    class CustomCursorTool(ViewerTool):
        """Cursor-only tool that requests repaints so hook visuals track the pointer."""

        def __init__(self):
            """Initialize the tool and store the qpane reference for optional helpers."""
            super().__init__()
            self._qpane = qpane_widget

        def mouseMoveEvent(self, event):
            """Request overlay and cursor refresh so hooks track the pointer."""
            self.signals.repaint_overlay_requested.emit()
            self.signals.cursor_update_requested.emit()
            event.ignore()

    return CustomCursorTool
