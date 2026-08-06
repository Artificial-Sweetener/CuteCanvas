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
"""Compact Clone Stamp options built entirely on CuteCanvas's public facade."""

from __future__ import annotations

from cutecanvas import (
    CloneStampAlignment,
    CloneStampSampleMode,
    CloneStampState,
    CloneStampTransform,
    CuteCanvas,
)
from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QPushButton,
    QToolBar,
)


class CloneStampControls(QObject):
    """Teach source sampling and alignment without owning editor state."""

    def __init__(
        self,
        canvas: CuteCanvas,
        toolbar: QToolBar,
        *,
        parent: QObject,
    ) -> None:
        """Build a contextual toolbar over the typed Clone Stamp facade."""
        super().__init__(parent)
        self._canvas = canvas
        self._toolbar = toolbar
        self._updating = False
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        label = QLabel(" Clone Stamp ", toolbar)
        label_action = toolbar.addWidget(label)
        self._sample_mode = QComboBox(toolbar)
        self._sample_mode.addItem(
            "Source layer",
            CloneStampSampleMode.ANCHORED_LAYER.value,
        )
        self._sample_mode.addItem(
            "Source and below",
            CloneStampSampleMode.ANCHORED_LAYER_AND_BELOW.value,
        )
        self._sample_mode.addItem(
            "Visible layers",
            CloneStampSampleMode.VISIBLE_COMPOSITE.value,
        )
        self._sample_mode.currentIndexChanged.connect(self._apply_sample_mode)
        sample_mode_action = toolbar.addWidget(self._sample_mode)
        self._aligned = QCheckBox("Aligned", toolbar)
        self._aligned.setToolTip("Keep the source offset when a new stroke begins.")
        self._aligned.toggled.connect(self._apply_alignment)
        aligned_action = toolbar.addWidget(self._aligned)
        rotation_label_action = toolbar.addWidget(QLabel(" Rotate ", toolbar))
        self._rotation = QDoubleSpinBox(toolbar)
        self._rotation.setRange(-360.0, 360.0)
        self._rotation.setDecimals(1)
        self._rotation.setSingleStep(5.0)
        self._rotation.setSuffix("°")
        self._rotation.setMaximumWidth(88)
        self._rotation.setToolTip("Rotate the cloned result around its source anchor.")
        self._rotation.valueChanged.connect(self._apply_transform)
        rotation_action = toolbar.addWidget(self._rotation)
        scale_label_action = toolbar.addWidget(QLabel(" Scale ", toolbar))
        self._scale = QDoubleSpinBox(toolbar)
        self._scale.setRange(1.0, 10000.0)
        self._scale.setDecimals(1)
        self._scale.setSingleStep(10.0)
        self._scale.setSuffix("%")
        self._scale.setMaximumWidth(94)
        self._scale.setToolTip("Scale the cloned result around its source anchor.")
        self._scale.valueChanged.connect(self._apply_transform)
        scale_action = toolbar.addWidget(self._scale)
        self._mirror_horizontal = QCheckBox("Flip H", toolbar)
        self._mirror_horizontal.setToolTip("Reflect cloned content horizontally.")
        self._mirror_horizontal.toggled.connect(self._apply_transform)
        mirror_horizontal_action = toolbar.addWidget(self._mirror_horizontal)
        self._mirror_vertical = QCheckBox("Flip V", toolbar)
        self._mirror_vertical.setToolTip("Reflect cloned content vertically.")
        self._mirror_vertical.toggled.connect(self._apply_transform)
        mirror_vertical_action = toolbar.addWidget(self._mirror_vertical)
        self._reset_transform = QPushButton("Reset", toolbar)
        self._reset_transform.setToolTip("Restore rotation, scale, and reflection.")
        self._reset_transform.clicked.connect(self._reset_sample_transform)
        reset_transform_action = toolbar.addWidget(self._reset_transform)
        self._source_status = QLabel(toolbar)
        source_status_action = toolbar.addWidget(self._source_status)
        self._actions = (
            label_action,
            sample_mode_action,
            aligned_action,
            rotation_label_action,
            rotation_action,
            scale_label_action,
            scale_action,
            mirror_horizontal_action,
            mirror_vertical_action,
            reset_transform_action,
            source_status_action,
        )
        canvas.cloneStampChanged.connect(self.refresh)
        canvas.compositionSelectionChanged.connect(self.refresh)
        canvas.selectedLayerChanged.connect(self.refresh)
        self.refresh()

    def sync_mode(self, mode: str) -> None:
        """Show these options only while the Clone Stamp tool is active."""
        visible = mode == CuteCanvas.CONTROL_MODE_CLONE_STAMP
        for action in self._actions:
            action.setVisible(visible)
        if visible:
            self.refresh()

    def refresh(self, *_args: object) -> None:
        """Mirror the complete immutable Clone Stamp state into the controls."""
        state = self._canvas.editor.clone_stamp.state
        self._updating = True
        try:
            self._sample_mode.setCurrentIndex(
                self._sample_mode.findData(state.sample_mode.value)
            )
            self._aligned.setChecked(state.alignment is CloneStampAlignment.ALIGNED)
            self._rotation.setValue(state.transform.rotation_degrees)
            self._scale.setValue(state.transform.scale_x * 100.0)
            self._mirror_horizontal.setChecked(state.transform.mirror_horizontal)
            self._mirror_vertical.setChecked(state.transform.mirror_vertical)
            self._present_source(state)
        finally:
            self._updating = False

    def _apply_sample_mode(self, _index: int) -> None:
        """Select the source product represented by the combo box."""
        if self._updating:
            return
        mode = self._sample_mode.currentData()
        if isinstance(mode, str):
            self._canvas.editor.clone_stamp.set_sample_mode(CloneStampSampleMode(mode))

    def _apply_alignment(self, checked: bool) -> None:
        """Choose whether successive strokes retain their source offset."""
        if self._updating:
            return
        alignment = (
            CloneStampAlignment.ALIGNED if checked else CloneStampAlignment.UNALIGNED
        )
        self._canvas.editor.clone_stamp.set_alignment(alignment)

    def _apply_transform(self, *_args: object) -> None:
        """Apply one coherent sampled-content transform from toolbar controls."""
        if self._updating:
            return
        scale = self._scale.value() / 100.0
        self._canvas.editor.clone_stamp.set_transform(
            CloneStampTransform(
                rotation_degrees=self._rotation.value(),
                scale_x=scale,
                scale_y=scale,
                mirror_horizontal=self._mirror_horizontal.isChecked(),
                mirror_vertical=self._mirror_vertical.isChecked(),
            )
        )

    def _reset_sample_transform(self) -> None:
        """Restore identity sampling without changing source or scope."""
        self._canvas.editor.clone_stamp.set_transform(CloneStampTransform())

    def _present_source(self, state: CloneStampState) -> None:
        """Explain the one remaining gesture without adding another button."""
        if state.source_set:
            self._source_status.setText("Source ready · Alt-click to replace")
            self._source_status.setToolTip(
                "The sampled-area outline follows the source while you paint."
            )
            return
        self._source_status.setText("Alt-click to choose a source")
        self._source_status.setToolTip(
            "Choose a rendered source on the selected layer."
        )
