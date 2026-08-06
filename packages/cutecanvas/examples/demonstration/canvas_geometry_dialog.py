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
"""Demonstrate the public canvas geometry workflows in one focused dialog."""

from __future__ import annotations

from collections.abc import Callable

from cutecanvas import (
    CanvasAnchor,
    CanvasResamplingMode,
    CanvasResamplingResult,
    CuteCanvas,
)
from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)


class CanvasGeometryDialog(QDialog):
    """Offer host-facing resize, resample, and explicit crop commands."""

    def __init__(
        self,
        canvas: CuteCanvas,
        *,
        show_status: Callable[[str], None],
        parent=None,
    ) -> None:
        """Build controls exclusively over the supported CuteCanvas facade."""
        super().__init__(parent)
        self._canvas = canvas
        self._show_status = show_status
        self._pending_request = None
        self.setWindowTitle("Canvas Geometry")
        self.setModal(False)
        self._width = _dimension_input()
        self._height = _dimension_input()
        self._anchor = QComboBox(self)
        for anchor, label in _ANCHOR_LABELS:
            self._anchor.addItem(label, anchor)
        self._anchor.setCurrentIndex(
            next(
                index
                for index, (anchor, _label) in enumerate(_ANCHOR_LABELS)
                if anchor is CanvasAnchor.CENTER
            )
        )
        self._quality = QComboBox(self)
        self._quality.addItem("Smooth", CanvasResamplingMode.SMOOTH)
        self._quality.addItem("Fast / nearest", CanvasResamplingMode.FAST)
        self._resample = QPushButton("Resample Layers", self)
        self._resample.clicked.connect(self._request_resampling)
        self._resize = QPushButton("Resize Bounds", self)
        self._resize.clicked.connect(self._resize_bounds)
        self._crop_button = QPushButton("Crop Layers to Canvas", self)
        self._crop_button.clicked.connect(self._crop)
        self._build_layout()
        canvas.canvasResamplingCompleted.connect(self._resampling_finished)
        canvas.compositionSelectionChanged.connect(lambda _value: self.refresh())
        canvas.compositionChanged.connect(lambda _value: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        """Load the active composition dimensions and enabled state."""
        current = self._canvas.editor.compositions.current
        enabled = current is not None and self._pending_request is None
        for control in (
            self._width,
            self._height,
            self._anchor,
            self._quality,
            self._resize,
            self._resample,
            self._crop_button,
        ):
            control.setEnabled(enabled)
        if current is None:
            return
        bounds = current.state.scene_bounds
        if bounds is not None:
            self._width.setValue(round(bounds.width()))
            self._height.setValue(round(bounds.height()))

    def _build_layout(self) -> None:
        """Assemble task-oriented controls and behavior explanations."""
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Resize Bounds changes the aperture and aligns content without "
            "resampling. Resample Layers scales every layer. Crop is a separate "
            "semantic clip and preserves source authorship.",
            self,
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        form = QFormLayout()
        form.addRow("Width", self._width)
        form.addRow("Height", self._height)
        form.addRow("Content anchor", self._anchor)
        form.addRow("Resampling", self._quality)
        layout.addLayout(form)
        actions = QHBoxLayout()
        actions.addWidget(self._resize)
        actions.addWidget(self._resample)
        actions.addWidget(self._crop_button)
        layout.addLayout(actions)

    def _resize_bounds(self) -> None:
        """Apply the selected nine-point alignment without resampling."""
        current = self._canvas.editor.compositions.current
        if current is None:
            return
        changed = current.resize_bounds(
            self._size(),
            anchor=self._anchor.currentData(),
        )
        self._show_status(
            "Canvas bounds resized without resampling."
            if changed
            else "Canvas bounds already match that size."
        )

    def _request_resampling(self) -> None:
        """Begin one asynchronous source-aware whole-canvas resample."""
        current = self._canvas.editor.compositions.current
        if current is None:
            return
        self._pending_request = current.resample(
            self._size(),
            mode=self._quality.currentData(),
        )
        self._resample.setEnabled(False)
        self._show_status("Resampling canvas layers…")

    def _crop(self) -> None:
        """Confirm and apply the explicit current-canvas crop boundary."""
        current = self._canvas.editor.compositions.current
        if current is None:
            return
        answer = QMessageBox.question(
            self,
            "Crop Layers to Canvas",
            "Clip every layer to the current canvas bounds? The operation is undoable.",
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return
        changed = current.crop_to_canvas()
        self._show_status(
            "Every layer was cropped to the canvas."
            if changed
            else "The composition has no layers to crop."
        )

    def _resampling_finished(self, result: CanvasResamplingResult) -> None:
        """Present the terminal result for the request started by this dialog."""
        if result.request_id != self._pending_request:
            return
        self._pending_request = None
        self.refresh()
        self._show_status(
            "Canvas resampling complete."
            if result.changed
            else (
                result.message
                if result.succeeded
                else f"Canvas resampling {result.status.value}: {result.message}"
            )
        )

    def _size(self) -> QSize:
        """Return the selected positive integer canvas size."""
        return QSize(self._width.value(), self._height.value())


def _dimension_input() -> QSpinBox:
    """Return one bounded whole-pixel dimension editor."""
    field = QSpinBox()
    field.setRange(1, 1_000_000)
    return field


_ANCHOR_LABELS = (
    (CanvasAnchor.TOP_LEFT, "Top left"),
    (CanvasAnchor.TOP, "Top"),
    (CanvasAnchor.TOP_RIGHT, "Top right"),
    (CanvasAnchor.LEFT, "Left"),
    (CanvasAnchor.CENTER, "Center"),
    (CanvasAnchor.RIGHT, "Right"),
    (CanvasAnchor.BOTTOM_LEFT, "Bottom left"),
    (CanvasAnchor.BOTTOM, "Bottom"),
    (CanvasAnchor.BOTTOM_RIGHT, "Bottom right"),
)


__all__ = ["CanvasGeometryDialog"]
