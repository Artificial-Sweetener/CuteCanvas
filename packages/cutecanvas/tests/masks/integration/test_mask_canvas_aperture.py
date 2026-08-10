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

"""Prove the composition canvas is the mask visibility and authoring aperture."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pytest
from cutecanvas import PixelSelectionMode, RasterExtentPolicy
from cutecanvas.coverage.spatial_constraint import PathCoverageConstraint
from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QPainterPath
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qpane.sdk.raster import qimage_to_numpy_argb32
from qpane.sdk.scene import ClipCoordinateSpace, LayerClip, RasterBounds
from qpane.sdk.vector import VectorShapeKind


@pytest.fixture()
def wide_harness(qapp: QApplication) -> Iterator[MountedQPaneHarness]:
    """Mount a square composition with observable viewport gutters."""
    mounted = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 400),
        widget_size=QSize(600, 400),
    )
    try:
        yield mounted
    finally:
        mounted.close()


@pytest.fixture()
def guttered_harness(qapp: QApplication) -> Iterator[MountedQPaneHarness]:
    """Mount a square composition with observable vertical gutters."""
    mounted = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 400),
        widget_size=QSize(400, 600),
    )
    try:
        yield mounted
    finally:
        mounted.close()


def _active_mask_layer(harness: MountedQPaneHarness):
    """Return the public layer handle for the active mask."""
    viewer = harness.viewer
    scene = viewer.currentScene()
    document = viewer.editor.compositions.current
    mask_id = viewer.activeMaskID()
    assert scene is not None and document is not None and mask_id is not None
    snapshot = next(
        layer
        for layer in scene.layers
        if layer.source_kind == "coverage" and layer.source_id == mask_id
    )
    layer = document.layer(snapshot.layer_id)
    assert layer is not None
    return layer


def _panel_point(harness: MountedQPaneHarness, x: float, y: float):
    """Project one scene point through QPane's public view coordinates."""
    point = harness.viewer.view().scene_to_panel_point(QPointF(x, y))
    assert point is not None
    return point.toPoint()


def test_moved_mask_is_clipped_to_canvas_while_runtime_content_survives(
    wide_harness: MountedQPaneHarness,
) -> None:
    """Layer movement may retain off-canvas coverage without painting the gutter."""
    harness = wide_harness
    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    assert viewer.addCoverageShape(
        VectorShapeKind.RECTANGLE,
        QRectF(20.0, 40.0, 80.0, 120.0),
        PixelSelectionMode.ADD,
    )
    assert (
        harness.wait_for_mask_tint(_panel_point(harness, 40.0, 80.0)).latency_ms
        is not None
    )
    layer = _active_mask_layer(harness)
    initial_plan = viewer.view().calculateRenderPlan(is_blank=False)
    assert initial_plan is not None
    initial_descriptor = next(
        item.descriptor
        for item in initial_plan.render_items
        if item.descriptor.layer_id == layer.id
    )
    assert initial_descriptor.clip is None

    assert layer.translate(QPointF(-60.0, 0.0))
    harness.drain_events()
    assert harness.wait_for_mask_render_idle()
    scene = viewer.currentScene()
    assert scene is not None
    plan = viewer.view().calculateRenderPlan(is_blank=False)
    assert plan is not None
    matches = tuple(
        item.descriptor
        for item in plan.render_items
        if item.descriptor.layer_id == layer.id
    )
    assert matches, tuple(
        (item.descriptor.layer_id, item.descriptor.kind) for item in plan.render_items
    )
    resolved = matches[0]
    assert resolved.clip == LayerClip(
        ClipCoordinateSpace.SCENE,
        scene.bounds.x(),
        scene.bounds.y(),
        scene.bounds.width(),
        scene.bounds.height(),
    )
    assert not harness.is_mask_tint(
        harness.capture().pixelColor(_panel_point(harness, -20.0, 80.0))
    )

    moved = viewer.exportMaskImage(mask_id)
    assert moved is not None
    assert moved.pixelColor(10, 80).value() == 255
    assert moved.pixelColor(50, 80).value() == 0

    assert layer.translate(QPointF(60.0, 0.0))
    restored = viewer.exportMaskImage(mask_id)
    assert restored is not None
    assert restored.pixelColor(30, 80).value() == 255
    assert restored.pixelColor(110, 80).value() == 0


