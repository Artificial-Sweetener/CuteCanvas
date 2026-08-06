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

"""Mounted hostile geometry-authoring snapping workflows."""

from __future__ import annotations

import pytest
from cutecanvas import VectorShapeKind
from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def _near_half_drag(viewer: object) -> tuple[object, object]:
    """Return panel points slightly inside the left and center document lines."""
    start = viewer.view().scene_to_panel_point(QPointF(3.0, 100.0))
    endpoint = viewer.view().scene_to_panel_point(QPointF(497.0, 300.0))
    assert start is not None and endpoint is not None
    return start, endpoint


@pytest.mark.parametrize(
    "mode_name",
    ("CONTROL_MODE_MASK_RECTANGLE", "CONTROL_MODE_MASK_ELLIPSE"),
)
def test_mask_shape_edges_snap_exactly_from_document_edge_to_center(
    qapp: QApplication,
    mode_name: str,
) -> None:
    """Mask shape preview and commit must share exact document-line snaps."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1000, 800),
        widget_size=QSize(1200, 900),
    )
    viewer = harness.viewer
    try:
        viewer.setControlMode(getattr(viewer, mode_name))
        start, endpoint = _near_half_drag(viewer)

        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start.toPoint())
        QTest.mouseMove(viewer, endpoint.toPoint(), delay=0)
        harness.drain_events()

        guides = viewer.snappingSubsystem().guides
        assert any(
            guide.axis.value == "x" and guide.position == pytest.approx(500.0)
            for guide in guides
        )

        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=endpoint.toPoint())
        harness.drain_events()

        layer = viewer.mask_service.assets.get_layer(harness.mask_ids[0])
        assert layer is not None
        assert len(layer.coverage.retained.items) == 1
        item = layer.coverage.retained.items[0]
        left, top, width, height = item.geometry.local_bounds
        assert left == pytest.approx(0.0)
        assert left + width == pytest.approx(500.0)
        assert top == pytest.approx(100.0, abs=1.0)
        assert height == pytest.approx(200.0, abs=1.0)
        assert not viewer.snappingSubsystem().guides
        assert viewer.getMaskUndoState(harness.mask_ids[0]).undo_depth == 1
    finally:
        harness.close()


@pytest.mark.parametrize(
    "mode_name",
    ("CONTROL_MODE_SELECT_RECTANGLE", "CONTROL_MODE_SELECT_ELLIPSE"),
)
def test_pixel_selection_edges_snap_to_document_center(
    qapp: QApplication,
    mode_name: str,
) -> None:
    """Pixel-selection marquees must commit the same exact snapped bounds."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1000, 800),
        widget_size=QSize(1200, 900),
    )
    viewer = harness.viewer
    try:
        viewer.setControlMode(getattr(viewer, mode_name))
        start, endpoint = _near_half_drag(viewer)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start.toPoint())
        QTest.mouseMove(viewer, endpoint.toPoint(), delay=0)
        harness.drain_events()
        assert any(
            guide.axis.value == "x" and guide.position == pytest.approx(500.0)
            for guide in viewer.snappingSubsystem().guides
        )
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=endpoint.toPoint())
        harness.drain_events()

        selection = viewer.pixelSelectionState()
        assert selection is not None and selection.bounds is not None
        assert selection.bounds.left() == 0
        assert selection.bounds.right() + 1 == 500
        assert not viewer.snappingSubsystem().guides
        assert viewer.sceneEditUndoAvailable()
        assert viewer.undoSceneEdit()
        assert not viewer.pixelSelectionState().has_selection
        assert viewer.redoSceneEdit()
        assert viewer.pixelSelectionState().bounds == selection.bounds
    finally:
        harness.close()


