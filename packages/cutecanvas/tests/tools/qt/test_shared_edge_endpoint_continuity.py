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

"""Mounted continuity proof at shared-edge endpoint rail limits."""

from __future__ import annotations

import logging
from typing import Protocol, cast

import pytest
from cutecanvas import LayerPolicy
from cutecanvas.scene.mapping_preview import SceneLayerMappingPreview
from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QPainterPath, QPainterPathStroker, QPolygonF
from PySide6.QtTest import QTest
from qpane.rendering.view import View
from qpane.sdk.scene import BilinearLayerTransform, PiecewiseLayerTransform

_BoundedMapping = PiecewiseLayerTransform | BilinearLayerTransform


class _MountedViewerRuntime(Protocol):
    """Expose the presentation state needed to verify a live paired mapping."""

    _scene_mapping_preview: SceneLayerMappingPreview

    def view(self) -> View:
        """Return the mounted rendering view."""
        ...


@pytest.mark.parametrize("second_height", (800.0, 1100.0))
def test_endpoint_sweep_to_both_rail_limits_never_drops_a_mask(
    qapp,
    caplog,
    second_height: float,
) -> None:
    """Repeated corner-limit pivots must retain both mapped mask interiors."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(3440, 1440),
        widget_size=QSize(1088, 903),
        mask_count=2,
    )
    viewer = harness.viewer
    runtime = cast(_MountedViewerRuntime, viewer)
    try:
        first_id, second_id = harness.mask_ids
        assert viewer.editor.coverage.rectangle(QRectF(640.0, 200.0, 800.0, 800.0))
        harness.activate_mask(1)
        assert viewer.editor.coverage.rectangle(
            QRectF(1440.0, 200.0, 800.0, second_height)
        )
        harness.activate_mask(0)
        assert harness.wait_for_mask_render_idle()
        assert harness.wait_for_render_refinement_idle(timeout_ms=3000)
        entries = {entry.mask_id: entry for entry in viewer.listMasksForComposition()}
        first = entries[first_id]
        second = entries[second_id]
        assert first.scene_id is not None and first.layer_id is not None
        assert second.layer_id is not None
        policy = LayerPolicy(selectable=True, movable=True, pixel_editable=True)
        viewer.setLayerInteractionPolicy(first.scene_id, first.layer_id, policy)
        viewer.setLayerInteractionPolicy(first.scene_id, second.layer_id, policy)
        assert viewer.setControlMode(viewer.CONTROL_MODE_SHARED_EDGE_RESIZE)

        start = _panel_point(runtime, QPointF(1440.0, 200.0))
        with harness.observe_presented_frames() as probe:
            QTest.mouseMove(viewer, start)
            QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
            for target_x in (2239.0, 641.0, 2238.0, 642.0, 2239.0, 641.0):
                before = len(probe.frames)
                QTest.mouseMove(
                    viewer,
                    _panel_point(runtime, QPointF(target_x, 200.0)),
                    delay=0,
                )
                harness.drain_events(wait_ms=40)
                assert len(probe.frames) > before
                previews = {
                    preview.layer_id: preview.mapping
                    for preview in runtime._scene_mapping_preview.previews
                }
                assert set(previews) == {first.layer_id, second.layer_id}
                assert all(
                    isinstance(
                        mapping, (PiecewiseLayerTransform, BilinearLayerTransform)
                    )
                    for mapping in previews.values()
                )
                if second_height == 800.0:
                    assert any(
                        isinstance(mapping, BilinearLayerTransform)
                        for mapping in previews.values()
                    )
                assert probe.frames[-1].mask_layer_count == 2
                assert all(
                    frame.mask_layer_count == 2 for frame in probe.frames[before:]
                )
                for layer_id, mapping in previews.items():
                    if not isinstance(
                        mapping,
                        (PiecewiseLayerTransform, BilinearLayerTransform),
                    ):
                        continue
                    interior = _interior_panel_points(
                        runtime,
                        mapping,
                    )
                    missing = tuple(
                        point
                        for point in interior
                        if not harness.is_mask_tint(probe.frames[-1].color_at(point))
                    )
                    assert not missing, (
                        target_x,
                        layer_id,
                        type(mapping).__name__,
                        len(missing),
                        missing[:10],
                        probe.frames[-1].mask_item_states,
                    )
            QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton)
        assert not tuple(
            record for record in caplog.records if record.levelno >= logging.ERROR
        )
    finally:
        harness.close()


def test_45_degree_snap_preview_and_commit_retain_both_masks(qapp) -> None:
    """Perfect-slant snapping must never publish partial participant coverage."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(300, 200),
        widget_size=QSize(800, 620),
        mask_count=2,
    )
    viewer = harness.viewer
    runtime = cast(_MountedViewerRuntime, viewer)
    try:
        first_id, second_id = harness.mask_ids
        assert viewer.editor.coverage.rectangle(QRectF(0.0, 0.0, 150.0, 100.0))
        harness.activate_mask(1)
        assert viewer.editor.coverage.rectangle(QRectF(150.0, 0.0, 150.0, 100.0))
        harness.activate_mask(0)
        assert harness.wait_for_mask_render_idle()
        assert harness.wait_for_render_refinement_idle(timeout_ms=3000)
        entries = {entry.mask_id: entry for entry in viewer.listMasksForComposition()}
        first = entries[first_id]
        second = entries[second_id]
        assert first.scene_id is not None and first.layer_id is not None
        assert second.layer_id is not None
        policy = LayerPolicy(selectable=True, movable=True, pixel_editable=True)
        viewer.setLayerInteractionPolicy(first.scene_id, first.layer_id, policy)
        viewer.setLayerInteractionPolicy(first.scene_id, second.layer_id, policy)
        assert viewer.setControlMode(viewer.CONTROL_MODE_SHARED_EDGE_RESIZE)
        start = _panel_point(runtime, QPointF(150.0, 0.0))
        near_perfect_slant = _panel_point(runtime, QPointF(52.0, 0.0))
        retained = (
            _panel_point(runtime, QPointF(50.0, 75.0)),
            _panel_point(runtime, QPointF(250.0, 50.0)),
        )

        with harness.observe_presented_frames() as probe:
            QTest.mouseMove(viewer, start)
            QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(viewer, near_perfect_slant, delay=0)
            QTest.mouseRelease(
                viewer,
                Qt.MouseButton.LeftButton,
                pos=near_perfect_slant,
            )
            assert harness.wait_for_mask_render_idle(timeout_ms=3000)
            assert harness.wait_for_render_refinement_idle(timeout_ms=3000)
            viewer.repaint()

        first_mapping = viewer.layerTransform(first.scene_id, first.layer_id)
        second_mapping = viewer.layerTransform(first.scene_id, second.layer_id)
        assert first_mapping is not None and second_mapping is not None
        assert first_mapping.map_point(QPointF(150.0, 0.0)) == QPointF(50.0, 0.0)
        assert second_mapping.map_point(QPointF(150.0, 0.0)) == QPointF(50.0, 0.0)
        assert probe.frames
        assert all(frame.mask_layer_count == 2 for frame in probe.frames), tuple(
            frame.mask_item_states for frame in probe.frames
        )
        assert all(
            harness.is_mask_tint(frame.color_at(point))
            for frame in probe.frames
            for point in retained
        )
    finally:
        harness.close()


def _panel_point(viewer: _MountedViewerRuntime, scene_point: QPointF) -> QPoint:
    """Return an integer panel point for one visible scene position."""
    panel = viewer.view().scene_to_panel_point(scene_point)
    assert panel is not None
    return panel.toPoint()


def _interior_panel_points(
    viewer: _MountedViewerRuntime,
    mapping: _BoundedMapping,
) -> tuple[QPoint, ...]:
    """Return every logical panel pixel safely inside one collapsed shape."""
    panel_points: list[QPointF] = []
    for point in mapping.target_boundary:
        panel_point = viewer.view().scene_to_panel_point(point)
        assert panel_point is not None
        panel_points.append(panel_point)
    polygon = QPolygonF(panel_points)
    path = QPainterPath()
    path.addPolygon(polygon)
    path.closeSubpath()
    stroker = QPainterPathStroker()
    stroker.setWidth(4.0)
    interior = path.subtracted(stroker.createStroke(path))
    bounds = interior.boundingRect().toAlignedRect()
    return tuple(
        QPoint(x, y)
        for y in range(bounds.top(), bounds.bottom() + 1)
        for x in range(bounds.left(), bounds.right() + 1)
        if interior.contains(QPointF(x + 0.5, y + 0.5))
    )
