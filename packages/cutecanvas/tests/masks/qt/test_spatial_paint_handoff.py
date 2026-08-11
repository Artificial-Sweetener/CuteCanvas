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

"""Rendered continuity proof for the first raster edit of transformed masks."""

from __future__ import annotations

from cutecanvas import CuteCanvas
from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qpane.sdk.scene import BilinearLayerTransform


def test_first_eraser_press_never_double_transforms_projected_vector_coverage(
    qapp: QApplication,
) -> None:
    """Raster adoption must not expose the projected mask through its old mapping."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1600, 1000),
        widget_size=QSize(1082, 639),
        mask_count=1,
        brush_size=64,
    )
    viewer = harness.viewer
    try:
        mask_id = harness.mask_ids[0]
        assert viewer.editor.coverage.rectangle(QRectF(800.0, 0.0, 800.0, 1000.0))
        entry = viewer.listMasksForComposition()[0]
        assert entry.scene_id is not None and entry.layer_id is not None
        assert entry.interaction.pixel_editable
        assert viewer.setControlMode(viewer.CONTROL_MODE_ERASER)
        mapping = BilinearLayerTransform(
            (
                QPointF(800.0, 0.0),
                QPointF(1600.0, 0.0),
                QPointF(1600.0, 1000.0),
                QPointF(800.0, 1000.0),
            ),
            (
                QPointF(1600.0, 0.0),
                QPointF(1600.0, 0.0),
                QPointF(1600.0, 1000.0),
                QPointF(0.0, 1000.0),
            ),
        )
        assert viewer.setLayerTransform(entry.scene_id, entry.layer_id, mapping)
        assert harness.wait_for_mask_render_idle(timeout_ms=3000)
        assert harness.wait_for_render_refinement_idle(timeout_ms=3000)

        remote_coverage = _panel_point(viewer, QPointF(1200.0, 300.0))
        erase_point = _panel_point(viewer, QPointF(900.0, 800.0))
        assert harness.is_mask_tint(harness.color_at(remote_coverage))

        with harness.observe_presented_frames() as probe:
            QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=erase_point)
            viewer.repaint()
            assert probe.frames
            assert not harness.is_mask_tint(probe.frames[-1].color_at(erase_point))
            harness.drain_events()
            QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=erase_point)
            assert harness.wait_for_mask_render_idle(timeout_ms=3000)
            assert harness.wait_for_render_refinement_idle(timeout_ms=3000)
            viewer.repaint()

        assert probe.frames
        assert all(
            harness.is_mask_tint(frame.color_at(remote_coverage))
            for frame in probe.frames
        ), tuple(
            (
                frame.color_at(remote_coverage).getRgb(),
                frame.mask_item_states,
            )
            for frame in probe.frames
        )
        asset = viewer.mask_service.assets.get_layer(mask_id)
        assert asset is not None and not asset.coverage.has_retained_items
        assert viewer.layerTransform(entry.scene_id, entry.layer_id).isIdentity()
        assert asset.coverage.coverage_value(900, 800) == 0
        assert asset.coverage.coverage_value(1200, 300) == 255
    finally:
        harness.close()


def _panel_point(viewer: CuteCanvas, scene_point: QPointF) -> QPoint:
    """Project one scene point into the mounted panel."""
    projected = viewer.view().scene_to_panel_point(scene_point)
    if projected is None:
        raise AssertionError("scene point must project into the mounted panel")
    return projected.toPoint()
