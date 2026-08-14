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
"""Demo controls for unified provisional and durable editor history."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QLabel, QMainWindow, QMenu, QToolBar

from cutecanvas import CuteCanvas, EditSessionKind

_SESSION_LABELS = {
    EditSessionKind.TRANSFORM: "Transform",
    EditSessionKind.POLYGON_SELECTION: "Polygon selection",
    EditSessionKind.POLYGON_MASK: "Polygon mask",
    EditSessionKind.SHARED_EDGE_RESIZE: "Shared edge resize",
}


class DemoHistoryControls:
    """Present Undo, Redo, Apply, and Cancel from public editor state."""

    def __init__(
        self,
        canvas: CuteCanvas,
        show_status: Callable[[str], None],
        parent: QObject,
    ) -> None:
        """Build history actions and subscribe to both history boundaries."""
        self._canvas = canvas
        self._show_status = show_status
        self.undo_action = QAction("Undo", parent)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self._undo)
        self.redo_action = QAction("Redo", parent)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.triggered.connect(self._redo)
        self.apply_action = QAction("Apply Active Edit", parent)
        self.apply_action.triggered.connect(self._apply)
        self.cancel_action = QAction("Cancel Active Edit", parent)
        self.cancel_action.triggered.connect(self._cancel)
        self.toolbar: QToolBar | None = None
        self._toolbar_label: QLabel | None = None
        canvas.sceneEditHistoryChanged.connect(self.refresh)
        canvas.editSessionChanged.connect(self.refresh)
        self.refresh()

    def populate(self, menu: QMenu) -> None:
        """Add unified history actions in their conventional order."""
        menu.addAction(self.undo_action)
        menu.addAction(self.redo_action)
        menu.addAction(self.apply_action)
        menu.addAction(self.cancel_action)

    def install_toolbar(self, window: QMainWindow) -> QToolBar:
        """Install the visible resolution surface for bounded editor sessions."""
        if self.toolbar is not None:
            return self.toolbar
        toolbar = QToolBar("Active Edit", window)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        label = QLabel(toolbar)
        toolbar.addWidget(label)
        toolbar.addAction(self.undo_action)
        toolbar.addAction(self.redo_action)
        toolbar.addSeparator()
        toolbar.addAction(self.apply_action)
        toolbar.addAction(self.cancel_action)
        window.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        self.toolbar = toolbar
        self._toolbar_label = label
        self.refresh()
        return toolbar

    def refresh(self, *_args: object) -> None:
        """Project current boundary state into action availability."""
        active = self._canvas.activeEditSession()
        self.undo_action.setEnabled(self._canvas.editorUndoAvailable())
        self.redo_action.setEnabled(self._canvas.editorRedoAvailable())
        self.apply_action.setEnabled(active is not None and active.can_apply)
        self.cancel_action.setEnabled(active is not None and active.can_cancel)
        if self.toolbar is not None:
            self.toolbar.setVisible(active is not None)
        if self._toolbar_label is not None:
            label = "" if active is None else _SESSION_LABELS[active.kind]
            self._toolbar_label.setText(f" {label} " if label else "")

    def _undo(self) -> None:
        """Undo one provisional or chronological editor edit."""
        if self._canvas.undoEditorEdit():
            self._show_status("Undid the last editor change.")

    def _redo(self) -> None:
        """Redo one provisional or chronological editor edit."""
        if self._canvas.redoEditorEdit():
            self._show_status("Redid the editor change.")

    def _apply(self) -> None:
        """Commit the unresolved tool result as one chronological edit."""
        if self._canvas.applyActiveEditSession():
            self._show_status("Applied the active editor change.")

    def _cancel(self) -> None:
        """Restore the active tool session's exact starting state."""
        if self._canvas.cancelActiveEditSession():
            self._show_status("Cancelled the active editor change.")


__all__ = ["DemoHistoryControls"]
