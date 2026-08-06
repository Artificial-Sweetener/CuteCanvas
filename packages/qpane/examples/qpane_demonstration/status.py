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
"""Teach compact image and zoom status controls around QPane signals."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QStatusBar,
    QToolButton,
    QWidget,
)


class ViewerStatusBar(QStatusBar):
    """Own the viewer demo's status message, size, and zoom controls."""

    zoomRequested = Signal(float)
    zoomPresetRequested = Signal(str)

    def __init__(self) -> None:
        """Build the compact permanent status widgets."""
        super().__init__()
        self.image_size_label = QLabel("-- × -- px")
        self.image_size_label.setObjectName("imageSizeStatusLabel")
        self.image_size_label.setStyleSheet("padding: 0 6px;")
        self.addPermanentWidget(self.image_size_label)

        toggle_container = QWidget()
        toggle_layout = QHBoxLayout(toggle_container)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        self.zoom_toggle = QToolButton()
        self.zoom_toggle.setObjectName("zoomToggleButton")
        self.zoom_toggle.setAutoRaise(True)
        self.zoom_toggle.setText("Fit")
        self.zoom_toggle.setToolTip("Toggle between fit and actual pixels")
        self.zoom_toggle.clicked.connect(self._request_zoom_preset)
        toggle_layout.addWidget(self.zoom_toggle)
        self.addPermanentWidget(toggle_container)

        zoom_container = QWidget()
        zoom_layout = QHBoxLayout(zoom_container)
        zoom_layout.setContentsMargins(6, 0, 6, 0)
        zoom_layout.setSpacing(3)
        zoom_layout.addWidget(QLabel("Zoom:"))
        self.zoom_input = QLineEdit("100%")
        self.zoom_input.setObjectName("zoomPercentInput")
        self.zoom_input.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.zoom_input.setFrame(False)
        self.zoom_input.setMaximumWidth(68)
        self.zoom_input.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.zoom_input.returnPressed.connect(self._submit_zoom)
        zoom_layout.addWidget(self.zoom_input)
        self.addPermanentWidget(zoom_container)

    def set_image_size(self, width: int | None, height: int | None) -> None:
        """Update the active image dimensions or show an empty readout."""
        if width is None or height is None:
            self.image_size_label.setText("-- × -- px")
        else:
            self.image_size_label.setText(f"{width} × {height} px")

    def set_zoom(self, zoom: float) -> None:
        """Reflect one effective zoom without disrupting active text entry."""
        if not self.zoom_input.hasFocus():
            self.zoom_input.setText(f"{zoom * 100:.1f}%")

    def _request_zoom_preset(self, _checked: bool = False) -> None:
        """Alternate the status toggle between fit and native pixels."""
        preset = "actual" if self.zoom_toggle.text() == "Fit" else "fit"
        self.zoom_toggle.setText("1:1" if preset == "actual" else "Fit")
        self.zoomPresetRequested.emit(preset)

    def _submit_zoom(self) -> None:
        """Parse a user-entered percentage and publish a zoom multiplier."""
        text = self.zoom_input.text().strip().removesuffix("%").strip()
        try:
            percent = float(text)
        except ValueError:
            return
        if percent > 0.0:
            self.zoomRequested.emit(percent / 100.0)
