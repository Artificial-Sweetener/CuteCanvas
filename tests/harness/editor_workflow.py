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
"""Mounted editor workflow and performance invariants for the abuse harness."""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from cutecanvas import LayerPolicy, RasterExtentPolicy
from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from qpane.raster.image_conversion import (
    qimage_to_numpy_argb32,
    qimage_to_numpy_grayscale8,
)

from .mounted_qpane import MountedQPaneHarness
from .timing import interaction_clock

_MAX_SYNCHRONOUS_EDITOR_LATENCY_MS = 100.0


@dataclass(frozen=True, slots=True)
class EditorWorkflowResult:
    """Report terminal workflow status and worst synchronous latency."""

    succeeded: bool
    max_latency_ms: float
    phase: str = ""
    message: str = ""


class MountedEditorWorkflow:
    """Exercise public editor behavior against a shown production CuteCanvas."""

    def __init__(self, harness: MountedQPaneHarness) -> None:
        """Bind the mounted pane and its real Qt event loop."""
        self._harness = harness
        self._viewer = harness.viewer
        self._max_latency_ms = 0.0

    def run(self) -> EditorWorkflowResult:
        """Run selection, ants, RGBA, bounds, and history proof as one slice."""
        try:
            self._exercise_shape_selection_and_ants()
            self._exercise_selection_constrained_mask_stroke()
            self._exercise_rgba_editing_and_bounds()
        except _EditorWorkflowFailure as failure:
            return EditorWorkflowResult(
                False,
                self._max_latency_ms,
                failure.phase,
                failure.message,
            )
        return EditorWorkflowResult(True, self._max_latency_ms)

    def _exercise_shape_selection_and_ants(self) -> None:
        """Require immediate rectangle commit and boundary-only timer changes."""
        viewer = self._viewer
        width = viewer.width()
        height = viewer.height()
        start = QPoint(max(12, width // 5), max(12, height // 5))
        end = QPoint(
            max(start.x() + 24, width * 3 // 5), max(start.y() + 24, height * 3 // 5)
        )
        viewer.setControlMode(viewer.CONTROL_MODE_SELECT_RECTANGLE)
        started = interaction_clock()
        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(viewer, end, delay=1)
        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, end)
        self._harness.drain_events()
        self._record_latency(started, "selection-commit")
        state = viewer.pixelSelectionState()
        if state is None or not state.has_selection or state.bounds is None:
            self._fail("selection-commit", "Rectangle gesture did not create coverage")

        first = self._harness.capture()
        self._harness.drain_events(wait_ms=120)
        second = self._harness.capture()
        difference = np.any(
            qimage_to_numpy_argb32(first) != qimage_to_numpy_argb32(second),
            axis=2,
        )
        changed = int(np.count_nonzero(difference))
        perimeter = 2 * ((end.x() - start.x()) + (end.y() - start.y()))
        if changed == 0:
            self._fail("marching-ants", "Selection phase did not animate")
        if changed > max(512, perimeter * 12):
            self._fail(
                "marching-ants",
                f"Selection animation invalidated {changed} pixels beyond its boundary budget",
            )
        center = QPoint((start.x() + end.x()) // 2, (start.y() + end.y()) // 2)
        if difference[center.y(), center.x()]:
            self._fail("marching-ants", "Selection animation changed interior pixels")

    def _exercise_selection_constrained_mask_stroke(self) -> None:
        """Require live and durable mask paint to remain inside selection."""
        viewer = self._viewer
        mask_id = viewer.activeMaskID()
        if mask_id is None:
            self._fail("mask-constraint", "Mounted pane has no active mask")
        y = viewer.height() * 2 // 5
        outside = QPoint(max(8, viewer.width() // 8), y)
        inside = QPoint(viewer.width() * 2 // 5, y)
        end = QPoint(viewer.width() * 7 // 8, y)
        viewer.setBrushSize(160)
        viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, outside)
        QTest.mouseMove(viewer, end, delay=1)
        self._harness.drain_events()
        preview = self._harness.capture()
        if not self._harness.is_mask_tint(preview.pixelColor(inside)):
            self._fail("mask-constraint-preview", "Selected mask paint did not preview")
        if not self._harness.is_background(preview.pixelColor(outside)):
            self._fail(
                "mask-constraint-preview",
                "Mask paint preview escaped active pixel selection",
            )
        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, end)
        if not self._harness.wait_for_mask_undo_depth(mask_id, 1):
            self._fail(
                "mask-constraint-commit", "Constrained mask stroke did not commit"
            )
        if not self._harness.wait_for_mask_render_idle():
            self._fail(
                "mask-constraint-commit", "Constrained mask render did not settle"
            )
        durable = self._harness.capture()
        if not self._harness.is_mask_tint(durable.pixelColor(inside)):
            self._fail("mask-constraint-commit", "Selected mask paint was not durable")
        if not self._harness.is_background(durable.pixelColor(outside)):
            self._fail(
                "mask-constraint-commit",
                "Durable mask paint escaped active pixel selection",
            )
        self._exercise_selected_mask_pixel_movement(inside)
        if not viewer.undoSceneEdit():
            self._fail(
                "mask-constraint-undo", "Constrained mask stroke was not undoable"
            )
        if self._harness.wait_for_background(inside).latency_ms is None:
            self._fail("mask-constraint-undo", "Mask undo did not restore background")

        if not viewer.clearPixelSelection():
            self._fail("selection-clear", "Public deselect rejected active coverage")
        cleared = self._harness.capture()
        self._harness.drain_events(wait_ms=120)
        stable = self._harness.capture()
        if not np.array_equal(
            qimage_to_numpy_argb32(cleared),
            qimage_to_numpy_argb32(stable),
        ):
            self._fail("selection-clear", "Deselect did not restore a stable frame")

    def _exercise_selected_mask_pixel_movement(self, origin: QPoint) -> None:
        """Require live, durable, and atomic movement of selected mask pixels."""
        viewer = self._viewer
        scene = viewer.currentScene()
        active_mask_id = viewer.activeMaskID()
        mask_layer = (
            None
            if scene is None
            else next(
                (
                    layer
                    for layer in scene.layers
                    if layer.source_kind == "coverage"
                    and layer.source_id == active_mask_id
                ),
                None,
            )
        )
        editable_policy = LayerPolicy(
            selectable=True,
            movable=True,
            pixel_editable=True,
        )
        if scene is None or mask_layer is None:
            self._fail("pixel-move-setup", "Active mask could not become editable")
        viewer.setLayerInteractionPolicy(
            scene.scene_id,
            mask_layer.layer_id,
            editable_policy,
        )
        viewer.setSelectedLayer(scene.scene_id, mask_layer.layer_id)
        selected = viewer.selectedLayer()
        if selected is None or selected.layer_id != mask_layer.layer_id:
            self._fail("pixel-move-setup", "Active mask could not become editable")
        before_selection = viewer.pixelSelectionState()
        if before_selection is None or before_selection.bounds is None:
            self._fail("pixel-move-setup", "Movement started without selection bounds")
        destination = QPoint(origin.x(), min(viewer.height() - 20, origin.y() + 130))
        if not self._harness.is_background(
            self._harness.capture().pixelColor(destination)
        ):
            self._fail("pixel-move-setup", "Movement destination was not empty")
        viewer.setControlMode(viewer.CONTROL_MODE_MOVE)
        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, origin)
        started = interaction_clock()
        QTest.mouseMove(viewer, destination, delay=1)
        self._harness.drain_events()
        self._record_latency(started, "pixel-move-preview")
        preview = self._harness.capture()
        if not self._harness.is_background(preview.pixelColor(origin)):
            self._fail("pixel-move-preview", "Preview retained selected origin pixels")
        if not self._harness.is_mask_tint(preview.pixelColor(destination)):
            self._fail("pixel-move-preview", "Preview omitted moved mask pixels")
        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, destination)
        floating = viewer.floatingPixelEditState()
        if floating is None:
            self._fail(
                "pixel-move-release",
                "Pointer release did not retain an explicit floating edit",
            )
        if not viewer.anchorFloatingPixels():
            self._fail("pixel-move-anchor", "Floating pixels could not anchor")
        if not self._harness.wait_for_mask_render_idle():
            self._fail("pixel-move-commit", "Moved mask render did not settle")
        durable = self._harness.capture()
        if not self._harness.is_background(durable.pixelColor(origin)):
            self._fail("pixel-move-commit", "Commit retained selected origin pixels")
        if not self._harness.is_mask_tint(durable.pixelColor(destination)):
            self._fail("pixel-move-commit", "Commit omitted moved mask pixels")
        moved_selection = viewer.pixelSelectionState()
        if (
            moved_selection is None
            or moved_selection.bounds is None
            or moved_selection.bounds == before_selection.bounds
        ):
            self._fail("pixel-move-selection", "Marching ants did not move with pixels")
        if before_selection.coverage is None or moved_selection.coverage is None:
            self._fail(
                "pixel-move-selection", "Movement lost public selection coverage"
            )
        before_coverage = qimage_to_numpy_grayscale8(before_selection.coverage)
        moved_coverage = qimage_to_numpy_grayscale8(moved_selection.coverage)
        if np.count_nonzero(moved_coverage) >= np.count_nonzero(before_coverage):
            self._fail(
                "pixel-move-selection",
                "Movement retained transparent pixels from the geometric selection",
            )
        if not np.any(moved_coverage == 0):
            self._fail(
                "pixel-move-selection",
                "Content-derived selection no longer represents transparent holes",
            )
        if not viewer.undoSceneEdit():
            self._fail("pixel-move-undo", "Atomic pixel movement was not undoable")
        if not self._harness.wait_for_mask_render_idle():
            self._fail("pixel-move-undo", "Movement undo render did not settle")
        restored = self._harness.capture()
        if not self._harness.is_mask_tint(restored.pixelColor(origin)):
            self._fail("pixel-move-undo", "Undo did not restore origin pixels")
        if not self._harness.is_background(restored.pixelColor(destination)):
            self._fail("pixel-move-undo", "Undo retained destination pixels")
        restored_selection = viewer.pixelSelectionState()
        if (
            restored_selection is None
            or restored_selection.bounds != before_selection.bounds
        ):
            self._fail("pixel-move-undo", "Undo did not restore selection coverage")
        if restored_selection.coverage is None or not np.array_equal(
            qimage_to_numpy_grayscale8(restored_selection.coverage),
            before_coverage,
        ):
            self._fail("pixel-move-undo", "Undo changed geometric selection pixels")
        if not viewer.redoSceneEdit():
            self._fail("pixel-move-redo", "Atomic pixel movement was not redoable")
        if not self._harness.wait_for_mask_render_idle():
            self._fail("pixel-move-redo", "Movement redo render did not settle")
        redone_selection = viewer.pixelSelectionState()
        if (
            redone_selection is None
            or redone_selection.coverage is None
            or not np.array_equal(
                qimage_to_numpy_grayscale8(redone_selection.coverage),
                moved_coverage,
            )
        ):
            self._fail("pixel-move-redo", "Redo changed content-derived selection")
        if not viewer.undoSceneEdit():
            self._fail("pixel-move-redo", "Second movement undo was rejected")

    def _exercise_rgba_editing_and_bounds(self) -> None:
        """Require soft-clear history, async bounds, and an invisible cleanup state."""
        viewer = self._viewer
        scene = viewer.currentScene()
        if scene is None:
            self._fail("rgba-setup", "Mounted pane has no active scene")
        size = 128
        image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor(45, 130, 230, 255))
        placement = QRectF(
            scene.bounds.x() + scene.bounds.width() * 0.08,
            scene.bounds.y() + scene.bounds.height() * 0.08,
            float(size),
            float(size),
        )
        layer_id = viewer.addEditableRasterLayer(
            image,
            placement=placement,
            label="Abuse paint",
            interaction=LayerPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
            extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
        )
        if layer_id is None or not viewer.setSelectedLayer(scene.scene_id, layer_id):
            self._fail("rgba-setup", "Editable RGBA layer was not selectable")
        refreshed = viewer.currentScene()
        if refreshed is None or not any(
            layer.layer_id == layer_id and layer.source_kind == "raster"
            for layer in refreshed.layers
        ):
            self._fail("rgba-scene", "Editable RGBA layer is absent from scene order")

        half = QImage(size // 2, size, QImage.Format_Grayscale8)
        half.fill(128)
        if not viewer.setPixelSelection(
            half,
            QRect(int(placement.x()), int(placement.y()), size // 2, size),
        ):
            self._fail("rgba-selection", "RGBA selection coverage was rejected")
        if not viewer.deleteSelectedPixels():
            self._fail("rgba-delete", "Selected RGBA pixels were not cleared")
        edited = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
        if edited is None:
            self._fail("rgba-delete", "Edited RGBA snapshot became unavailable")
        if not 126 <= edited.pixelColor(8, 8).alpha() <= 128:
            self._fail(
                "rgba-delete", "Soft selection did not proportionally clear alpha"
            )
        if edited.pixelColor(size - 8, 8).alpha() != 255:
            self._fail("rgba-delete", "RGBA clear changed unselected pixels")
        if not viewer.undoSceneEdit():
            self._fail("rgba-undo", "Chronological undo rejected RGBA pixels")
        restored = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
        if restored is None or restored.pixelColor(8, 8).alpha() != 255:
            self._fail("rgba-undo", "RGBA undo did not restore exact alpha")
        if not viewer.redoSceneEdit():
            self._fail("rgba-redo", "Chronological redo rejected RGBA pixels")
        if not viewer.undoSceneEdit():
            self._fail("rgba-undo", "Second RGBA undo failed")

        completions: list[tuple[object, ...]] = []
        viewer.rasterBoundsRequestCompleted.connect(
            lambda *values: completions.append(tuple(values))
        )
        started = interaction_clock()
        request_id = viewer.requestRasterBounds(
            scene.scene_id,
            layer_id,
            QRect(-16, -16, 160, 160),
        )
        self._record_latency(started, "rgba-bounds-submit")
        if request_id is None:
            self._fail("rgba-bounds", "Editable RGBA bounds request was rejected")
        deadline = time.perf_counter() + 3.0
        while time.perf_counter() < deadline and not completions:
            self._harness.drain_events(wait_ms=1)
        if not completions or completions[-1][3] is not True:
            self._fail("rgba-bounds", "Editable RGBA bounds did not complete")
        state = viewer.rasterSurfaceState(scene.scene_id, layer_id)
        if state is None or state.bounds != QRect(-16, -16, 160, 160):
            self._fail("rgba-bounds", "Completed RGBA bounds are incorrect")
        if not viewer.undoSceneEdit():
            self._fail("rgba-bounds-undo", "RGBA bounds were absent from history")
        state = viewer.rasterSurfaceState(scene.scene_id, layer_id)
        if state is None or state.bounds != QRect(0, 0, size, size):
            self._fail("rgba-bounds-undo", "RGBA bounds undo was not exact")

        full = QImage(size, size, QImage.Format_Grayscale8)
        full.fill(255)
        if (
            not viewer.setPixelSelection(
                full,
                QRect(int(placement.x()), int(placement.y()), size, size),
            )
            or not viewer.deleteSelectedPixels()
        ):
            self._fail("rgba-cleanup", "Could not clear the temporary RGBA layer")
        transparent = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
        if (
            transparent is None
            or transparent.pixelColor(size // 2, size // 2).alpha() != 0
        ):
            self._fail("rgba-cleanup", "Temporary RGBA content remained visible")
        viewer.clearPixelSelection()
        viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
        self._harness.drain_events(wait_ms=120)

    def _record_latency(self, started: float, phase: str) -> None:
        """Retain and enforce worst synchronous editor latency."""
        latency_ms = (interaction_clock() - started) * 1000.0
        self._max_latency_ms = max(self._max_latency_ms, latency_ms)
        if latency_ms > _MAX_SYNCHRONOUS_EDITOR_LATENCY_MS:
            self._fail(
                phase,
                f"Synchronous editor work took {latency_ms:.1f}ms "
                f"(budget {_MAX_SYNCHRONOUS_EDITOR_LATENCY_MS:.1f}ms)",
            )

    @staticmethod
    def _fail(phase: str, message: str) -> None:
        """Raise one normalized editor workflow failure."""
        raise _EditorWorkflowFailure(phase, message)


class _EditorWorkflowFailure(RuntimeError):
    """Carry a focused editor invariant failure."""

    def __init__(self, phase: str, message: str) -> None:
        """Capture phase and human-readable evidence."""
        super().__init__(message)
        self.phase = phase
        self.message = message