@pytest.mark.parametrize(
    "shape_kind",
    (VectorShapeKind.RECTANGLE, VectorShapeKind.ELLIPSE),
)
def test_vector_shape_edges_snap_to_document_center(
    qapp: QApplication,
    shape_kind: VectorShapeKind,
) -> None:
    """Semantic vector shapes must retain exact snapped source geometry."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1000, 800),
        widget_size=QSize(1200, 900),
    )
    viewer = harness.viewer
    try:
        scene = viewer.currentScene()
        assert scene is not None
        layer_id = viewer.createVectorLayer(QSize(1000, 800), label="Snapped shape")
        assert layer_id is not None
        assert viewer.setSelectedLayer(scene.scene_id, layer_id)
        viewer.setVectorToolShape(shape_kind)
        viewer.setControlMode(viewer.CONTROL_MODE_VECTOR_SHAPE)
        start, endpoint = _near_half_drag(viewer)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start.toPoint())
        QTest.mouseMove(viewer, endpoint.toPoint(), delay=0)
        harness.drain_events()
        assert any(
            guide.axis.value == "x" and guide.position == pytest.approx(500.0)
            for guide in viewer.snappingSubsystem().guides
        )
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=endpoint.toPoint())
        harness.drain_events()

        state = viewer.vectorDocumentState(scene.scene_id, layer_id)
        assert state is not None and len(state.objects) == 1
        bounds = state.objects[0].bounds
        assert bounds.left() == pytest.approx(0.0)
        assert bounds.right() == pytest.approx(500.0)
        assert not viewer.snappingSubsystem().guides
        assert viewer.undoSceneEdit()
        assert viewer.vectorDocumentState(scene.scene_id, layer_id).objects == ()
        assert viewer.redoSceneEdit()
        assert len(viewer.vectorDocumentState(scene.scene_id, layer_id).objects) == 1
    finally:
        harness.close()


def test_mask_square_constraint_preserves_snap_and_preview_geometry(
    qapp: QApplication,
) -> None:
    """Shift-constrained mask geometry must remain square when one axis snaps."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1000, 800),
        widget_size=QSize(1200, 900),
    )
    viewer = harness.viewer
    try:
        viewer.setControlMode(viewer.CONTROL_MODE_MASK_RECTANGLE)
        start = viewer.view().scene_to_panel_point(QPointF(3.0, 100.0))
        endpoint = viewer.view().scene_to_panel_point(QPointF(497.0, 590.0))
        assert start is not None and endpoint is not None

        QTest.keyPress(viewer, Qt.Key.Key_Shift)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start.toPoint())
        QTest.mouseMove(viewer, endpoint.toPoint(), delay=0)
        harness.drain_events()
        assert any(
            guide.axis.value == "x" and guide.position == pytest.approx(500.0)
            for guide in viewer.snappingSubsystem().guides
        )
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=endpoint.toPoint())
        QTest.keyRelease(viewer, Qt.Key.Key_Shift)
        harness.drain_events()

        layer = viewer.mask_service.assets.get_layer(harness.mask_ids[0])
        assert layer is not None
        item = layer.coverage.retained.items[0]
        left, _top, width, height = item.geometry.local_bounds
        assert left == pytest.approx(0.0)
        assert width == pytest.approx(500.0)
        assert height == pytest.approx(width)
        assert not viewer.snappingSubsystem().guides
    finally:
        QTest.keyRelease(viewer, Qt.Key.Key_Shift)
        harness.close()


def test_disabled_snapping_preserves_raw_mask_geometry(qapp: QApplication) -> None:
    """The global policy switch must bypass both mask-shape endpoints."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1000, 800),
        widget_size=QSize(1200, 900),
    )
    viewer = harness.viewer
    try:
        assert viewer.configureSnapping(enabled=False)
        viewer.setControlMode(viewer.CONTROL_MODE_MASK_RECTANGLE)
        start, endpoint = _near_half_drag(viewer)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start.toPoint())
        QTest.mouseMove(viewer, endpoint.toPoint(), delay=0)
        harness.drain_events()
        assert not viewer.snappingSubsystem().guides
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=endpoint.toPoint())
        harness.drain_events()

        layer = viewer.mask_service.assets.get_layer(harness.mask_ids[0])
        assert layer is not None
        left, _top, width, _height = layer.coverage.retained.items[
            0
        ].geometry.local_bounds
        assert left > 1.0
        assert left + width < 499.0
        assert not viewer.snappingSubsystem().guides
    finally:
        harness.close()


@pytest.mark.parametrize("target", ("guide", "grid"))
def test_configured_authoring_target_domains_snap_exactly(
    qapp: QApplication,
    target: str,
) -> None:
    """Authored guides and the optional grid participate through shared policy."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1000, 800),
        widget_size=QSize(1200, 900),
    )
    viewer = harness.viewer
    try:
        if target == "guide":
            assert viewer.setSnapGuides(vertical=(333.0,))
            assert viewer.configureSnapping(
                canvas=False,
                layers=False,
                selections=False,
                guides=True,
                grid=False,
            )
            expected_x = 333.0
        else:
            assert viewer.setSnapGrid(QPointF(), QPointF(250.0, 250.0))
            assert viewer.configureSnapping(
                canvas=False,
                layers=False,
                selections=False,
                guides=False,
                grid=True,
            )
            expected_x = 250.0
        viewer.setControlMode(viewer.CONTROL_MODE_MASK_RECTANGLE)
        start = viewer.view().scene_to_panel_point(QPointF(100.0, 100.0))
        endpoint = viewer.view().scene_to_panel_point(QPointF(expected_x - 4.0, 300.0))
        assert start is not None and endpoint is not None

        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start.toPoint())
        QTest.mouseMove(viewer, endpoint.toPoint(), delay=0)
        harness.drain_events()
        assert any(
            guide.axis.value == "x" and guide.position == pytest.approx(expected_x)
            for guide in viewer.snappingSubsystem().guides
        )
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=endpoint.toPoint())
        harness.drain_events()

        layer = viewer.mask_service.assets.get_layer(harness.mask_ids[0])
        assert layer is not None
        left, _top, width, _height = layer.coverage.retained.items[
            0
        ].geometry.local_bounds
        assert left == pytest.approx(100.0, abs=1.0)
        assert left + width == pytest.approx(expected_x)
    finally:
        harness.close()


