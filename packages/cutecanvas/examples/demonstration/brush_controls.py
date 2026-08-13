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
"""Contextual public-API brush controls for the demonstration editor."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

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

from cutecanvas import (
    BrushDynamics,
    BrushPreset,
    CuteCanvas,
    LayerSnapshot,
    PaintTargetKind,
)


@dataclass(frozen=True, slots=True)
class _BrushContext:
    """Describe the active target's concise toolbar presentation."""

    target_text: str
    target_tooltip: str
    operation_text: str
    color_label: str | None = None
    color_tooltip: str | None = None
    color: QColor | None = None
    mask_id: uuid.UUID | None = None


class BrushControls(QObject):
    """Present one compact brush bar backed only by CuteCanvas's public facade."""

    def __init__(
        self, qpane: CuteCanvas, toolbar: QToolBar, *, parent: QObject
    ) -> None:
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
        self._target_name = QLabel(toolbar)
        toolbar.addWidget(self._target_name)
        self._preset = QComboBox(toolbar)
        for preset in _factory_presets():
            self._preset.addItem(preset.name, preset)
        self._preset.currentIndexChanged.connect(self._apply_factory_preset)
        toolbar.addWidget(self._preset)
        self._color = QPushButton("Color", toolbar)
        self._color.clicked.connect(self._choose_color)
        self._color_action = toolbar.addWidget(self._color)
        self._operation = QLabel(toolbar)
        toolbar.addWidget(self._operation)
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
        self._toolbar.setVisible(
            mode
            in {
                CuteCanvas.CONTROL_MODE_DRAW_BRUSH,
                CuteCanvas.CONTROL_MODE_CLONE_STAMP,
            }
        )
        if self._toolbar.isVisible():
            self.refresh()

    def refresh(self, *_args: object) -> None:
        """Refresh controls from detached public paint snapshots."""
        self._updating = True
        try:
            target = self._qpane.paintTargetState()
            kind = PaintTargetKind.LAYER if target is None else target.kind
            self._target.setCurrentIndex(self._target.findData(kind))
            self._target.setEnabled(
                self._qpane.getControlMode() != CuteCanvas.CONTROL_MODE_CLONE_STAMP
            )
            preset = self._qpane.brushPreset()
            self._size.setValue(round(preset.size))
            self._hardness.setValue(round(preset.hardness * 100.0))
            self._opacity.setValue(round(preset.opacity * 100.0))
            self._flow.setValue(round(preset.flow * 100.0))
            context = self._brush_context()
            self._target_name.setText(context.target_text)
            self._target_name.setToolTip(context.target_tooltip)
            self._operation.setText(context.operation_text)
            self._operation.setToolTip(context.operation_text)
            self._update_color_control(context)
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
        """Edit color or mask presentation according to the active target."""
        context = self._brush_context()
        if context.color is None:
            return
        if context.mask_id is None:
            color = QColorDialog.getColor(
                context.color,
                self._toolbar,
                "Paint Color",
                QColorDialog.ColorDialogOption.ShowAlphaChannel,
            )
            if color.isValid():
                self._qpane.setPaintColor(color)
                self.refresh()
            return
        color = QColorDialog.getColor(
            context.color,
            self._toolbar,
            "Mask Tint",
        )
        if color.isValid():
            self._qpane.setMaskProperties(context.mask_id, color=color)
            self.refresh()

    def _brush_context(self) -> _BrushContext:
        """Resolve exact target identity and its distinct color semantics."""
        target = self._qpane.paintTargetState()
        if target is None:
            selection = self._qpane.selectedLayer()
            layer = (
                None if selection is None else self._target_layer(selection.layer_id)
            )
            if layer is not None:
                label = self._layer_label(layer)
                operation = (
                    "Alt-click a source · Painting creates the layer"
                    if self._qpane.getControlMode()
                    == CuteCanvas.CONTROL_MODE_CLONE_STAMP
                    else "First stroke creates and selects the layer"
                )
                return _BrushContext(
                    target_text=f"New paint layer above: {label}",
                    target_tooltip=(
                        "The first stroke creates a real editable raster layer "
                        "above the selected layer."
                    ),
                    operation_text=operation,
                )
            return _BrushContext(
                target_text="No target",
                target_tooltip="Select an editable raster or mask layer.",
                operation_text="Select an editable layer",
            )
        if target.kind is PaintTargetKind.PIXEL_SELECTION:
            return _BrushContext(
                target_text="Editing: Pixel selection",
                target_tooltip="Composition-owned pixel selection coverage",
                operation_text="Add to selection · Alt subtracts",
            )
        layer = self._target_layer(target.layer_id)
        if layer is None:
            return _BrushContext(
                target_text="Unavailable target",
                target_tooltip="The selected paint layer is no longer available.",
                operation_text="Select another editable layer",
            )
        label = self._layer_label(layer)
        target_tooltip = f"{label} · {layer.source_kind} · {layer.layer_id}"
        if self._qpane.getControlMode() == CuteCanvas.CONTROL_MODE_CLONE_STAMP:
            return _BrushContext(
                target_text=f"Editing: {label}",
                target_tooltip=target_tooltip,
                operation_text="Clone pixels · Alt-click sets source",
            )
        if layer.source_kind == "raster":
            return _BrushContext(
                target_text=f"Editing: {label}",
                target_tooltip=target_tooltip,
                operation_text="Paint pixels · Alt erases",
                color_label="Paint",
                color_tooltip="Foreground color for strokes on this raster layer",
                color=self._qpane.paintColor(),
            )
        if layer.source_kind == "coverage" and layer.source_id is not None:
            return _BrushContext(
                target_text=f"Editing: {label}",
                target_tooltip=target_tooltip,
                operation_text="Add mask coverage · Alt erases",
                color_label="Mask tint",
                color_tooltip="Display tint for this mask; mask strokes edit coverage",
                color=QColor(layer.tint or QColor(255, 0, 0)),
                mask_id=layer.source_id,
            )
        return _BrushContext(
            target_text=f"Editing: {label}",
            target_tooltip=target_tooltip,
            operation_text="This layer does not accept brush strokes",
        )

    def _target_layer(self, layer_id: uuid.UUID | None) -> LayerSnapshot | None:
        """Return the active scene layer matching the paint target."""
        scene = self._qpane.currentScene()
        if scene is None or layer_id is None:
            return None
        return next(
            (layer for layer in scene.layers if layer.layer_id == layer_id),
            None,
        )

    @staticmethod
    def _layer_label(layer: LayerSnapshot) -> str:
        """Return a compact target label from public authoring metadata."""
        label = None if layer.label is None else layer.label.strip()
        if label:
            return label
        fallback = {
            "mask": "Mask",
            "raster": "Paint layer",
        }.get(layer.source_kind, layer.source_kind.replace("-", " ").title())
        return f"{fallback} {str(layer.layer_id)[:8]}"

    def _update_color_control(self, context: _BrushContext) -> None:
        """Present the active target's color role without conflating state owners."""
        color = context.color
        visible = color is not None and context.color_label is not None
        self._color_action.setVisible(visible)
        self._color.setVisible(visible)
        if not visible or color is None or context.color_label is None:
            self._color.setStyleSheet("")
            self._color.setToolTip("")
            return
        self._color.setText(context.color_label)
        self._color.setToolTip(context.color_tooltip or "")
        self._update_color_button(color)

    def _update_color_button(self, color: QColor) -> None:
        """Render the current paint color without introducing an icon dependency."""
        foreground = "#111" if color.lightnessF() > 0.55 else "#fff"
        self._color.setStyleSheet(
            "QPushButton {"
            f"background: rgba({color.red()}, {color.green()}, {color.blue()}, "
            f"{color.alpha()}); color: {foreground};"
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
