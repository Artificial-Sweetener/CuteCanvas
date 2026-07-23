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
"""Public-API host policy controls for the demonstration editor."""

from __future__ import annotations

from collections.abc import Callable

from cutecanvas import CuteCanvas, EditorCapability, EditorPolicy
from PySide6.QtCore import QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

_CAPABILITY_LABELS = (
    (EditorCapability.SELECT_PIXELS, "Pixel Selection"),
    (EditorCapability.EDIT_PIXELS, "Pixel Editing"),
    (EditorCapability.PAINT, "Painting"),
    (EditorCapability.MOVE_LAYERS, "Move Layers"),
    (EditorCapability.TRANSFORM_LAYERS, "Transform Layers"),
)


class EditorPolicyControls(QObject):
    """Own demo actions that compose the host's editor capability policy."""

    def __init__(
        self,
        qpane: CuteCanvas,
        *,
        show_status: Callable[[str], None],
        parent: QObject,
    ) -> None:
        """Build checkable actions and track public policy replacements."""
        super().__init__(parent)
        self._qpane = qpane
        self._show_status = show_status
        self._synchronizing = False
        self._actions: dict[EditorCapability, QAction] = {}
        for capability, label in _CAPABILITY_LABELS:
            action = QAction(label, self, checkable=True)
            action.toggled.connect(self._apply_checked_capabilities)
            self._actions[capability] = action
        qpane.editorPolicyChanged.connect(self._synchronize)
        self._synchronize(qpane.editorPolicy())

    def populate_menu(self, menu: QMenu) -> None:
        """Populate one compact submenu in stable capability order."""
        for capability, _label in _CAPABILITY_LABELS:
            menu.addAction(self._actions[capability])

    def _apply_checked_capabilities(self, _checked: bool = False) -> None:
        """Replace the public policy from the complete checked action set."""
        if self._synchronizing:
            return
        capabilities = frozenset(
            capability
            for capability, action in self._actions.items()
            if action.isChecked()
        )
        if self._qpane.setEditorPolicy(EditorPolicy(capabilities)):
            enabled = len(capabilities)
            self._show_status(f"Host editor policy enables {enabled} capabilities.")

    def _synchronize(self, policy: EditorPolicy) -> None:
        """Mirror an externally replaced policy without recursive writes."""
        self._synchronizing = True
        try:
            for capability, action in self._actions.items():
                action.setChecked(capability in policy.capabilities)
        finally:
            self._synchronizing = False
