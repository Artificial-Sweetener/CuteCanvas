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
"""Mounted public-API coverage for the demo's contextual brush bar."""

from __future__ import annotations

from cutecanvas import CuteCanvas
from demonstration.brush_controls import BrushControls
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QColorDialog, QToolBar


def test_brush_bar_distinguishes_raster_mask_and_selection_color_semantics(
    qapp, monkeypatch
) -> None:
    """Each real paint target should expose its exact identity and valid actions."""
    canvas = CuteCanvas(features=("mask",))
    toolbar = QToolBar()
    toolbar.resize(1800, 48)
    controls = BrushControls(canvas, toolbar, parent=toolbar)
    try:
        base = QImage(320, 240, QImage.Format_ARGB32_Premultiplied)
        base.fill(QColor(30, 50, 80, 255))
        canvas.createCompositionFromImage(base, title="Brush controls")
        raster_layer_id = canvas.createPaintLayer(QSize(80, 60), label="Ink")
        assert raster_layer_id is not None
        controls.sync_mode(CuteCanvas.CONTROL_MODE_DRAW_BRUSH)
        toolbar.show()
        qapp.processEvents()

        assert controls._target_name.text() == "Editing: Ink"
        assert controls._operation.text() == "Paint pixels · Alt erases"
        assert controls._color.text() == "Paint"
        assert not controls._color.isHidden()

        paint_color = QColor(25, 145, 235, 190)
        monkeypatch.setattr(
            QColorDialog,
            "getColor",
            staticmethod(lambda *_args, **_kwargs: QColor(paint_color)),
        )
        controls._choose_color()
        assert canvas.paintColor() == paint_color
        assert "rgba(25, 145, 235, 190)" in controls._color.styleSheet()

        mask_id = canvas.createBlankMask(QSize(320, 240))
        assert mask_id is not None
        assert canvas.setActiveMaskID(mask_id)
        controls.refresh()
        assert controls._target_name.text().startswith("Editing: Mask")
        assert controls._operation.text() == "Add mask coverage · Alt erases"
        assert controls._color.text() == "Mask tint"
        assert not controls._color.isHidden()

        mask_tint = QColor(220, 65, 135)
        monkeypatch.setattr(
            QColorDialog,
            "getColor",
            staticmethod(lambda *_args, **_kwargs: QColor(mask_tint)),
        )
        controls._choose_color()
        scene = canvas.currentScene()
        assert scene is not None
        mask_layer = next(layer for layer in scene.layers if layer.source_id == mask_id)
        assert mask_layer.tint == mask_tint
        assert canvas.paintColor() == paint_color
        assert "rgba(220, 65, 135, 255)" in controls._color.styleSheet()

        assert canvas.setPixelSelectionPaintTarget()
        controls.refresh()
        assert controls._target_name.text() == "Editing: Pixel selection"
        assert controls._operation.text() == "Add to selection · Alt subtracts"
        assert controls._color.isHidden()

        assert canvas.setPaintTarget(scene.scene_id, raster_layer_id)
        controls.refresh()
        assert controls._target_name.text() == "Editing: Ink"
        assert controls._color.text() == "Paint"
    finally:
        toolbar.close()
        canvas.close()
        toolbar.deleteLater()
        canvas.deleteLater()
        qapp.processEvents()


def test_active_mask_tint_change_refreshes_brush_feedback(qapp, monkeypatch) -> None:
    """Changing an active mask tint should immediately rebuild its brush cursor."""
    canvas = CuteCanvas(features=("mask",))
    try:
        base = QImage(64, 48, QImage.Format_ARGB32_Premultiplied)
        base.fill(QColor("white"))
        canvas.createCompositionFromImage(base, title="Mask tint")
        mask_id = canvas.createBlankMask(base.size())
        assert mask_id is not None
        assert canvas.setActiveMaskID(mask_id)
        refreshes: list[None] = []
        monkeypatch.setattr(canvas, "refreshCursor", lambda: refreshes.append(None))

        assert canvas.setMaskProperties(mask_id, color=QColor(15, 180, 90))
        assert refreshes == [None]
    finally:
        canvas.close()
        canvas.deleteLater()
        qapp.processEvents()
