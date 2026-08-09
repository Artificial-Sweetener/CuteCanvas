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

"""Mounted demo-policy proof for Shared Edge Resize."""

from __future__ import annotations

import uuid

import pytest
from cutecanvas import CuteCanvas, VectorShapeKind
from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness
from demonstration.layer_policy import DemoLayerPolicyController
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtTest import QTest
from qpane.sdk.scene import LayerDescriptor


def test_demo_shared_edge_mode_enables_both_adjacent_mask_layers(qapp) -> None:
    """The demo must make both participants movable when the coupled tool owns input."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 300),
        widget_size=QSize(800, 620),
        mask_count=1,
    )
    viewer = harness.viewer
    policy = DemoLayerPolicyController(viewer)
    try:
        first_id = harness.mask_ids[0]
        _add_rectangle(viewer, first_id, QRectF(80.0, 80.0, 80.0, 100.0))
        second_id = _rectangle_mask(viewer, QRectF(160.0, 80.0, 80.0, 100.0))
        policy.reconcile()
        first, second = _mask_layers(viewer, first_id, second_id)
        assert not first.interaction.movable
        assert second.interaction.movable

        assert viewer.setControlMode(viewer.CONTROL_MODE_SHARED_EDGE_RESIZE)
        harness.drain_events()
        first, second = _mask_layers(viewer, first_id, second_id)
        assert first.interaction.movable
        assert second.interaction.movable

        start = _panel_point(viewer, QPointF(160.0, 130.0))
        end = _panel_point(viewer, QPointF(180.0, 130.0))
        QTest.mouseMove(viewer, start)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewer, end, delay=0)
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=end)
        harness.drain_events()

        first, second = _mask_layers(viewer, first_id, second_id)
        assert first.transform is not None and second.transform is not None
        assert first.transform.m11() == pytest.approx(1.25, abs=0.02)
        assert second.transform.m11() == pytest.approx(0.75, abs=0.02)
    finally:
        policy.deleteLater()
        harness.close()


def _rectangle_mask(viewer: CuteCanvas, bounds: QRectF) -> uuid.UUID:
    """Create one active retained rectangle mask through public APIs."""
    mask_id = viewer.createBlankMask(QSize(400, 300))
    assert mask_id is not None
    _add_rectangle(viewer, mask_id, bounds)
    return mask_id


def _add_rectangle(
    viewer: CuteCanvas,
    mask_id: uuid.UUID,
    bounds: QRectF,
) -> None:
    """Author one retained rectangle into an existing mask."""
    viewer.setActiveMaskID(mask_id)
    assert viewer.addCoverageShape(VectorShapeKind.RECTANGLE, bounds) is not None


def _mask_layers(
    viewer: CuteCanvas,
    first_id: uuid.UUID,
    second_id: uuid.UUID,
) -> tuple[LayerDescriptor, LayerDescriptor]:
    """Return the current descriptors for two mask resources."""
    entries = {entry.mask_id: entry for entry in viewer.listMasksForComposition()}
    layer_ids = {entries[first_id].layer_id, entries[second_id].layer_id}
    scene = viewer.currentScene()
    assert scene is not None and None not in layer_ids
    layers = {layer.layer_id: layer for layer in scene.layers}
    return layers[entries[first_id].layer_id], layers[entries[second_id].layer_id]


def _panel_point(viewer: CuteCanvas, scene_point: QPointF) -> QPoint:
    """Return an integer panel point for one visible scene point."""
    panel = viewer.view().scene_to_panel_point(scene_point)
    assert panel is not None
    return panel.toPoint()
