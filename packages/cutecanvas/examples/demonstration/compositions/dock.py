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

"""Compact composition-and-layer panel for the CuteCanvas example."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtWidgets import QLabel, QSizePolicy, QToolBar, QVBoxLayout, QWidget

from cutecanvas import CuteCanvas
from demonstration import demo_text
from demonstration.compositions.browser import CompositionBrowser


class CompositionDock(QWidget):
    """Present composition compositions and their ordinary ordered layers."""

    visibilityChanged = Signal(bool)
    layerPropertiesRequested = Signal(object, object)
    compositionPropertiesRequested = Signal(object)

    def __init__(
        self,
        canvas: CuteCanvas,
        *,
        on_focus_requested: Callable[[str], None],
        set_status: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        """Build an intentional composition panel over the public editor facade."""
        super().__init__(parent)
        self._canvas = canvas
        self._set_status = set_status
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._toolbar = QToolBar(self)
        self._toolbar.setMovable(False)
        self._toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._toolbar.setStyleSheet("QToolBar { border: 0; }")
        self._toolbar.addAction("New", self._create_composition)
        self._toolbar.addAction("Close", self._close_composition)
        tips = self._toolbar.addAction("Tips")
        tips.setCheckable(True)
        layout.addWidget(self._toolbar)

        self._hint = QLabel(demo_text.COMPOSITIONS_HINT, self)
        self._hint.setWordWrap(True)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._hint.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self._hint.hide()
        tips.toggled.connect(self._hint.setVisible)
        layout.addWidget(self._hint)

        self._browser = CompositionBrowser(
            canvas,
            on_focus_requested=on_focus_requested,
            parent=self,
        )
        self._browser.layerPropertiesRequested.connect(self.layerPropertiesRequested)
        self._browser.compositionPropertiesRequested.connect(
            self.compositionPropertiesRequested
        )
        self._browser.statusRequested.connect(set_status)
        layout.addWidget(self._browser)

    def panelWidthHint(self) -> int:
        """Return the compact width required by the text-only toolbar."""
        margins = self.layout().contentsMargins()
        return self._toolbar.sizeHint().width() + margins.left() + margins.right()

    def refresh_selection(self) -> None:
        """Refresh composition rows and active-layer highlighting."""
        self._browser.refresh()

    def showEvent(self, event) -> None:  # type: ignore[override]
        """Publish panel visibility after Qt reveals the widget."""
        super().showEvent(event)
        self.visibilityChanged.emit(True)

    def hideEvent(self, event) -> None:  # type: ignore[override]
        """Publish panel visibility after Qt hides the widget."""
        super().hideEvent(event)
        self.visibilityChanged.emit(False)

    def _create_composition(self) -> None:
        """Create an empty composition sized from the active canvas."""
        scene = self._canvas.currentScene()
        bounds = (
            QRectF(0.0, 0.0, 1920.0, 1080.0) if scene is None else QRectF(scene.bounds)
        )
        count = len(self._canvas.editor.compositions) + 1
        self._canvas.editor.compositions.create(bounds, title=f"Untitled {count}")
        self._set_status("Created an empty composition.")

    def _close_composition(self) -> None:
        """Close the active composition when host policy allows removal."""
        composition = self._canvas.editor.compositions.current
        if composition is None:
            self._set_status("No composition is open.")
            return
        if not composition.state.policy.removable:
            self._set_status("The host has locked this composition.")
            return
        composition.remove()
        self._set_status("Closed composition.")
