#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Public-API affine controls for the demo's selected movable layer."""

from __future__ import annotations

import math
import uuid

from PySide6.QtCore import QRectF
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qpane import QPane

_POSITION_LIMIT = 1_000_000_000.0
_SCALE_LIMIT = 10_000.0


class LayerTransformControls(QGroupBox):
    """Edit exact geometry for one layer chosen by the composition tree."""

    def __init__(
        self,
        qpane: QPane,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        parent: QWidget | None = None,
    ) -> None:
        """Build compact transform controls and observe public scene state."""
        super().__init__("Transform", parent)
        self._qpane = qpane
        self._target = (scene_id, layer_id)
        self._build_content()
        self._connect_signals()
        self.refresh()

    def refresh(self, *_args: object) -> None:
        """Reflect the fixed layer without applying edited values."""
        transform = self._qpane.layerTransform(*self._target)
        bounds = self._qpane.layerLocalBounds(*self._target)
        scene = self._qpane.currentScene()
        movable = bool(
            scene is not None
            and any(
                layer.layer_id == self._target[1] and layer.interaction.movable
                for layer in scene.layers
            )
        )
        enabled = movable and transform is not None and bounds is not None
        self.setEnabled(enabled)
        if not enabled:
            self._status.setText("This layer does not expose editable geometry.")
            return
        self._show_target(transform, bounds)

    def _build_content(self) -> None:
        """Build position, scale, rotation, and explicit action controls."""
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._position_x = self._spin(-_POSITION_LIMIT, _POSITION_LIMIT, 2)
        self._position_y = self._spin(-_POSITION_LIMIT, _POSITION_LIMIT, 2)
        self._scale_x = self._spin(-_SCALE_LIMIT, _SCALE_LIMIT, 2)
        self._scale_y = self._spin(-_SCALE_LIMIT, _SCALE_LIMIT, 2)
        self._rotation = self._spin(-3600.0, 3600.0, 2)
        self._scale_x.setSuffix(" %")
        self._scale_y.setSuffix(" %")
        self._rotation.setSuffix("°")
        form.addRow("Position X", self._position_x)
        form.addRow("Position Y", self._position_y)
        form.addRow("Scale X", self._scale_x)
        form.addRow("Scale Y", self._scale_y)
        form.addRow("Rotation", self._rotation)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self._apply = QPushButton("Apply Transform", self)
        self._reset = QPushButton("Reset", self)
        actions.addWidget(self._apply)
        actions.addWidget(self._reset)
        layout.addLayout(actions)
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

    def _connect_signals(self) -> None:
        """Apply only explicit user actions and observe public state changes."""
        self._apply.clicked.connect(self._apply_transform)
        self._reset.clicked.connect(self._reset_transform)
        self._qpane.sceneChanged.connect(self.refresh)

    def _show_target(self, transform: QTransform, bounds: QRectF) -> None:
        """Decompose one affine value into approachable contextual controls."""
        scale_x = math.hypot(transform.m11(), transform.m12())
        determinant = transform.determinant()
        scale_y = determinant / scale_x if scale_x > 1e-12 else 0.0
        rotation = math.degrees(math.atan2(transform.m12(), transform.m11()))
        mapped = transform.mapRect(bounds)
        values = (
            (self._position_x, mapped.x()),
            (self._position_y, mapped.y()),
            (self._scale_x, scale_x * 100.0),
            (self._scale_y, scale_y * 100.0),
            (self._rotation, rotation),
        )
        for editor, value in values:
            editor.blockSignals(True)
            editor.setValue(value)
            editor.blockSignals(False)
        self._status.setText(
            "Transform edits are non-destructive and participate in scene undo."
        )

    def _apply_transform(self) -> None:
        """Build and submit one affine transform from the displayed values."""
        scale_x = self._scale_x.value() / 100.0
        scale_y = self._scale_y.value() / 100.0
        if abs(scale_x) <= 1e-9 or abs(scale_y) <= 1e-9:
            self._status.setText("Scale must be non-zero.")
            return
        radians = math.radians(self._rotation.value())
        cosine = math.cos(radians)
        sine = math.sin(radians)
        linear = QTransform(
            cosine * scale_x,
            sine * scale_x,
            -sine * scale_y,
            cosine * scale_y,
            0.0,
            0.0,
        )
        bounds = self._qpane.layerLocalBounds(*self._target)
        if bounds is None:
            self._status.setText("The selected layer does not expose local bounds.")
            return
        mapped = linear.mapRect(bounds)
        transform = QTransform(
            linear.m11(),
            linear.m12(),
            linear.m21(),
            linear.m22(),
            self._position_x.value() - mapped.x(),
            self._position_y.value() - mapped.y(),
        )
        changed = self._qpane.setLayerTransform(
            *self._target,
            transform,
        )
        self._status.setText(
            "Transform applied." if changed else "Transform is unchanged."
        )

    def _reset_transform(self) -> None:
        """Restore identity local-to-scene geometry for the selected layer."""
        changed = self._qpane.setLayerTransform(
            *self._target,
            QTransform(),
        )
        self._status.setText("Transform reset." if changed else "Already reset.")

    def _spin(
        self,
        minimum: float,
        maximum: float,
        decimals: int,
    ) -> QDoubleSpinBox:
        """Return one consistently configured numeric editor."""
        editor = QDoubleSpinBox(self)
        editor.setRange(minimum, maximum)
        editor.setDecimals(decimals)
        editor.setKeyboardTracking(False)
        return editor
