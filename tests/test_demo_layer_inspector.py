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
"""Public-API integration coverage for the demo raster layer inspector."""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from cutecanvas import CuteCanvas, RasterExtentPolicy, VectorShapeKind
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
from qpane.rendering.layer_rasterization import LayerRasterizer

from examples.cutecanvas_demo import ExampleOptions, ExampleWindow
from examples.demonstration.layer_inspector import RasterStorageProperties
from examples.demonstration.placed_asset_controls import PlacedAssetControls
from examples.demonstration.transform_controls import LayerTransformControls
from tests.harness.mounted_qpane import MountedQPaneHarness


def _wait_for(qapp, predicate, timeout: float = 3.0) -> None:
    """Process Qt events until ``predicate`` succeeds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("timed out waiting for the demo inspector")


def test_demo_layer_inspector_changes_policy_and_pads_through_public_api(qapp) -> None:
    """The demo inspector should teach the complete host-facing resize workflow."""
    viewer = CuteCanvas(features=("mask",))
    image_id = uuid.uuid4()
    image = QImage(12, 10, QImage.Format_RGB32)
    viewer.setImagesByID(
        CuteCanvas.imageMapFromLists([image], ids=[image_id]), image_id
    )
    mask_id = viewer.createBlankMask(image.size())
    assert mask_id is not None
    assert viewer.setActiveMaskID(mask_id)
    mask = viewer.listMasksForImage()[0]
    assert mask.scene_id is not None and mask.layer_id is not None
    inspector = RasterStorageProperties(viewer, mask.scene_id, mask.layer_id)
    try:
        expanding_index = inspector._policy_combo.findData(
            RasterExtentPolicy.EXPAND_ON_WRITE
        )

        inspector._policy_combo.setCurrentIndex(expanding_index)

        state = viewer.rasterSurfaceState(mask.scene_id, mask.layer_id)
        assert state is not None
        assert state.extent_policy is RasterExtentPolicy.EXPAND_ON_WRITE
        inspector._pad_button.click()
        _wait_for(
            qapp,
            lambda: (
                (updated := viewer.rasterSurfaceState(mask.scene_id, mask.layer_id))
                is not None
                and updated.pending_request_id is None
                and updated.bounds == QRect(-32, -32, 76, 74)
            ),
        )

        assert inspector._bound_inputs["x"].value() == -32
        assert inspector._bound_inputs["y"].value() == -32
        assert inspector._bound_inputs["width"].value() == 76
        assert inspector._bound_inputs["height"].value() == 74
    finally:
        inspector.close()
        inspector.deleteLater()
        viewer.close()
        viewer.deleteLater()
        qapp.processEvents()


def test_demo_layer_inspector_preserves_manual_bounds_until_applied(qapp) -> None:
    """Scene refreshes and async submission must not discard edited bounds."""
    viewer = CuteCanvas(features=("mask",))
    image_id = uuid.uuid4()
    image = QImage(40, 30, QImage.Format_RGB32)
    viewer.setImagesByID(
        CuteCanvas.imageMapFromLists([image], ids=[image_id]), image_id
    )
    mask_id = viewer.createBlankMask(image.size())
    assert mask_id is not None
    assert viewer.setActiveMaskID(mask_id)
    mask = viewer.listMasksForImage()[0]
    assert mask.scene_id is not None and mask.layer_id is not None
    inspector = RasterStorageProperties(viewer, mask.scene_id, mask.layer_id)
    requested = QRect(-8, -6, 56, 44)
    try:
        for name, value in (
            ("x", requested.x()),
            ("y", requested.y()),
            ("width", requested.width()),
            ("height", requested.height()),
        ):
            inspector._bound_inputs[name].setValue(value)

        assert viewer.setRasterExtentPolicy(
            mask.scene_id,
            mask.layer_id,
            RasterExtentPolicy.EXPAND_ON_WRITE,
        )

        assert inspector._edited_bounds() == requested
        assert inspector._status.text().startswith("Edited bounds:")
        inspector._apply_button.click()
        assert inspector._edited_bounds() == requested
        assert inspector._status.text().startswith("Preparing bounds request")
        _wait_for(
            qapp,
            lambda: (
                (updated := viewer.rasterSurfaceState(mask.scene_id, mask.layer_id))
                is not None
                and updated.pending_request_id is None
                and updated.bounds == requested
            ),
        )

        assert inspector._edited_bounds() == requested
        assert inspector._status.text() == "Raster bounds updated."
    finally:
        inspector.close()
        inspector.deleteLater()
        viewer.close()
        viewer.deleteLater()
        qapp.processEvents()


def test_demo_layer_inspector_accepts_crop_and_clips_painted_pixels(
    qapp,
    monkeypatch,
) -> None:
    """Accepting the crop warning must submit and visibly apply smaller bounds."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(40, 30),
        widget_size=QSize(400, 300),
        mask_count=1,
        brush_size=4,
    )
    mask = harness.viewer.listMasksForImage()[0]
    assert mask.scene_id is not None and mask.layer_id is not None
    inspector = RasterStorageProperties(
        harness.viewer,
        mask.scene_id,
        mask.layer_id,
    )
    painted_panel_point = QPoint(300, 200)
    try:
        QTest.mouseClick(
            harness.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            painted_panel_point,
        )
        assert harness.wait_for_mask_undo_depth(harness.mask_ids[0], 1)
        before = harness.viewer.getActiveMaskImage()
        assert before is not None
        assert before.pixelColor(30, 20).red() > 0
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes.value,
        )
        inspector._bound_inputs["width"].setValue(10)
        inspector._bound_inputs["height"].setValue(10)

        inspector._apply_button.click()

        _wait_for(
            qapp,
            lambda: (
                (
                    state := harness.viewer.rasterSurfaceState(
                        mask.scene_id,
                        mask.layer_id,
                    )
                )
                is not None
                and state.pending_request_id is None
                and state.bounds == QRect(0, 0, 10, 10)
            ),
        )

        after = harness.viewer.getActiveMaskImage()
        assert after is not None
        assert after.pixelColor(30, 20).red() == 0
        assert harness.wait_for_background(painted_panel_point).latency_ms is not None
    finally:
        inspector.close()
        inspector.deleteLater()
        harness.close()


