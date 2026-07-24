#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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
"""Demo contracts for intentional public editor-policy controls."""

from cutecanvas import CuteCanvas, EditorCapability
from PySide6.QtWidgets import QMenu

from examples.demonstration.editor_policy_controls import EditorPolicyControls


def test_demo_editor_policy_menu_composes_public_capabilities(qapp) -> None:
    """The compact demo menu must mirror and replace only the public policy."""
    viewer = CuteCanvas(features=())
    messages: list[str] = []
    controls = EditorPolicyControls(
        viewer,
        show_status=messages.append,
        parent=viewer,
    )
    menu = QMenu()
    controls.populate_menu(menu)
    try:
        actions = menu.actions()
        assert len(actions) == len(EditorCapability)
        assert all(action.isChecked() for action in actions)

        paint = next(action for action in actions if action.text() == "Painting")
        paint.setChecked(False)

        assert EditorCapability.PAINT not in viewer.editorPolicy().capabilities
        assert len(viewer.editorPolicy().capabilities) == len(EditorCapability) - 1
        expected = len(EditorCapability) - 1
        assert messages[-1] == (f"Host editor policy enables {expected} capabilities.")
    finally:
        menu.deleteLater()
        viewer.deleteLater()
        qapp.processEvents()
