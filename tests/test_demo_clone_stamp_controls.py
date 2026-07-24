#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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
"""Mounted public-facade coverage for the demo's Clone Stamp options."""

from __future__ import annotations

from cutecanvas import (
    CloneStampAlignment,
    CloneStampSampleMode,
    CloneStampTransform,
    CuteCanvas,
)
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QToolBar

from examples.cutecanvas_demo import ExampleOptions, ExampleWindow
from examples.demonstration.brush_controls import BrushControls
from examples.demonstration.clone_stamp_controls import CloneStampControls


def test_clone_stamp_action_selects_tool_before_a_raster_target_exists(qapp) -> None:
    """Clicking the demo action must not leave the previous navigation tool active."""
    window = ExampleWindow(ExampleOptions(feature_set="core"))
    try:
        window.tools.set_mode(CuteCanvas.CONTROL_MODE_PANZOOM)
        assert window.qpane.getControlMode() == CuteCanvas.CONTROL_MODE_PANZOOM

        window.tools.mode_clone_stamp_action.trigger()
        qapp.processEvents()

        assert window.qpane.getControlMode() == CuteCanvas.CONTROL_MODE_CLONE_STAMP
        assert window.tools.mode_clone_stamp_action.isChecked()
        assert not window.tools.mode_pan_action.isChecked()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_clone_stamp_demo_action_sets_persistent_source_and_paints(qapp) -> None:
    """The mounted demo action should drive the complete source-to-destination workflow."""
    window = ExampleWindow(ExampleOptions(feature_set="core"))
    try:
        window.resize(1000, 760)
        window.show()
        window.qpane.createComposition(QRectF(0.0, 0.0, 320.0, 240.0))
        pixels = QImage(320, 240, QImage.Format.Format_ARGB32_Premultiplied)
        pixels.fill(Qt.GlobalColor.transparent)
        source_color = QColor(25, 135, 225, 255)
        painter = QPainter(pixels)
        painter.fillRect(0, 0, 120, 240, source_color)
        painter.end()
        layer_id = window.qpane.addEditableRasterLayer(pixels, label="Clone target")
        scene = window.qpane.currentScene()
        assert scene is not None and layer_id is not None
        assert window.qpane.setSelectedLayer(scene.scene_id, layer_id)
        window.qpane.setZoomFit()
        qapp.processEvents()

        window.tools.mode_clone_stamp_action.trigger()
        qapp.processEvents()
        source_scene = QPointF(60.0, 120.0)
        destination_scene = QPointF(240.0, 120.0)
        source_panel = window.qpane.view().scene_to_panel_point(source_scene)
        destination_panel = window.qpane.view().scene_to_panel_point(destination_scene)
        assert source_panel is not None and destination_panel is not None

        QTest.mouseClick(
            window.qpane,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.AltModifier,
            source_panel.toPoint(),
        )
        qapp.processEvents()
        anchored = window.qpane.cloneStampState()
        assert anchored.source_set
        assert anchored.source is not None
        anchored_scene = anchored.source.scene_point()
        assert abs(anchored_scene.x() - source_scene.x()) < 0.5
        assert abs(anchored_scene.y() - source_scene.y()) < 0.5

        QTest.mouseClick(
            window.qpane,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            destination_panel.toPoint(),
        )
        qapp.processEvents()

        painted = window.qpane.editableRasterLayerImage(scene.scene_id, layer_id)
        assert painted is not None
        assert painted.pixelColor(240, 120) == source_color
        assert window.qpane.cloneStampState().source == anchored.source
        assert window.qpane.getControlMode() == CuteCanvas.CONTROL_MODE_CLONE_STAMP
        assert window.qpane.undoSceneEdit()
        restored = window.qpane.editableRasterLayerImage(scene.scene_id, layer_id)
        assert restored is not None
        assert restored.pixelColor(240, 120).alpha() == 0
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_clone_stamp_options_share_the_brush_bar_and_public_state(qapp) -> None:
    """The demo should expose clone options without duplicating editor state."""
    canvas = CuteCanvas()
    toolbar = QToolBar()
    toolbar.resize(2200, 48)
    brush_controls = BrushControls(canvas, toolbar, parent=toolbar)
    clone_controls = CloneStampControls(canvas, toolbar, parent=toolbar)
    try:
        base = QImage(320, 240, QImage.Format_ARGB32_Premultiplied)
        base.fill(QColor(30, 50, 80, 255))
        canvas.createCompositionFromImage(base, title="Clone controls")
        layer_id = canvas.createPaintLayer(QSize(120, 80), label="Retouch")
        assert layer_id is not None
        canvas.editor.clone_stamp.activate()
        brush_controls.sync_mode(CuteCanvas.CONTROL_MODE_CLONE_STAMP)
        clone_controls.sync_mode(CuteCanvas.CONTROL_MODE_CLONE_STAMP)
        toolbar.show()
        qapp.processEvents()

        assert toolbar.isVisible()
        assert brush_controls._target_name.text() == "Editing: Retouch"
        assert brush_controls._operation.text() == (
            "Clone pixels · Alt-click sets source"
        )
        assert not brush_controls._target.isEnabled()
        assert brush_controls._color.isHidden()
        assert clone_controls._source_status.text() == ("Alt-click to choose a source")

        clone_controls._aligned.setChecked(False)
        clone_controls._sample_mode.setCurrentIndex(
            clone_controls._sample_mode.findData(
                CloneStampSampleMode.VISIBLE_COMPOSITE.value
            )
        )
        assert canvas.editor.clone_stamp.state.alignment is (
            CloneStampAlignment.UNALIGNED
        )
        assert canvas.editor.clone_stamp.state.sample_mode is (
            CloneStampSampleMode.VISIBLE_COMPOSITE
        )
        clone_controls._rotation.setValue(37.5)
        clone_controls._scale.setValue(150.0)
        clone_controls._mirror_horizontal.setChecked(True)
        assert canvas.editor.clone_stamp.state.transform == CloneStampTransform(
            rotation_degrees=37.5,
            scale_x=1.5,
            scale_y=1.5,
            mirror_horizontal=True,
        )
        clone_controls._reset_transform.click()
        assert canvas.editor.clone_stamp.state.transform == CloneStampTransform()
        assert canvas.editor.clone_stamp.set_source(QPointF(12.0, 18.0))
        qapp.processEvents()
        assert clone_controls._source_status.text() == (
            "Source ready · Alt-click to replace"
        )
    finally:
        toolbar.close()
        canvas.close()
        toolbar.deleteLater()
        canvas.deleteLater()
        qapp.processEvents()
