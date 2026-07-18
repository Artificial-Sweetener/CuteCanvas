#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Public-API integration coverage for the demo raster layer inspector."""

from __future__ import annotations

import time
import uuid

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from examples.demonstration.layer_inspector import RasterLayerInspector
from qpane import QPane, RasterExtentPolicy
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
    viewer = QPane(features=("mask",))
    image_id = uuid.uuid4()
    image = QImage(12, 10, QImage.Format_RGB32)
    viewer.setImagesByID(QPane.imageMapFromLists([image], ids=[image_id]), image_id)
    mask_id = viewer.createBlankMask(image.size())
    assert mask_id is not None
    assert viewer.setActiveMaskID(mask_id)
    inspector = RasterLayerInspector(viewer)
    try:
        mask = viewer.listMasksForImage()[0]
        assert mask.scene_id is not None
        assert mask.layer_id is not None
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
    viewer = QPane(features=("mask",))
    image_id = uuid.uuid4()
    image = QImage(40, 30, QImage.Format_RGB32)
    viewer.setImagesByID(QPane.imageMapFromLists([image], ids=[image_id]), image_id)
    mask_id = viewer.createBlankMask(image.size())
    assert mask_id is not None
    assert viewer.setActiveMaskID(mask_id)
    inspector = RasterLayerInspector(viewer)
    requested = QRect(-8, -6, 56, 44)
    try:
        mask = viewer.listMasksForImage()[0]
        assert mask.scene_id is not None
        assert mask.layer_id is not None
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
    inspector = RasterLayerInspector(harness.viewer)
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

        mask = harness.viewer.listMasksForImage()[0]
        assert mask.scene_id is not None
        assert mask.layer_id is not None
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
