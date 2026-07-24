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
"""Focused public-API raster-storage properties for the demonstration."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from cutecanvas import CuteCanvas, RasterExtentPolicy, RasterSurfaceSnapshot
from PySide6.QtCore import QRect
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

_PAD_INCREMENT = 32
_COORDINATE_LIMIT = 1_000_000_000


class RasterStorageProperties(QWidget):
    """Edit one raster layer's extent policy and integer local bounds."""

    def __init__(
        self,
        qpane: CuteCanvas,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        parent: QWidget | None = None,
        *,
        show_status: Callable[[str], None] | None = None,
    ) -> None:
        """Build the inspector and subscribe only to CuteCanvas's public contract."""
        super().__init__(parent)
        self.setObjectName("rasterLayerInspector")
        self._qpane = qpane
        self._show_status = show_status
        self._target = (scene_id, layer_id)
        self._edited_layer: tuple[uuid.UUID, uuid.UUID] | None = None
        self._bounds_dirty = False
        self._build_content()
        self._connect_signals()
        self.refresh()

    def refresh(self, *_args: object) -> None:
        """Refresh the one layer identity selected by the composition tree."""
        self._refresh_state()

    def _build_content(self) -> None:
        """Build focused controls for policy and integer local bounds."""
        layout = QVBoxLayout(self)
        self._raster_group = QGroupBox("Raster Storage", self)
        raster_layout = QVBoxLayout(self._raster_group)
        form = QFormLayout()
        self._policy_combo = QComboBox(self)
        self._policy_combo.addItem("Fixed", RasterExtentPolicy.FIXED)
        self._policy_combo.addItem(
            "Expand on write",
            RasterExtentPolicy.EXPAND_ON_WRITE,
        )
        self._policy_combo.addItem(
            "Unbounded",
            RasterExtentPolicy.UNBOUNDED,
        )
        form.addRow("Write policy", self._policy_combo)
        self._bound_inputs: dict[str, QSpinBox] = {}
        for name, label in (
            ("x", "X"),
            ("y", "Y"),
            ("width", "Width"),
            ("height", "Height"),
        ):
            editor = QSpinBox(self)
            editor.setRange(
                1 if name in {"width", "height"} else -_COORDINATE_LIMIT,
                _COORDINATE_LIMIT,
            )
            editor.valueChanged.connect(self._mark_bounds_dirty)
            self._bound_inputs[name] = editor
            form.addRow(label, editor)
        raster_layout.addLayout(form)
        buttons = QHBoxLayout()
        self._apply_button = QPushButton("Apply Bounds", self)
        self._pad_button = QPushButton(f"Pad {_PAD_INCREMENT}px", self)
        buttons.addWidget(self._apply_button)
        buttons.addWidget(self._pad_button)
        raster_layout.addLayout(buttons)
        self._status = QLabel("No raster layer is available.", self)
        self._status.setWordWrap(True)
        raster_layout.addWidget(self._status)
        layout.addWidget(self._raster_group)
        layout.addStretch(1)

    def _connect_signals(self) -> None:
        """Connect host controls and public CuteCanvas state notifications."""
        self._policy_combo.currentIndexChanged.connect(self._apply_policy)
        self._apply_button.clicked.connect(self._apply_bounds)
        self._pad_button.clicked.connect(self._pad_bounds)
        self._qpane.compositionChanged.connect(self.refresh)
        self._qpane.sceneChanged.connect(self.refresh)
        self._qpane.selectedLayerChanged.connect(self.refresh)
        self._qpane.maskUndoStackChanged.connect(self.refresh)
        self._qpane.rasterBoundsRequestCompleted.connect(self._handle_bounds_completion)

    def _target_layer(self) -> tuple[uuid.UUID, uuid.UUID]:
        """Return the fixed scene and layer identity supplied by the tree."""
        return self._target

    def _state(self) -> RasterSurfaceSnapshot | None:
        """Query the selected raster layer through the facade."""
        return self._qpane.rasterSurfaceState(*self._target_layer())

    def _refresh_state(self, *_args: object) -> None:
        """Populate controls from one detached public state snapshot."""
        target_layer = self._target_layer()
        if target_layer != self._edited_layer:
            self._edited_layer = target_layer
            self._bounds_dirty = False
        state = self._state()
        enabled = state is not None
        self._raster_group.setVisible(enabled)
        self._policy_combo.setEnabled(enabled)
        self._apply_button.setEnabled(enabled)
        self._pad_button.setEnabled(enabled)
        for editor in self._bound_inputs.values():
            editor.setEnabled(enabled)
        if state is None:
            self._status.setText("No raster layer is available.")
            return
        bounds = state.bounds
        if not self._bounds_dirty:
            self._set_bounds_inputs(bounds)
        self._policy_combo.blockSignals(True)
        self._policy_combo.setCurrentIndex(
            self._policy_combo.findData(state.extent_policy)
        )
        self._policy_combo.blockSignals(False)
        pending = state.pending_request_id is not None
        self._apply_button.setEnabled(not pending)
        self._pad_button.setEnabled(not pending)
        if pending:
            self._status.setText("Preparing bounds...")
        elif self._bounds_dirty:
            edited = self._edited_bounds()
            self._status.setText(
                f"Edited bounds: {edited.x()}, {edited.y()}, "
                f"{edited.width()} x {edited.height()}. Click Apply Bounds."
            )
        else:
            self._status.setText(
                f"Local bounds: {bounds.x()}, {bounds.y()}, "
                f"{bounds.width()} x {bounds.height()}"
            )

    def _mark_bounds_dirty(self, _value: int) -> None:
        """Preserve host-entered bounds across unrelated scene refreshes."""
        self._bounds_dirty = True
        edited = self._edited_bounds()
        self._status.setText(
            f"Edited bounds: {edited.x()}, {edited.y()}, "
            f"{edited.width()} x {edited.height()}. Click Apply Bounds."
        )

    def _set_bounds_inputs(self, bounds: QRect) -> None:
        """Display one bounds rectangle without treating it as a user edit."""
        values = {
            "x": bounds.x(),
            "y": bounds.y(),
            "width": bounds.width(),
            "height": bounds.height(),
        }
        for name, value in values.items():
            editor = self._bound_inputs[name]
            editor.blockSignals(True)
            editor.setValue(value)
            editor.blockSignals(False)

    def _apply_policy(self, _index: int) -> None:
        """Apply the selected storage policy without changing pixels or bounds."""
        layer = self._target_layer()
        policy_value = self._policy_combo.currentData()
        if not isinstance(policy_value, str):
            return
        policy = RasterExtentPolicy(policy_value)
        if self._qpane.setRasterExtentPolicy(*layer, policy):
            self._status.setText(f"Write policy set to {policy.value}.")

    def _edited_bounds(self) -> QRect:
        """Return the integer local bounds currently shown by the editors."""
        return QRect(
            self._bound_inputs["x"].value(),
            self._bound_inputs["y"].value(),
            self._bound_inputs["width"].value(),
            self._bound_inputs["height"].value(),
        )

    def _apply_bounds(self) -> None:
        """Confirm destructive cropping and submit one asynchronous resize."""
        state = self._state()
        if state is None:
            return
        requested = self._edited_bounds()
        if not requested.contains(state.bounds) and not self._confirm_crop():
            self._bounds_dirty = False
            self._refresh_state()
            return
        self._request_bounds(requested)

    def _pad_bounds(self) -> None:
        """Pad every storage edge while preserving the layer transform."""
        state = self._state()
        if state is None:
            return
        bounds = state.bounds
        self._request_bounds(
            QRect(
                bounds.x() - _PAD_INCREMENT,
                bounds.y() - _PAD_INCREMENT,
                bounds.width() + 2 * _PAD_INCREMENT,
                bounds.height() + 2 * _PAD_INCREMENT,
            )
        )

    def _confirm_crop(self) -> bool:
        """Ask before discarding pixels outside newly requested local bounds."""
        answer = QMessageBox.question(
            self,
            "Crop Raster Layer",
            "Pixels outside the new local bounds will be removed. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _request_bounds(self, bounds: QRect) -> None:
        """Submit bounds work and expose its asynchronous request identity."""
        layer = self._target_layer()
        self._set_bounds_inputs(bounds)
        self._bounds_dirty = True
        request_id = self._qpane.requestRasterBounds(*layer, bounds)
        if request_id is None:
            self._status.setText("The selected layer did not accept new bounds.")
            return
        self._apply_button.setEnabled(False)
        self._pad_button.setEnabled(False)
        self._status.setText(f"Preparing bounds request {str(request_id)[:8]}...")

    def _handle_bounds_completion(
        self,
        request_id: uuid.UUID,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        succeeded: bool,
        message: str,
    ) -> None:
        """Show terminal request status and refresh the selected layer."""
        del request_id
        if self._target_layer() != (scene_id, layer_id):
            return
        if succeeded:
            self._bounds_dirty = False
        self._refresh_state()
        self._status.setText(
            "Raster bounds updated."
            if succeeded
            else f"Raster bounds were not updated: {message}"
        )