@pytest.mark.parametrize("target", ("layer", "selection"))
def test_scene_geometry_target_domains_snap_mask_authoring(
    qapp: QApplication,
    target: str,
) -> None:
    """Visible layer and pixel-selection geometry both drive authored endpoints."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1000, 800),
        widget_size=QSize(1200, 900),
    )
    viewer = harness.viewer
    try:
        if target == "selection":
            assert viewer.configureSnapping(enabled=False)
            viewer.setControlMode(viewer.CONTROL_MODE_SELECT_RECTANGLE)
            selection_start = viewer.view().scene_to_panel_point(QPointF(200.0, 200.0))
            selection_end = viewer.view().scene_to_panel_point(QPointF(600.0, 500.0))
            assert selection_start is not None and selection_end is not None
            QTest.mousePress(
                viewer, Qt.MouseButton.LeftButton, pos=selection_start.toPoint()
            )
            QTest.mouseRelease(
                viewer, Qt.MouseButton.LeftButton, pos=selection_end.toPoint()
            )
            harness.drain_events()
            selection = viewer.pixelSelectionState()
            assert selection.has_selection and selection.bounds is not None
            assert viewer.configureSnapping(
                enabled=True,
                canvas=False,
                layers=False,
                selections=True,
                guides=False,
                grid=False,
            )
            expected_x = selection.bounds.x() + selection.bounds.width() / 2.0
        else:
            scene = viewer.currentScene()
            assert scene is not None
            target_layer = next(
                layer
                for layer in scene.layers
                if layer.source_id not in set(harness.mask_ids)
            )
            assert viewer.setLayerTransform(
                scene.scene_id,
                target_layer.layer_id,
                QTransform.fromTranslate(50.0, 0.0),
            )
            assert viewer.configureSnapping(
                canvas=False,
                layers=True,
                selections=False,
                guides=False,
                grid=False,
            )
            expected_x = 550.0

        viewer.setControlMode(viewer.CONTROL_MODE_MASK_RECTANGLE)
        start = viewer.view().scene_to_panel_point(QPointF(100.0, 100.0))
        endpoint = viewer.view().scene_to_panel_point(QPointF(expected_x - 4.0, 300.0))
        assert start is not None and endpoint is not None
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start.toPoint())
        QTest.mouseMove(viewer, endpoint.toPoint(), delay=0)
        harness.drain_events()
        assert any(
            guide.axis.value == "x" and guide.position == pytest.approx(expected_x)
            for guide in viewer.snappingSubsystem().guides
        )
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=endpoint.toPoint())
        harness.drain_events()

        layer = viewer.mask_service.assets.get_layer(harness.mask_ids[0])
        assert layer is not None
        left, _top, width, _height = layer.coverage.retained.items[
            0
        ].geometry.local_bounds
        assert left + width == pytest.approx(expected_x)
    finally:
        harness.close()


def test_cancel_and_tool_switch_clear_authoring_session_and_guides(
    qapp: QApplication,
) -> None:
    """Cancellation and deactivation cannot leak a snap into a later gesture."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1000, 800),
        widget_size=QSize(1200, 900),
    )
    viewer = harness.viewer
    try:
        viewer.setControlMode(viewer.CONTROL_MODE_MASK_RECTANGLE)
        start, endpoint = _near_half_drag(viewer)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start.toPoint())
        QTest.mouseMove(viewer, endpoint.toPoint(), delay=0)
        harness.drain_events()
        assert viewer.snappingSubsystem().guides

        QTest.keyClick(viewer, Qt.Key.Key_Escape)
        harness.drain_events()
        assert not viewer.snappingSubsystem().guides
        layer = viewer.mask_service.assets.get_layer(harness.mask_ids[0])
        assert layer is not None and not layer.coverage.retained.items

        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start.toPoint())
        QTest.mouseMove(viewer, endpoint.toPoint(), delay=0)
        harness.drain_events()
        assert viewer.snappingSubsystem().guides
        QTest.keyPress(viewer, Qt.Key.Key_Space)
        harness.drain_events()
        assert not viewer.snappingSubsystem().guides
        assert not layer.coverage.retained.items
        QTest.keyRelease(viewer, Qt.Key.Key_Space)
        harness.drain_events()

        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start.toPoint())
        QTest.mouseMove(viewer, endpoint.toPoint(), delay=0)
        harness.drain_events()
        assert viewer.snappingSubsystem().guides
        viewer.setControlMode(viewer.CONTROL_MODE_PANZOOM)
        harness.drain_events()
        assert not viewer.snappingSubsystem().guides
        assert not layer.coverage.retained.items

        viewer.setControlMode(viewer.CONTROL_MODE_MASK_RECTANGLE)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start.toPoint())
        QTest.mouseMove(viewer, endpoint.toPoint(), delay=0)
        harness.drain_events()
        assert viewer.snappingSubsystem().guides
        viewer.createComposition(QRectF(0.0, 0.0, 256.0, 192.0))
        harness.drain_events()
        assert not viewer.snappingSubsystem().guides
        assert not layer.coverage.retained.items
    finally:
        harness.close()
