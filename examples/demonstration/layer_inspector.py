#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Public-API raster layer inspector used by the demonstration host."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QRect
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from qpane import QPane, QPaneRasterSurfaceState, RasterExtentPolicy

_PAD_INCREMENT = 32
_COORDINATE_LIMIT = 1_000_000_000


class RasterLayerInspector(QDockWidget):
    """Let demo users inspect and resize active mask-backed raster layers."""

    def __init__(self, qpane: QPane, parent: QWidget | None = None) -> None:
        """Build the inspector and subscribe only to QPane's public contract."""
        super().__init__("Layer Inspector", parent)
        self.setObjectName("rasterLayerInspector")
        self._qpane = qpane
        self._layers: dict[uuid.UUID, tuple[uuid.UUID, uuid.UUID]] = {}
        self._edited_layer: tuple[uuid.UUID, uuid.UUID] | None = None
        self._bounds_dirty = False
        self._build_content()
        self._connect_signals()
        self.refresh()

    def refresh(self, *_args: object) -> None:
        """Refresh the selectable mask layers and their raster surface state."""
        selected_mask_id = self._selected_mask_id()
        active_mask_id = self._qpane.activeMaskID()
        masks = self._qpane.listMasksForImage()
        self._layers = {
            info.mask_id: (info.scene_id, info.layer_id)
            for info in masks
            if info.scene_id is not None and info.layer_id is not None
        }
        preferred = (
            selected_mask_id
            if selected_mask_id in self._layers
            else (
                active_mask_id
                if active_mask_id in self._layers
                else next(iter(self._layers), None)
            )
        )
        self._layer_combo.blockSignals(True)
        self._layer_combo.clear()
        for index, info in enumerate(masks, start=1):
            if info.mask_id not in self._layers:
                continue
            label = info.label or f"Mask {index}"
            self._layer_combo.addItem(label, info.mask_id)
        if preferred is not None:
            combo_index = self._layer_combo.findData(preferred)
            self._layer_combo.setCurrentIndex(combo_index)
        self._layer_combo.blockSignals(False)
        self._refresh_state()

    def _build_content(self) -> None:
        """Build focused controls for policy and integer local bounds."""
        content = QWidget(self)
        layout = QVBoxLayout(content)
        form = QFormLayout()
        self._layer_combo = QComboBox(content)
        self._policy_combo = QComboBox(content)
        self._policy_combo.addItem("Fixed", RasterExtentPolicy.FIXED)
        self._policy_combo.addItem(
            "Expand on write",
            RasterExtentPolicy.EXPAND_ON_WRITE,
        )
        form.addRow("Raster layer", self._layer_combo)
        form.addRow("Write policy", self._policy_combo)
        self._bound_inputs: dict[str, QSpinBox] = {}
        for name, label in (
            ("x", "X"),
            ("y", "Y"),
            ("width", "Width"),
            ("height", "Height"),
        ):
            editor = QSpinBox(content)
            editor.setRange(
                1 if name in {"width", "height"} else -_COORDINATE_LIMIT,
                _COORDINATE_LIMIT,
            )
            editor.valueChanged.connect(self._mark_bounds_dirty)
            self._bound_inputs[name] = editor
            form.addRow(label, editor)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        self._apply_button = QPushButton("Apply Bounds", content)
        self._pad_button = QPushButton(f"Pad {_PAD_INCREMENT}px", content)
        buttons.addWidget(self._apply_button)
        buttons.addWidget(self._pad_button)
        layout.addLayout(buttons)
        self._status = QLabel("No raster layer is available.", content)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        layout.addStretch(1)
        self.setWidget(content)

    def _connect_signals(self) -> None:
        """Connect host controls and public QPane state notifications."""
        self._layer_combo.currentIndexChanged.connect(self._refresh_state)
        self._policy_combo.currentIndexChanged.connect(self._apply_policy)
        self._apply_button.clicked.connect(self._apply_bounds)
        self._pad_button.clicked.connect(self._pad_bounds)
        self._qpane.currentImageChanged.connect(self.refresh)
        self._qpane.catalogChanged.connect(self.refresh)
        self._qpane.sceneChanged.connect(self.refresh)
        self._qpane.maskUndoStackChanged.connect(self.refresh)
        self._qpane.rasterBoundsRequestCompleted.connect(self._handle_bounds_completion)

    def _selected_mask_id(self) -> uuid.UUID | None:
        """Return the UUID stored by the selected combo-box row."""
        value = self._layer_combo.currentData()
        return value if isinstance(value, uuid.UUID) else None

    def _selected_layer(self) -> tuple[uuid.UUID, uuid.UUID] | None:
        """Return the selected scene and layer identifiers."""
        mask_id = self._selected_mask_id()
        return None if mask_id is None else self._layers.get(mask_id)

    def _state(self) -> QPaneRasterSurfaceState | None:
        """Query the selected raster layer through the facade."""
        layer = self._selected_layer()
        if layer is None:
            return None
        return self._qpane.rasterSurfaceState(*layer)

    def _refresh_state(self, *_args: object) -> None:
        """Populate controls from one detached public state snapshot."""
        selected_layer = self._selected_layer()
        if selected_layer != self._edited_layer:
            self._edited_layer = selected_layer
            self._bounds_dirty = False
        state = self._state()
        enabled = state is not None
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
        self._bounds_dirty = self._selected_layer() is not None
        if self._bounds_dirty:
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
        layer = self._selected_layer()
        policy_value = self._policy_combo.currentData()
        if layer is None or not isinstance(policy_value, str):
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
        layer = self._selected_layer()
        if layer is None:
            return
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
        if self._selected_layer() != (scene_id, layer_id):
            return
        if succeeded:
            self._bounds_dirty = False
        self._refresh_state()
        self._status.setText(
            "Raster bounds updated."
            if succeeded
            else f"Raster bounds were not updated: {message}"
        )
