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

"""Public-API Move-tool controls for the demonstration host."""

from __future__ import annotations

from cutecanvas import CuteCanvas, MoveToolOptions
from PySide6.QtCore import QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QToolBar


class MoveControls(QObject):
    """Present direct layer-selection policy beside the Move tool."""

    def __init__(
        self,
        canvas: CuteCanvas,
        toolbar: QToolBar,
        *,
        parent: QObject,
    ) -> None:
        """Create and synchronize the auto-selection action."""
        super().__init__(parent)
        self._canvas = canvas
        self._toolbar = toolbar
        self.auto_select_action = QAction("Auto-select layers", self)
        self.auto_select_action.setCheckable(True)
        self.auto_select_action.toggled.connect(self._set_auto_select)
        toolbar.addAction(self.auto_select_action)
        canvas.moveToolOptionsChanged.connect(self._sync_options)
        self._sync_options(canvas.moveToolOptions())

    def sync_mode(self, mode: str) -> None:
        """Show these controls only while the Move tool is active."""
        self._toolbar.setVisible(mode == CuteCanvas.CONTROL_MODE_MOVE)

    def _set_auto_select(self, enabled: bool) -> None:
        """Replace the immutable public options from one checkbox change."""
        self._canvas.setMoveToolOptions(MoveToolOptions(auto_select_layers=enabled))

    def _sync_options(self, options: MoveToolOptions) -> None:
        """Mirror authoritative options without feeding back into the canvas."""
        self.auto_select_action.blockSignals(True)
        self.auto_select_action.setChecked(options.auto_select_layers)
        self.auto_select_action.blockSignals(False)
