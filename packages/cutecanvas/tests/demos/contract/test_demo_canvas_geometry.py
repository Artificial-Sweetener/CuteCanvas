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
"""Public-only proof for the demonstration canvas geometry dialog."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from cutecanvas import CuteCanvas
from cutecanvas_demo import ExampleOptions, ExampleWindow
from demonstration.canvas_geometry_dialog import CanvasGeometryDialog


def test_demo_window_exposes_canvas_geometry_from_visible_menu(qapp) -> None:
    """Keep the complete workflow discoverable from the mounted demo menu bar."""
    window = ExampleWindow(ExampleOptions())
    try:
        window.show()
        qapp.processEvents()
        canvas_action = next(
            (
                action
                for action in window.menuBar().actions()
                if action.text().replace("&", "") == "Canvas"
            ),
            None,
        )
        assert canvas_action is not None
        canvas_menu = canvas_action.menu()
        assert canvas_menu is not None
        geometry_action = next(
            (
                action
                for action in canvas_menu.actions()
                if action.text() == "Canvas Geometry…"
            ),
            None,
        )
        assert geometry_action is not None
        assert geometry_action.isEnabled()

        geometry_action.trigger()
        qapp.processEvents()

        dialog = window.commands._canvas_geometry_dialog
        assert dialog is not None
        assert dialog.isVisible()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_demo_dialog_drives_anchored_bounds_through_composition_handle(qapp) -> None:
    """Keep the demo discoverable without reaching into document internals."""
    canvas = CuteCanvas(features=())
    image = QImage(4, 3, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("magenta"))
    composition_id = canvas.createCompositionFromImage(image)
    messages: list[str] = []
    dialog = CanvasGeometryDialog(canvas, show_status=messages.append)
    try:
        dialog._width.setValue(8)
        dialog._height.setValue(7)
        dialog._resize_bounds()

        state = canvas.editor.compositions.get(composition_id).state
        assert state.scene_bounds is not None
        assert state.scene_bounds.size().toSize() == QSize(8, 7)
        assert messages == ["Canvas bounds resized without resampling."]
    finally:
        dialog.close()
        canvas.close()