@pytest.mark.parametrize(
    ("mode_name", "scene_points"),
    (
        (
            "CONTROL_MODE_MASK_RECTANGLE",
            ((300.0, 100.0), (480.0, 300.0)),
        ),
        (
            "CONTROL_MODE_MASK_ELLIPSE",
            ((300.0, 100.0), (480.0, 300.0)),
        ),
        (
            "CONTROL_MODE_MASK_LASSO",
            (
                (300.0, 100.0),
                (480.0, 100.0),
                (480.0, 300.0),
                (300.0, 300.0),
            ),
        ),
    ),
)
def test_shape_preview_and_authorship_share_the_canvas_aperture(
    wide_harness: MountedQPaneHarness,
    mode_name: str,
    scene_points: tuple[tuple[float, float], ...],
) -> None:
    """Every shape tool must neither preview nor retain a hostile off-canvas drag."""
    harness = wide_harness
    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    viewer.setControlMode(getattr(viewer, mode_name))
    points = tuple(_panel_point(harness, *point) for point in scene_points)
    canvas_right = _panel_point(harness, 400.0, 200.0).x()
    before = qimage_to_numpy_argb32(harness.capture())

    QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=points[0])
    for point in points[1:]:
        QTest.mouseMove(viewer, point, delay=1)
    harness.drain_events()
    preview = qimage_to_numpy_argb32(harness.capture())

    changed = np.any(before != preview, axis=2)
    assert not np.any(changed[:, canvas_right + 3 :])

    QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=points[-1])
    harness.drain_events()
    authored = viewer.exportMaskImage(mask_id)
    assert authored is not None
    assert authored.pixelColor(350, 200).value() == 255

    layer = _active_mask_layer(harness)
    assert layer.translate(QPointF(-100.0, 0.0))
    moved = viewer.exportMaskImage(mask_id)
    assert moved is not None
    assert moved.pixelColor(250, 200).value() == 255
    assert moved.pixelColor(350, 200).value() == 0

    assert layer.translate(QPointF(100.0, 0.0))
    restored = viewer.exportMaskImage(mask_id)
    assert restored is not None
    assert restored.pixelColor(350, 200).value() == 255


def test_shape_gesture_may_begin_outside_and_authors_only_inside_the_canvas(
    wide_harness: MountedQPaneHarness,
) -> None:
    """A gutter-to-canvas drag must retain every covered canvas-edge pixel."""
    harness = wide_harness
    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    viewer.setControlMode(viewer.CONTROL_MODE_MASK_RECTANGLE)
    canvas_left = _panel_point(harness, 0.0, 200.0).x()
    before = qimage_to_numpy_argb32(harness.capture())

    QTest.mousePress(
        viewer,
        Qt.MouseButton.LeftButton,
        pos=_panel_point(harness, -50.0, 100.0),
    )
    QTest.mouseMove(viewer, _panel_point(harness, 50.0, 300.0))
    harness.drain_events()
    preview = qimage_to_numpy_argb32(harness.capture())
    changed = np.any(before != preview, axis=2)
    assert not np.any(changed[:, : canvas_left - 3])
    assert np.any(changed[100:301, canvas_left : canvas_left + 50])
    QTest.mouseRelease(
        viewer,
        Qt.MouseButton.LeftButton,
        pos=_panel_point(harness, 50.0, 300.0),
    )
    harness.drain_events()

    assert viewer.getMaskUndoState(mask_id).undo_depth == 1
    authored = viewer.exportMaskImage(mask_id)
    assert authored is not None
    assert authored.pixelColor(0, 200).value() == 255
    assert authored.pixelColor(49, 200).value() == 255
    assert authored.pixelColor(51, 200).value() == 0


def test_shape_started_above_canvas_keeps_top_preview_boundary_visible(
    guttered_harness: MountedQPaneHarness,
) -> None:
    """Top-clipped ants and committed coverage must reach the first canvas row."""
    harness = guttered_harness
    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    viewer.setControlMode(viewer.CONTROL_MODE_MASK_RECTANGLE)
    canvas_top = _panel_point(harness, 200.0, 0.0).y()
    left = _panel_point(harness, 100.0, 0.0).x()
    right = _panel_point(harness, 300.0, 0.0).x()
    before = qimage_to_numpy_argb32(harness.capture())

    start = _panel_point(harness, 100.0, -50.0)
    end = _panel_point(harness, 300.0, 50.0)
    QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(viewer, end)
    harness.drain_events()
    preview = qimage_to_numpy_argb32(harness.capture())
    changed = np.any(before != preview, axis=2)

    assert not np.any(changed[: canvas_top - 3, :])
    assert np.any(changed[canvas_top : canvas_top + 3, left : right + 1])

    QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=end)
    harness.drain_events()
    assert viewer.getMaskUndoState(mask_id).undo_depth == 1
    authored = viewer.exportMaskImage(mask_id)
    assert authored is not None
    assert authored.pixelColor(200, 0).value() == 255
    assert authored.pixelColor(200, 49).value() == 255
    assert authored.pixelColor(200, 51).value() == 0


