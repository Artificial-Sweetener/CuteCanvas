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
"""Focused composition policy editor for the demonstration host."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from cutecanvas import CompositionPolicy, CuteCanvas
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class CompositionPropertiesDialog(QDialog):
    """Edit one document's host-owned structural policy through public API."""

    def __init__(
        self,
        qpane: CuteCanvas,
        composition_id: uuid.UUID,
        parent: QWidget | None = None,
        *,
        show_status: Callable[[str], None] | None = None,
    ) -> None:
        """Build a compact modal from one detached composition snapshot."""
        super().__init__(parent)
        entry = qpane.getCompositionSnapshot().compositions[composition_id]
        self._qpane = qpane
        self._composition_id = composition_id
        self._show_status = show_status
        self.setWindowTitle("Composition Properties")
        self.setModal(True)
        self.setMinimumWidth(340)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(entry.title, self))
        bounds = entry.scene_bounds
        if bounds is not None:
            layout.addWidget(
                QLabel(
                    f"Canvas: {bounds.width():g} × {bounds.height():g}",
                    self,
                )
            )
        self.removable = QCheckBox("Allow document removal", self)
        self.removable.setChecked(entry.policy.removable)
        layout.addWidget(self.removable)
        self.comparison_enabled = QCheckBox("Allow image comparison", self)
        self.comparison_enabled.setChecked(entry.policy.comparison_enabled)
        layout.addWidget(self.comparison_enabled)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        """Apply the detached checkbox values and close the modal."""
        changed = self._qpane.setCompositionPolicy(
            self._composition_id,
            CompositionPolicy(
                removable=self.removable.isChecked(),
                comparison_enabled=self.comparison_enabled.isChecked(),
            ),
        )
        if changed and self._show_status is not None:
            self._show_status("Composition policy updated.")
        self.accept()
