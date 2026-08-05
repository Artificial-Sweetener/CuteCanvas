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
"""Demonstrate the public replaceable pixel-selection preview transaction."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from cutecanvas import CuteCanvas, LayerEdgeOperation
from PySide6.QtCore import QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QInputDialog


class SelectionModificationDemoControl(QObject):
    """Own demo actions and one nonmodal live selection-preview editor."""

    def __init__(
        self,
        canvas: CuteCanvas,
        show_status: Callable[[str], None],
        parent: QObject,
    ) -> None:
        """Bind the public selection facade and demo status presentation."""

        super().__init__(parent)
        self._canvas = canvas
        self._show_status = show_status
        self._session_id: uuid.UUID | None = None
        self._dialog: QInputDialog | None = None
        self.expand_action = self._action(
            "Expand Selection...",
            LayerEdgeOperation.EXPAND,
        )
        self.contract_action = self._action(
            "Contract Selection...",
            LayerEdgeOperation.CONTRACT,
        )
        self.feather_action = self._action(
            "Feather Selection...",
            LayerEdgeOperation.FEATHER,
        )
        self.destroyed.connect(self._cancel_active)

    def set_enabled(self, enabled: bool) -> None:
        """Project selection availability into every modification action."""

        self.expand_action.setEnabled(enabled)
        self.contract_action.setEnabled(enabled)
        self.feather_action.setEnabled(enabled)

    def _action(
        self,
        label: str,
        operation: LayerEdgeOperation,
    ) -> QAction:
        """Create one operation action routed through the shared preview editor."""

        action = QAction(label, self)
        action.triggered.connect(lambda: self._open(operation))
        return action

    def _open(self, operation: LayerEdgeOperation) -> None:
        """Start one nonmodal editor whose values replace a captured base."""

        self._cancel_active()
        session_id = self._canvas.editor.selection.begin_modification()
        if session_id is None:
            self._show_status("A pixel selection is required.")
            return
        self._session_id = session_id
        dialog = QInputDialog(self._canvas)
        dialog.setObjectName("SelectionModificationPreviewDialog")
        dialog.setWindowTitle("Modify Selection")
        dialog.setLabelText(f"{operation.value.title()} by pixels:")
        dialog.setInputMode(QInputDialog.InputMode.IntInput)
        dialog.setIntRange(1, 999)
        dialog.setIntValue(4)
        dialog.setModal(False)
        dialog.intValueChanged.connect(lambda value: self._preview(operation, value))
        dialog.accepted.connect(self._apply_active)
        dialog.rejected.connect(self._cancel_active)
        self._dialog = dialog
        self._preview(operation, dialog.intValue())
        dialog.open()

    def _preview(self, operation: LayerEdgeOperation, radius: int) -> None:
        """Replace the visible product using the session's original selection."""

        session_id = self._session_id
        if session_id is None:
            return
        if (
            self._canvas.editor.selection.preview_modification(
                session_id,
                operation,
                radius,
            )
            is None
        ):
            self._show_status("Selection preview could not be updated.")

    def _apply_active(self) -> None:
        """Settle the latest value once and release demo dialog ownership."""

        session_id = self._session_id
        self._release_dialog()
        if session_id is None:
            return
        self._session_id = None
        if self._canvas.editor.selection.apply_modification(session_id):
            self._show_status("Applying selection modification...")
        else:
            self._show_status("Selection modification could not be applied.")

    def _cancel_active(self, *_args: object) -> None:
        """Restore the captured selection and release demo dialog ownership."""

        session_id = self._session_id
        self._session_id = None
        self._release_dialog()
        if session_id is not None:
            self._canvas.editor.selection.cancel_modification(session_id)

    def _release_dialog(self) -> None:
        """Detach and delete the current nonmodal editor without re-entering it."""

        dialog = self._dialog
        self._dialog = None
        if dialog is not None:
            dialog.deleteLater()


__all__ = ["SelectionModificationDemoControl"]
