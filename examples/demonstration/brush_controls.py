#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Contextual public-API brush controls for the demonstration editor."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QToolBar,
)

from qpane import BrushDynamics, BrushPreset, PaintTargetKind, QPane


class BrushControls(QObject):
    """Present one compact brush bar backed only by QPane's public facade."""

    def __init__(self, qpane: QPane, toolbar: QToolBar, *, parent: QObject) -> None:
        """Build target, preset, color, and scalar brush controls."""
        super().__init__(parent)
        self._qpane = qpane
        self._toolbar = toolbar
        self._updating = False
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        toolbar.addWidget(QLabel(" Brush ", toolbar))
        self._target = QComboBox(toolbar)
        self._target.addItem("Active layer", PaintTargetKind.LAYER)
        self._target.addItem("Pixel selection", PaintTargetKind.PIXEL_SELECTION)
        self._target.currentIndexChanged.connect(self._apply_target)
        toolbar.addWidget(self._target)
        self._preset = QComboBox(toolbar)
        for preset in _factory_presets():
            self._preset.addItem(preset.name, preset)
        self._preset.currentIndexChanged.connect(self._apply_factory_preset)
        toolbar.addWidget(self._preset)
        self._color = QPushButton("Color", toolbar)
        self._color.clicked.connect(self._choose_color)
        toolbar.addWidget(self._color)
        self._size = self._scalar("Size", 1, 2000, " px")
        self._hardness = self._scalar("Hardness", 0, 100, "%")
        self._opacity = self._scalar("Opacity", 0, 100, "%")
        self._flow = self._scalar("Flow", 1, 100, "%")
        qpane.paintTargetChanged.connect(self.refresh)
        qpane.brushPresetChanged.connect(self.refresh)
        qpane.paintColorChanged.connect(self.refresh)
        qpane.selectedLayerChanged.connect(self.refresh)
        qpane.sceneChanged.connect(self.refresh)
        self.refresh()

    def sync_mode(self, mode: str) -> None:
        """Show the contextual bar only while the shared brush tool is active."""
        self._toolbar.setVisible(mode == QPane.CONTROL_MODE_DRAW_BRUSH)
        if self._toolbar.isVisible():
            self.refresh()

    def refresh(self, *_args: object) -> None:
        """Refresh controls from detached public paint snapshots."""
        self._updating = True
        try:
            target = self._qpane.paintTargetState()
            kind = PaintTargetKind.LAYER if target is None else target.kind
            self._target.setCurrentIndex(self._target.findData(kind))
            preset = self._qpane.brushPreset()
            self._size.setValue(round(preset.size))
            self._hardness.setValue(round(preset.hardness * 100.0))
            self._opacity.setValue(round(preset.opacity * 100.0))
            self._flow.setValue(round(preset.flow * 100.0))
            color_target = target is not None and target.source_kind == "raster"
            self._color.setVisible(color_target)
            self._update_color_button(self._qpane.paintColor())
        finally:
            self._updating = False

    def _scalar(
        self,
        label: str,
        minimum: int,
        maximum: int,
        suffix: str,
    ) -> QSpinBox:
        """Add one labeled compact scalar editor."""
        self._toolbar.addWidget(QLabel(f" {label} ", self._toolbar))
        editor = QSpinBox(self._toolbar)
        editor.setRange(minimum, maximum)
        editor.setSuffix(suffix)
        editor.valueChanged.connect(self._apply_scalars)
        self._toolbar.addWidget(editor)
        return editor

    def _apply_target(self, _index: int) -> None:
        """Route the brush to the selected layer or composition selection."""
        if self._updating:
            return
        kind = PaintTargetKind(self._target.currentData())
        if kind is PaintTargetKind.PIXEL_SELECTION:
            self._qpane.setPixelSelectionPaintTarget()
            return
        scene = self._qpane.currentScene()
        selected = self._qpane.selectedLayer()
        if scene is not None and selected is not None:
            self._qpane.setPaintTarget(scene.scene_id, selected.layer_id)

    def _apply_factory_preset(self, _index: int) -> None:
        """Install a complete immutable factory preset."""
        if self._updating:
            return
        preset = self._preset.currentData()
        if isinstance(preset, BrushPreset):
            self._qpane.setBrushPreset(preset)

    def _apply_scalars(self, _value: int) -> None:
        """Replace scalar fields while retaining dynamics and preset identity."""
        if self._updating:
            return
        preset = replace(
            self._qpane.brushPreset(),
            size=float(self._size.value()),
            hardness=self._hardness.value() / 100.0,
            opacity=self._opacity.value() / 100.0,
            flow=self._flow.value() / 100.0,
        )
        self._qpane.setBrushPreset(preset)

    def _choose_color(self) -> None:
        """Choose a detached color for editable RGBA targets."""
        color = QColorDialog.getColor(
            self._qpane.paintColor(),
            self._toolbar,
            "Paint Color",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if color.isValid():
            self._qpane.setPaintColor(color)

    def _update_color_button(self, color: QColor) -> None:
        """Render the current paint color without introducing an icon dependency."""
        foreground = "#111" if color.lightnessF() > 0.55 else "#fff"
        self._color.setStyleSheet(
            "QPushButton {"
            f"background: {color.name(QColor.NameFormat.HexArgb)}; color: {foreground};"
            "padding: 3px 10px;"
            "}"
        )


def _factory_presets() -> tuple[BrushPreset, ...]:
    """Return the concise factory set demonstrated by the editor toolbar."""
    return (
        BrushPreset(name="Basic", size=20.0),
        BrushPreset(name="Soft", size=40.0, hardness=0.15),
        BrushPreset(name="Airbrush", size=80.0, hardness=0.05, flow=0.12),
        BrushPreset(
            name="Scatter",
            size=28.0,
            hardness=0.7,
            spacing=0.35,
            texture_strength=0.55,
            texture_scale=5.0,
            texture_seed=17,
            dynamics=BrushDynamics(
                pressure_size=1.0,
                position_jitter=0.65,
                size_jitter=0.35,
            ),
        ),
    )
