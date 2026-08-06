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
"""Abuse mixed mask tools, transient navigation, and chronological history."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pytest
from cutecanvas import CuteCanvas, PixelSelectionMode
from cutecanvas_test_support.harness.abuse_model import (
    HarnessPoint,
    PointerKind,
    StrokeAction,
)
from cutecanvas_test_support.harness.input_driver import QtStrokeDriver
from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness
from PySide6.QtCore import QEvent, QRectF, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit
from qpane.sdk.vector import VectorShapeKind
from shiboken6 import isValid


@pytest.fixture()
def harness(qapp: QApplication) -> Iterator[MountedQPaneHarness]:
    """Mount one production mask editor and dispose its asynchronous work."""
    mounted = MountedQPaneHarness(qapp, brush_size=30)
    try:
        yield mounted
    finally:
        mounted.close()


def _horizontal_stroke() -> StrokeAction:
    """Return a stroke crossing the center of the retained test shape."""
    return StrokeAction(
        PointerKind.MOUSE,
        (HarnessPoint(150, 200), HarnessPoint(250, 200)),
        30,
    )


def _mask_value(harness: MountedQPaneHarness, x: int, y: int) -> int:
    """Return evaluated active-mask coverage at one image coordinate."""
    image = harness.viewer.getActiveMaskImage()
    assert image is not None and not image.isNull()
    return image.pixelColor(x, y).red()


def test_shape_then_alt_brush_is_one_composited_mask_with_exact_history(
    harness: MountedQPaneHarness,
) -> None:
    """A subtractive brush stroke must erase retained shape coverage chronologically."""
    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    assert (
        viewer.addCoverageShape(
            VectorShapeKind.RECTANGLE,
            QRectF(100.0, 100.0, 200.0, 200.0),
            PixelSelectionMode.REPLACE,
        )
        is not None
    )
    assert _mask_value(harness, 200, 200) == 255
    assert viewer.getMaskUndoState(mask_id).undo_depth == 1

    viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
    viewer.setFocus()
    QTest.keyPress(viewer, Qt.Key.Key_Alt)
    driver = QtStrokeDriver(harness)
    stroke = _horizontal_stroke()
    driver.begin(stroke)
    driver.move(stroke, 1)
    driver.end(stroke)
    QTest.keyRelease(viewer, Qt.Key.Key_Alt)

    assert harness.wait_for_mask_undo_depth(mask_id, 2)
    assert _mask_value(harness, 200, 200) == 0
    assert _mask_value(harness, 120, 120) == 255

    QTest.keyClick(viewer, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    harness.drain_events()
    assert viewer.getMaskUndoState(mask_id).undo_depth == 1
    assert _mask_value(harness, 200, 200) == 255

    QTest.keyClick(viewer, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    harness.drain_events()
    assert viewer.getMaskUndoState(mask_id).undo_depth == 0
    assert _mask_value(harness, 120, 120) == 0

    QTest.keyClick(
        viewer,
        Qt.Key.Key_Z,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    harness.drain_events()
    assert viewer.getMaskUndoState(mask_id).undo_depth == 1
    assert _mask_value(harness, 120, 120) == 255


def test_generated_smart_selection_erasure_round_trips_retained_shape_history(
    harness: MountedQPaneHarness,
) -> None:
    """Generated mask results compose after shapes and undo as one edit."""
    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    assert (
        viewer.addCoverageShape(
            VectorShapeKind.RECTANGLE,
            QRectF(100.0, 100.0, 200.0, 200.0),
            PixelSelectionMode.ADD,
        )
        is not None
    )
    generated = np.zeros((400, 400), dtype=np.uint8)
    generated[180:221, 180:221] = 255

    viewer.mask_service.handleGeneratedMask(
        generated,
        np.array((180, 180, 220, 220), dtype=np.int32),
        erase_mode=True,
    )

    assert viewer.getMaskUndoState(mask_id).undo_depth == 2
    assert _mask_value(harness, 200, 200) == 0
    assert _mask_value(harness, 120, 120) == 255
    layer = viewer.mask_service.assets.get_layer(mask_id)
    assert layer is not None
    assert not layer.coverage.has_retained_items

    QTest.keyClick(viewer, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    harness.drain_events()
    assert viewer.getMaskUndoState(mask_id).undo_depth == 1
    assert _mask_value(harness, 200, 200) == 255
    assert layer.coverage.has_retained_items

    QTest.keyClick(
        viewer,
        Qt.Key.Key_Z,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    harness.drain_events()
    assert viewer.getMaskUndoState(mask_id).undo_depth == 2
    assert _mask_value(harness, 200, 200) == 0
    assert not layer.coverage.has_retained_items


def test_successive_generated_masks_use_semantic_history_equality(
    harness: MountedQPaneHarness,
) -> None:
    """Repeated SAM results must record, skip, and replay array-backed states."""
    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    first = np.zeros((400, 400), dtype=np.uint8)
    first[40:81, 40:81] = 255

    viewer.mask_service.handleGeneratedMask(
        first,
        np.array((40, 40, 80, 80), dtype=np.int32),
        erase_mode=False,
    )
    assert viewer.getMaskUndoState(mask_id).undo_depth == 1
    assert _mask_value(harness, 60, 60) == 255

    viewer.mask_service.handleGeneratedMask(
        first,
        np.array((40, 40, 80, 80), dtype=np.int32),
        erase_mode=False,
    )
    assert viewer.getMaskUndoState(mask_id).undo_depth == 1

    second = np.zeros((400, 400), dtype=np.uint8)
    second[180:221, 180:221] = 255
    viewer.mask_service.handleGeneratedMask(
        second,
        np.array((180, 180, 220, 220), dtype=np.int32),
        erase_mode=False,
    )
    assert viewer.getMaskUndoState(mask_id).undo_depth == 2
    assert _mask_value(harness, 60, 60) == 255
    assert _mask_value(harness, 200, 200) == 255

    assert viewer.undoSceneEdit()
    assert _mask_value(harness, 60, 60) == 255
    assert _mask_value(harness, 200, 200) == 0
    assert viewer.redoSceneEdit()
    assert _mask_value(harness, 200, 200) == 255


def test_cancelled_mixed_stroke_restores_exact_retained_state(
    harness: MountedQPaneHarness,
) -> None:
    """Escape after provisional worker work cannot flatten or alter the mask."""
    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    assert (
        viewer.addCoverageShape(
            VectorShapeKind.RECTANGLE,
            QRectF(100.0, 100.0, 200.0, 200.0),
            PixelSelectionMode.ADD,
        )
        is not None
    )
    viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
    viewer.setFocus()
    QTest.keyPress(viewer, Qt.Key.Key_Alt)
    driver = QtStrokeDriver(harness)
    stroke = _horizontal_stroke()
    driver.begin(stroke)
    driver.move(stroke, 1)
    QTest.keyClick(viewer, Qt.Key.Key_Escape)
    QTest.keyRelease(viewer, Qt.Key.Key_Alt)
    assert harness.wait_for_mask_render_idle()

    assert viewer.getMaskUndoState(mask_id).undo_depth == 1
    assert _mask_value(harness, 200, 200) == 255
    layer = viewer.mask_service.assets.get_layer(mask_id)
    assert layer is not None and layer.coverage.has_retained_items


def test_switching_masks_cancels_mixed_stroke_without_cross_layer_leakage(
    qapp: QApplication,
) -> None:
    """An erratic layer switch restores the source and leaves the target blank."""
    mounted = MountedQPaneHarness(qapp, mask_count=2, brush_size=30)
    try:
        viewer = mounted.viewer
        source_id, target_id = mounted.mask_ids
        assert (
            viewer.addCoverageShape(
                VectorShapeKind.RECTANGLE,
                QRectF(100.0, 100.0, 200.0, 200.0),
                PixelSelectionMode.ADD,
            )
            is not None
        )
        viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
        viewer.setFocus()
        QTest.keyPress(viewer, Qt.Key.Key_Alt)
        driver = QtStrokeDriver(mounted)
        stroke = _horizontal_stroke()
        driver.begin(stroke)
        driver.move(stroke, 1)

        mounted.activate_mask(1)
        QTest.keyRelease(viewer, Qt.Key.Key_Alt)
        assert mounted.wait_for_mask_render_idle()

        assert viewer.getMaskUndoState(source_id).undo_depth == 1
        assert viewer.getMaskUndoState(target_id).undo_depth == 0
        source = viewer.exportMaskImage(source_id)
        target = viewer.exportMaskImage(target_id)
        assert source is not None and source.pixelColor(200, 200).red() == 255
        assert target is not None and target.pixelColor(200, 200).red() == 0
        source_layer = viewer.mask_service.assets.get_layer(source_id)
        assert source_layer is not None and source_layer.coverage.has_retained_items
    finally:
        mounted.close()


def test_new_edit_after_undo_invalidates_mixed_tool_redo(
    harness: MountedQPaneHarness,
) -> None:
    """Chronology cannot replay an abandoned mixed-tool branch."""
    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    assert (
        viewer.addCoverageShape(
            VectorShapeKind.RECTANGLE,
            QRectF(100.0, 100.0, 200.0, 200.0),
            PixelSelectionMode.ADD,
        )
        is not None
    )
    viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
    viewer.setFocus()
    QTest.keyPress(viewer, Qt.Key.Key_Alt)
    driver = QtStrokeDriver(harness)
    stroke = _horizontal_stroke()
    driver.begin(stroke)
    driver.move(stroke, 1)
    driver.end(stroke)
    QTest.keyRelease(viewer, Qt.Key.Key_Alt)
    assert harness.wait_for_mask_undo_depth(mask_id, 2)

    QTest.keyClick(viewer, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    harness.drain_events()
    state = viewer.getMaskUndoState(mask_id)
    assert state.undo_depth == 1 and state.redo_depth == 1

    assert (
        viewer.addCoverageShape(
            VectorShapeKind.ELLIPSE,
            QRectF(20.0, 20.0, 40.0, 40.0),
            PixelSelectionMode.ADD,
        )
        is not None
    )
    state = viewer.getMaskUndoState(mask_id)
    assert state.undo_depth == 2 and state.redo_depth == 0


def test_space_navigation_preserves_new_selection_during_hostile_tool_changes(
    harness: MountedQPaneHarness,
) -> None:
    """Space owns only the effective mode while persistent selection keeps changing."""
    viewer = harness.viewer
    viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
    viewer.setFocus()

    QTest.keyPress(viewer, Qt.Key.Key_Space)
    assert viewer.getControlMode() == viewer.CONTROL_MODE_PANZOOM

    viewer.setControlMode(viewer.CONTROL_MODE_MASK_RECTANGLE)
    assert viewer.getControlMode() == viewer.CONTROL_MODE_PANZOOM

    QTest.keyRelease(viewer, Qt.Key.Key_Space)
    assert viewer.getControlMode() == viewer.CONTROL_MODE_MASK_RECTANGLE


def test_mask_shape_adds_to_brush_pixels_and_alt_shape_subtracts(
    harness: MountedQPaneHarness,
) -> None:
    """Mask geometry shares additive/subtractive algebra with raster tools."""
    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    driver = QtStrokeDriver(harness)
    seed = StrokeAction(
        PointerKind.MOUSE,
        (HarnessPoint(40, 40), HarnessPoint(60, 40)),
        30,
    )
    driver.begin(seed)
    driver.move(seed, 1)
    driver.end(seed)
    assert harness.wait_for_mask_undo_depth(mask_id, 1)

    viewer.setControlMode(viewer.CONTROL_MODE_MASK_RECTANGLE)
    QTest.mousePress(
        viewer, Qt.MouseButton.LeftButton, pos=HarnessPoint(100, 100).to_qpoint()
    )
    QTest.mouseMove(viewer, HarnessPoint(300, 300).to_qpoint(), delay=1)
    QTest.mouseRelease(
        viewer,
        Qt.MouseButton.LeftButton,
        pos=HarnessPoint(300, 300).to_qpoint(),
    )
    harness.drain_events()
    assert viewer.getMaskUndoState(mask_id).undo_depth == 2
    assert _mask_value(harness, 50, 40) == 255
    assert _mask_value(harness, 200, 200) == 255

    viewer.setFocus()
    QTest.keyPress(viewer, Qt.Key.Key_Alt)
    QTest.mousePress(
        viewer, Qt.MouseButton.LeftButton, pos=HarnessPoint(180, 180).to_qpoint()
    )
    QTest.mouseMove(viewer, HarnessPoint(220, 220).to_qpoint(), delay=1)
    QTest.mouseRelease(
        viewer,
        Qt.MouseButton.LeftButton,
        pos=HarnessPoint(220, 220).to_qpoint(),
    )
    QTest.keyRelease(viewer, Qt.Key.Key_Alt)
    harness.drain_events()
    assert viewer.getMaskUndoState(mask_id).undo_depth == 3
    assert _mask_value(harness, 200, 200) == 0
    assert _mask_value(harness, 50, 40) == 255


def test_first_shape_use_recovers_alt_from_the_pointer_snapshot(
    harness: MountedQPaneHarness,
) -> None:
    """The first gesture must erase even when activation missed the Alt key press."""

    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    assert (
        viewer.addCoverageShape(
            VectorShapeKind.RECTANGLE,
            QRectF(100.0, 100.0, 200.0, 200.0),
            PixelSelectionMode.ADD,
        )
        is not None
    )
    viewer.setControlMode(viewer.CONTROL_MODE_MASK_RECTANGLE)

    QTest.mousePress(
        viewer,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.AltModifier,
        HarnessPoint(180, 180).to_qpoint(),
    )
    QTest.mouseMove(viewer, HarnessPoint(220, 220).to_qpoint(), delay=1)
    QTest.mouseRelease(
        viewer,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.AltModifier,
        HarnessPoint(220, 220).to_qpoint(),
    )
    harness.drain_events()

    assert viewer.getMaskUndoState(mask_id).undo_depth == 2
    assert _mask_value(harness, 200, 200) == 0
    assert _mask_value(harness, 170, 170) == 255


@pytest.mark.parametrize(
    "mode_name",
    (
        "CONTROL_MODE_MASK_RECTANGLE",
        "CONTROL_MODE_MASK_ELLIPSE",
        "CONTROL_MODE_MASK_LASSO",
        "CONTROL_MODE_PAINT_BUCKET",
        "CONTROL_MODE_DRAW_BRUSH",
    ),
)
def test_alt_mask_tools_show_and_clear_a_subtractive_cursor_indicator(
    harness: MountedQPaneHarness,
    mode_name: str,
) -> None:
    """Every subtractive Input tool should expose immediate reversible feedback."""

    viewer = harness.viewer
    viewer.setControlMode(getattr(viewer, mode_name))
    viewer.setFocus()
    viewer.refreshCursor()
    harness.drain_events()
    additive = viewer.cursor()

    QTest.keyPress(viewer, Qt.Key.Key_Alt)
    harness.drain_events()
    subtractive = viewer.cursor()

    assert additive.shape() is Qt.CursorShape.BitmapCursor
    assert subtractive.shape() is Qt.CursorShape.BitmapCursor
    assert subtractive.hotSpot() == additive.hotSpot()
    assert subtractive.pixmap().cacheKey() != additive.pixmap().cacheKey()

    QTest.keyRelease(viewer, Qt.Key.Key_Alt)
    harness.drain_events()
    restored = viewer.cursor()
    assert restored.pixmap().cacheKey() == additive.pixmap().cacheKey()


def test_explicit_eraser_cursor_and_mode_ignore_alt(
    harness: MountedQPaneHarness,
) -> None:
    """Explicit erasure must not acquire brush inversion feedback under Alt."""

    viewer = harness.viewer
    viewer.setControlMode(viewer.CONTROL_MODE_ERASER)
    viewer.setFocus()
    viewer.refreshCursor()
    harness.drain_events()
    ordinary = viewer.cursor()

    QTest.keyPress(viewer, Qt.Key.Key_Alt)
    harness.drain_events()
    with_alt = viewer.cursor()

    assert viewer.getControlMode() == viewer.CONTROL_MODE_ERASER
    assert with_alt.shape() == ordinary.shape()
    assert with_alt.hotSpot() == ordinary.hotSpot()
    assert with_alt.pixmap().cacheKey() == ordinary.pixmap().cacheKey()

    QTest.keyRelease(viewer, Qt.Key.Key_Alt)


def test_alt_held_before_tool_activation_applies_to_cursor_and_first_shape(
    harness: MountedQPaneHarness,
) -> None:
    """Activation must project an already-held subtractive state immediately."""

    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    assert (
        viewer.addCoverageShape(
            VectorShapeKind.RECTANGLE,
            QRectF(100.0, 100.0, 200.0, 200.0),
            PixelSelectionMode.ADD,
        )
        is not None
    )
    viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
    viewer.setFocus()
    QTest.keyPress(viewer, Qt.Key.Key_Alt)

    viewer.setControlMode(viewer.CONTROL_MODE_MASK_ELLIPSE)
    harness.drain_events()
    assert viewer.cursor().shape() is Qt.CursorShape.BitmapCursor
    additive_cursor = viewer.cursor_builder.create_precision_cursor(False)
    assert viewer.cursor().pixmap().cacheKey() != additive_cursor.pixmap().cacheKey()

    QTest.mousePress(
        viewer,
        Qt.MouseButton.LeftButton,
        pos=HarnessPoint(180, 180).to_qpoint(),
    )
    QTest.mouseMove(viewer, HarnessPoint(220, 220).to_qpoint(), delay=1)
    QTest.mouseRelease(
        viewer,
        Qt.MouseButton.LeftButton,
        pos=HarnessPoint(220, 220).to_qpoint(),
    )
    QTest.keyRelease(viewer, Qt.Key.Key_Alt)
    harness.drain_events()

    assert viewer.getMaskUndoState(mask_id).undo_depth == 2
    assert _mask_value(harness, 200, 200) == 0
    assert _mask_value(harness, 170, 170) == 255


def test_hiding_canvas_clears_transient_space_and_alt_state(
    harness: MountedQPaneHarness,
) -> None:
    """Lifecycle loss must restore selection and prevent sticky subtraction."""
    viewer = harness.viewer
    viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
    viewer.setFocus()
    QTest.keyPress(viewer, Qt.Key.Key_Alt)
    QTest.keyPress(viewer, Qt.Key.Key_Space)
    assert viewer.getControlMode() == viewer.CONTROL_MODE_PANZOOM

    viewer.hide()
    harness.drain_events()
    viewer.show()
    harness.drain_events()

    assert viewer.getControlMode() == viewer.CONTROL_MODE_DRAW_BRUSH
    driver = QtStrokeDriver(harness)
    stroke = _horizontal_stroke()
    driver.begin(stroke)
    driver.move(stroke, 1)
    driver.end(stroke)
    assert harness.wait_for_mask_undo_depth(harness.mask_ids[0], 1)
    assert _mask_value(harness, 200, 200) == 255


def test_focus_loss_clears_transient_navigation_and_subtraction(
    harness: MountedQPaneHarness,
) -> None:
    """A sibling focus target cannot leave editor modifiers sticky."""
    viewer = harness.viewer
    viewer.setControlMode(viewer.CONTROL_MODE_MASK_ELLIPSE)
    viewer.setFocus()
    QTest.keyPress(viewer, Qt.Key.Key_Alt)
    QTest.keyPress(viewer, Qt.Key.Key_Space)
    assert viewer.getControlMode() == viewer.CONTROL_MODE_PANZOOM
    sibling = QLineEdit(harness.host)
    sibling.show()
    sibling.setFocus()
    harness.drain_events()
    try:
        assert viewer.getControlMode() == viewer.CONTROL_MODE_MASK_ELLIPSE
        assert not viewer.interaction.alt_key_held
        assert not viewer.interaction.shift_key_held
    finally:
        sibling.close()
        sibling.deleteLater()
        harness.drain_events()


def test_teardown_while_modifiers_are_held_detaches_input_observers(
    qapp: QApplication,
) -> None:
    """Destroying an active canvas cannot leave callbacks into deleted Qt state."""
    viewer = CuteCanvas(features=("mask",))
    sibling = QLineEdit()
    try:
        composition_id = viewer.createComposition(
            QRectF(0.0, 0.0, 64.0, 64.0),
            title="Teardown",
        )
        viewer.openComposition(composition_id)
        assert viewer.createBlankMask(QSize(64, 64)) is not None
        viewer.show()
        viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
        viewer.setFocus()
        QTest.keyPress(viewer, Qt.Key.Key_Alt)
        QTest.keyPress(viewer, Qt.Key.Key_Space)
        assert viewer.getControlMode() == viewer.CONTROL_MODE_PANZOOM

        viewer.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        assert not isValid(viewer)

        sibling.show()
        sibling.setFocus()
        qapp.processEvents()
    finally:
        sibling.close()
        sibling.deleteLater()
        qapp.processEvents()
