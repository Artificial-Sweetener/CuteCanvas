#    QPane - High-performance PySide6 image viewer
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

"""Lightweight editors for live hook experimentation in the example demo."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


class HookEditorWindow(QDialog):
    """Editable window that applies hook code via a supplied callback."""

    def __init__(
        self,
        title: str,
        description: str,
        seed_code: str,
        on_apply: Callable[[str], tuple[bool, str]],
        parent=None,
    ) -> None:
        """Render the editor UI and wire the Apply callback.

        Args:
            title: Window title describing the hook category.
            description: Short paragraph shown above the editor.
            seed_code: Initial code snippet to populate the text box.
            on_apply: Callback that consumes the code text and returns
                (success, message) for user feedback.
            parent: Optional QWidget parent.
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self._on_apply = on_apply
        layout = QVBoxLayout(self)
        self._description = QLabel(description, self)
        self._description.setWordWrap(True)
        layout.addWidget(self._description)
        self._editor = QPlainTextEdit(self)
        self._editor.setPlainText(seed_code.strip() + "\n")
        self._editor.setFont(QFont("Consolas", 10))
        layout.addWidget(self._editor)
        self._status = QLabel("", self)
        layout.addWidget(self._status)
        self._apply_button = QPushButton("Apply", self)
        self._apply_button.clicked.connect(self._handle_apply)
        layout.addWidget(self._apply_button)
        self.resize(720, 480)

    def _handle_apply(self) -> None:
        """Run the apply callback and surface the result."""
        success, message = self._on_apply(self._editor.toPlainText())
        self._status.setText(message)
        if success:
            self._status.setStyleSheet("color: green;")
        else:
            self._status.setStyleSheet("color: red;")

    def set_code(self, code: str) -> None:
        """Replace the editor contents while keeping focus."""
        self._editor.setPlainText(code.strip() + "\n")