def test_brush_authors_only_the_exposed_canvas_of_an_infinite_moved_mask(
    wide_harness: MountedQPaneHarness,
) -> None:
    """Raster paint may expand mask storage but never escape the scene aperture."""
    harness = wide_harness
    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    layer = _active_mask_layer(harness)
    assert layer.translate(QPointF(200.0, 0.0))
    viewer.setBrushSize(20)
    viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)

    inside = _panel_point(harness, 50.0, 200.0)
    QTest.mouseClick(viewer, Qt.MouseButton.LeftButton, pos=inside)
    assert harness.wait_for_mask_undo_depth(mask_id, 1)
    assert harness.wait_for_mask_render_idle()
    painted = viewer.exportMaskImage(mask_id)
    assert painted is not None
    assert painted.pixelColor(50, 200).value() == 255

    crossing_start = _panel_point(harness, 350.0, 200.0)
    crossing_end = _panel_point(harness, 450.0, 200.0)
    QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=crossing_start)
    QTest.mouseMove(viewer, crossing_end)
    QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=crossing_end)
    assert harness.wait_for_mask_undo_depth(mask_id, 2)

    outside = _panel_point(harness, -30.0, 200.0)
    QTest.mouseClick(viewer, Qt.MouseButton.LeftButton, pos=outside)
    harness.drain_events()
    assert viewer.getMaskUndoState(mask_id).undo_depth == 2

    assert layer.translate(QPointF(-200.0, 0.0))
    hidden = viewer.exportMaskImage(mask_id)
    assert hidden is not None
    assert hidden.pixelColor(50, 200).value() == 0

    assert layer.translate(QPointF(200.0, 0.0))
    restored = viewer.exportMaskImage(mask_id)
    assert restored is not None
    assert restored.pixelColor(50, 200).value() == 255


def test_mask_shape_authors_after_raster_storage_expands_from_layer_origin(
    wide_harness: MountedQPaneHarness,
) -> None:
    """Retained shapes must remain in layer-local space after raster expansion."""
    harness = wide_harness
    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    mask_info = viewer.listMasksForComposition()[0]
    assert mask_info.scene_id is not None
    assert mask_info.layer_id is not None
    viewer.setRasterExtentPolicy(
        mask_info.scene_id,
        mask_info.layer_id,
        RasterExtentPolicy.EXPAND_ON_WRITE,
    )
    initial_state = viewer.rasterSurfaceState(
        mask_info.scene_id,
        mask_info.layer_id,
    )
    assert initial_state is not None
    assert initial_state.extent_policy is RasterExtentPolicy.EXPAND_ON_WRITE
    layer = _active_mask_layer(harness)
    assert layer.translate(QPointF(500.0, 0.0))

    viewer.setBrushSize(20)
    viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
    QTest.mouseClick(
        viewer,
        Qt.MouseButton.LeftButton,
        pos=_panel_point(harness, 50.0, 200.0),
    )
    assert harness.wait_for_mask_undo_depth(mask_id, 1)
    state = viewer.rasterSurfaceState(mask_info.scene_id, mask_info.layer_id)
    assert state is not None
    assert state.bounds.x() < 0

    viewer.setControlMode(viewer.CONTROL_MODE_MASK_RECTANGLE)
    start = _panel_point(harness, 100.0, 100.0)
    end = _panel_point(harness, 200.0, 200.0)
    QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(viewer, end)
    QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=end)
    harness.drain_events()

    assert viewer.getMaskUndoState(mask_id).undo_depth == 2
    authored = viewer.exportMaskImage(mask_id)
    assert authored is not None
    assert authored.pixelColor(150, 150).value() == 255


def test_large_canvas_aperture_samples_only_the_requested_dirty_region() -> None:
    """A 16K canvas constraint must never materialize a 16K coverage image."""
    path = QPainterPath()
    path.addRect(0.0, 0.0, 16_384.0, 16_384.0)
    constraint = PathCoverageConstraint(path)

    sampled = constraint.sample(RasterBounds(8_000, 8_000, 64, 48), stride=2)

    assert constraint.bounds == RasterBounds(0, 0, 16_384, 16_384)
    assert sampled.shape == (24, 32)
    assert np.all(sampled == 255)