def test_demo_transform_controls_apply_to_non_destructive_placed_layer(qapp) -> None:
    """Placed layers must scale and rotate through the visible demo controls."""
    window = ExampleWindow(ExampleOptions(feature_set="core"))
    inspector = None
    try:
        image_id = uuid.uuid4()
        background = QImage(400, 300, QImage.Format_ARGB32_Premultiplied)
        background.fill(QColor("black"))
        window.qpane.setImagesByID(
            CuteCanvas.imageMapFromLists([background], ids=[image_id]),
            image_id,
        )
        placed = QImage(80, 60, QImage.Format_ARGB32_Premultiplied)
        placed.fill(QColor("magenta"))
        window.workspace.place_decoded_embedded_asset(Path("placed.png"), placed)
        scene = window.qpane.currentScene()
        selected = window.qpane.selectedLayer()
        assert scene is not None and selected is not None
        original_transform = window.qpane.layerTransform(
            scene.scene_id,
            selected.layer_id,
        )
        assert original_transform is not None
        window.resize(900, 650)
        window.show()
        qapp.processEvents()
        inspector = LayerTransformControls(
            window.qpane,
            scene.scene_id,
            selected.layer_id,
            window,
        )
        controls = inspector
        controls._position_x.setValue(120.0)
        controls._position_y.setValue(70.0)
        controls._scale_x.setValue(150.0)
        controls._scale_y.setValue(75.0)
        controls._rotation.setValue(30.0)

        controls._apply.click()
        qapp.processEvents()

        transform = window.qpane.layerTransform(scene.scene_id, selected.layer_id)
        bounds = window.qpane.layerLocalBounds(scene.scene_id, selected.layer_id)
        assert transform is not None and bounds == QRectF(0.0, 0.0, 80.0, 60.0)
        mapped = transform.mapRect(bounds)
        assert abs(mapped.x() - 120.0) < 0.01
        assert abs(mapped.y() - 70.0) < 0.01
        assert abs(transform.m11() - 1.5 * 0.8660254) < 0.001
        assert abs(transform.m12() - 0.75) < 0.001
        assert controls._status.text() == "Transform applied."
        internal_scene = window.qpane.view().current_scene_descriptor()
        assert internal_scene is not None
        center = window.qpane.view().layer_source_to_panel_point(
            internal_scene.scene_id,
            selected.layer_id,
            QPointF(40.0, 30.0),
        )
        assert center is not None
        rendered = window.qpane.grab().toImage()
        center_color = rendered.pixelColor(center.toPoint())
        assert center_color.red() > 200 and center_color.blue() > 200
        window.qpane.markDirty()
        window.qpane.update()
        qapp.processEvents()
        assert window.qpane.grab().toImage() == rendered

        assert window.qpane.undoSceneEdit()
        assert (
            window.qpane.layerTransform(scene.scene_id, selected.layer_id)
            == original_transform
        )
        assert window.qpane.redoSceneEdit()
        assert (
            window.qpane.layerTransform(scene.scene_id, selected.layer_id) == transform
        )
    finally:
        if inspector is not None:
            inspector.close()
            inspector.deleteLater()
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_demo_rasterized_placed_layer_is_immediately_pixel_editable(
    qapp,
    monkeypatch,
) -> None:
    """The shown demo must explain async readiness and then accept pixel edits."""
    window = ExampleWindow(ExampleOptions(feature_set="core"))
    inspector = None
    release_rasterization = threading.Event()
    try:
        image_id = uuid.uuid4()
        background = QImage(240, 180, QImage.Format_ARGB32_Premultiplied)
        background.fill(QColor("black"))
        window.qpane.setImagesByID(
            CuteCanvas.imageMapFromLists([background], ids=[image_id]),
            image_id,
        )
        placed = QImage(64, 48, QImage.Format_ARGB32_Premultiplied)
        placed.fill(QColor(220, 40, 80, 255))
        layer_id = window.qpane.placeEmbeddedAsset(
            placed,
            placement=QRectF(50.0, 40.0, 64.0, 48.0),
            label="Rasterize me",
        )
        scene = window.qpane.currentScene()
        assert scene is not None and layer_id is not None
        assert window.qpane.setSelectedLayer(scene.scene_id, layer_id)
        selection = QImage(16, 12, QImage.Format_Grayscale8)
        selection.fill(255)
        assert window.qpane.setPixelSelection(selection, QRect(58, 46, 16, 12))
        completions: list[tuple[object, ...]] = []
        window.qpane.placedAssetRequestCompleted.connect(
            lambda *values: completions.append(tuple(values))
        )
        rasterization_started = threading.Event()
        rasterize = LayerRasterizer.rasterize

        def held_rasterization(source: QImage, pixel_size: QSize) -> QImage:
            """Hold the real worker so pre-completion UI behavior is observable."""
            rasterization_started.set()
            if not release_rasterization.wait(3.0):
                raise TimeoutError("test did not release placed rasterization")
            return rasterize(source, pixel_size)

        monkeypatch.setattr(
            LayerRasterizer,
            "rasterize",
            staticmethod(held_rasterization),
        )
        window.resize(900, 650)
        window.show()
        window.activateWindow()
        window.qpane.setFocus(Qt.FocusReason.OtherFocusReason)
        qapp.processEvents()
        inspector = PlacedAssetControls(
            window.qpane,
            window,
            show_status=window.status_ui.show_message,
        )
        inspector.set_target(scene.scene_id, layer_id)
        inspector.show()
        qapp.processEvents()
        controls = inspector
        assert controls.isVisible()

        controls._rasterize.click()
        _wait_for(qapp, rasterization_started.is_set)
        assert controls._rasterize.text() == "Rasterizing…"
        assert not controls._rasterize.isEnabled()
        assert "Pixel editing will be available" in window.status.currentMessage()

        QTest.keyClick(window.qpane, Qt.Key_Delete)
        qapp.processEvents()
        assert "not ready for pixel editing" in window.status.currentMessage()
        assert (
            next(
                layer
                for layer in window.qpane.currentScene().layers
                if layer.layer_id == layer_id
            ).source_kind
            == "placed-asset"
        )

        release_rasterization.set()
        _wait_for(
            qapp,
            lambda: any(values[3] is True for values in completions),
        )
        assert "ready for pixel editing" in window.status.currentMessage()

        rasterized_scene = window.qpane.currentScene()
        assert rasterized_scene is not None
        rasterized = next(
            layer for layer in rasterized_scene.layers if layer.layer_id == layer_id
        )
        assert rasterized.source_kind == "raster"
        assert rasterized.interaction.pixel_editable
        assert window.qpane.undoSceneEdit()
        restored_placed = next(
            layer
            for layer in window.qpane.currentScene().layers
            if layer.layer_id == layer_id
        )
        assert restored_placed.source_kind == "placed-asset"
        assert restored_placed.interaction.movable
        assert not restored_placed.interaction.pixel_editable
        assert window.qpane.redoSceneEdit()
        redone_raster = next(
            layer
            for layer in window.qpane.currentScene().layers
            if layer.layer_id == layer_id
        )
        assert redone_raster.source_kind == "raster"
        assert redone_raster.interaction.pixel_editable
        QTest.keyClick(window.qpane, Qt.Key_Delete)
        qapp.processEvents()

        deleted = window.qpane.editableRasterLayerImage(scene.scene_id, layer_id)
        assert deleted is not None
        assert deleted.pixelColor(8, 6).alpha() == 0
        assert deleted.pixelColor(30, 24).alpha() == 255
        assert window.qpane.undoSceneEdit()
        restored = window.qpane.editableRasterLayerImage(scene.scene_id, layer_id)
        assert restored is not None and restored.pixelColor(8, 6).alpha() == 255

        window.tools.set_mode(CuteCanvas.CONTROL_MODE_MOVE)
        internal_scene = window.qpane.view().current_scene_descriptor()
        assert internal_scene is not None
        start = window.qpane.view().layer_source_to_panel_point(
            internal_scene.scene_id,
            layer_id,
            QPointF(12.0, 10.0),
        )
        finish = window.qpane.view().layer_source_to_panel_point(
            internal_scene.scene_id,
            layer_id,
            QPointF(28.0, 10.0),
        )
        assert start is not None and finish is not None
        QTest.mousePress(
            window.qpane,
            Qt.LeftButton,
            Qt.NoModifier,
            start.toPoint(),
        )
        QTest.mouseMove(window.qpane, finish.toPoint(), delay=0)
        QTest.mouseRelease(
            window.qpane,
            Qt.LeftButton,
            Qt.NoModifier,
            finish.toPoint(),
        )
        qapp.processEvents()
        floating = window.qpane.floatingPixelEditState()
        assert floating is not None and floating.offset.x() > 0
        assert window.qpane.anchorFloatingPixels()
        moved = window.qpane.editableRasterLayerImage(scene.scene_id, layer_id)
        assert moved is not None
        assert moved.pixelColor(8, 6).alpha() == 0
        assert moved.pixelColor(24, 6).alpha() == 255
    finally:
        release_rasterization.set()
        if inspector is not None:
            inspector.close()
            inspector.deleteLater()
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_demo_rasterized_vector_layer_is_immediately_pixel_editable(qapp) -> None:
    """Every semantic-to-raster source swap must refresh demo edit policy."""
    window = ExampleWindow(ExampleOptions(feature_set="core"))
    try:
        image_id = uuid.uuid4()
        background = QImage(240, 180, QImage.Format_ARGB32_Premultiplied)
        background.fill(QColor("black"))
        window.qpane.setImagesByID(
            CuteCanvas.imageMapFromLists([background], ids=[image_id]),
            image_id,
        )
        scene = window.qpane.currentScene()
        assert scene is not None
        layer_id = window.qpane.createVectorLayer(QSize(240, 180), label="Vector")
        assert layer_id is not None
        assert window.qpane.setSelectedLayer(scene.scene_id, layer_id)
        assert (
            window.qpane.addVectorShape(
                scene.scene_id,
                layer_id,
                VectorShapeKind.RECTANGLE,
                QRectF(40.0, 30.0, 80.0, 60.0),
            )
            is not None
        )
        completions: list[tuple[object, ...]] = []
        window.qpane.vectorRequestCompleted.connect(
            lambda *values: completions.append(tuple(values))
        )

        request_id = window.qpane.rasterizeVectorLayer(scene.scene_id, layer_id)
        assert request_id is not None
        _wait_for(
            qapp,
            lambda: any(
                values[0] == request_id and values[4] is True for values in completions
            ),
        )

        rasterized_scene = window.qpane.currentScene()
        assert rasterized_scene is not None
        rasterized = next(
            layer for layer in rasterized_scene.layers if layer.layer_id == layer_id
        )
        assert rasterized.source_kind == "raster"
        assert rasterized.interaction.pixel_editable
        assert window.qpane.rasterSurfaceState(scene.scene_id, layer_id) is not None
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()
