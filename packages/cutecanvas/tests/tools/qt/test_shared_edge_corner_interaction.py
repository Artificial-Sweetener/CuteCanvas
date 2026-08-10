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

"""Mounted interactivity and coverage proof for joined seam endpoints."""

from __future__ import annotations

from typing import Protocol, cast

from cutecanvas import CuteCanvas, LayerPolicy
from cutecanvas.scene.mapping_preview import SceneLayerMappingPreview
from cutecanvas_test_support.harness.mounted_qpane import (
    MountedQPaneHarness,
    PresentedMaskFrame,
)
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtTest import QTest
from qpane.rendering.view import View
from qpane.sdk.scene import BilinearLayerTransform


class _MountedViewerRuntime(Protocol):
    """Expose live presentation state needed by the interaction proof."""

    _scene_mapping_preview: SceneLayerMappingPreview

    def view(self) -> View:
        """Return the mounted rendering view."""
        ...


def test_joined_endpoint_reopens_and_opposite_endpoint_remains_editable(qapp) -> None:
    """Joined handles reopen without undo while paired coverage stays complete."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 300),
        widget_size=QSize(800, 620),
        mask_count=2,
    )
    viewer = harness.viewer
    runtime = cast(_MountedViewerRuntime, viewer)
    try:
        first_id, second_id = harness.mask_ids
        assert viewer.editor.coverage.rectangle(QRectF(0.0, 0.0, 200.0, 300.0))
        harness.activate_mask(1)
        assert viewer.editor.coverage.rectangle(QRectF(200.0, 0.0, 200.0, 300.0))
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

        _drag(runtime, viewer, QPointF(200.0, 0.0), QPointF(0.0, 0.0))
        harness.drain_events()
        assert isinstance(
            viewer.layerTransform(first.scene_id, first.layer_id),
            BilinearLayerTransform,
        )

        with harness.observe_presented_frames() as reopened_probe:
            _begin_drag(runtime, viewer, QPointF(0.0, 0.0), QPointF(50.0, 0.0))
            assert {
                preview.layer_id for preview in runtime._scene_mapping_preview.previews
            } == {first.layer_id, second.layer_id}
            QTest.mouseRelease(
                viewer,
                Qt.MouseButton.LeftButton,
                pos=_panel_point(runtime, QPointF(50.0, 0.0)),
            )
            _wait_for_final_frame(harness)
        _assert_canvas_coverage(harness, runtime, reopened_probe.frames)

        with harness.observe_presented_frames() as opposite_probe:
            _begin_drag(runtime, viewer, QPointF(200.0, 300.0), QPointF(400.0, 300.0))
            assert {
                preview.layer_id for preview in runtime._scene_mapping_preview.previews
            } == {first.layer_id, second.layer_id}
            QTest.mouseRelease(
                viewer,
                Qt.MouseButton.LeftButton,
                pos=_panel_point(runtime, QPointF(400.0, 300.0)),
            )
            _wait_for_final_frame(harness)

        first_mapping = viewer.layerTransform(first.scene_id, first.layer_id)
        second_mapping = viewer.layerTransform(first.scene_id, second.layer_id)
        assert first_mapping is not None and second_mapping is not None
        for mapping in (first_mapping, second_mapping):
            assert mapping.map_point(QPointF(200.0, 0.0)) == QPointF(50.0, 0.0)
            assert mapping.map_point(QPointF(200.0, 300.0)) == QPointF(400.0, 300.0)
        assert all(
            frame.mask_layer_count == 2 for frame in opposite_probe.frames
        ), tuple(frame.mask_item_states for frame in opposite_probe.frames)
        _assert_canvas_coverage(harness, runtime, opposite_probe.frames)

        _begin_drag(runtime, viewer, QPointF(400.0, 300.0), QPointF(350.0, 300.0))
        assert {
            preview.layer_id for preview in runtime._scene_mapping_preview.previews
        } == {first.layer_id, second.layer_id}
        QTest.keyClick(viewer, Qt.Key.Key_Escape)
    finally:
        harness.close()


def _drag(
    runtime: _MountedViewerRuntime,
    viewer: CuteCanvas,
    start: QPointF,
    end: QPointF,
) -> None:
    """Complete one shared-edge endpoint drag."""
    _begin_drag(runtime, viewer, start, end)
    QTest.mouseRelease(
        viewer,
        Qt.MouseButton.LeftButton,
        pos=_panel_point(runtime, end),
    )


def _begin_drag(
    runtime: _MountedViewerRuntime,
    viewer: CuteCanvas,
    start: QPointF,
    end: QPointF,
) -> None:
    """Begin one endpoint drag and leave it active at ``end``."""
    start_point = _panel_point(runtime, start)
    QTest.mouseMove(viewer, start_point)
    QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start_point)
    QTest.mouseMove(viewer, _panel_point(runtime, end), delay=0)


def _wait_for_final_frame(harness: MountedQPaneHarness) -> None:
    """Wait for committed mask products and publish their refined frame."""
    assert harness.wait_for_mask_render_idle(timeout_ms=3000)
    assert harness.wait_for_render_refinement_idle(timeout_ms=3000)
    harness.viewer.repaint()


def _panel_point(viewer: _MountedViewerRuntime, scene_point: QPointF) -> QPoint:
    """Return an integer panel point for one visible scene position."""
    panel = viewer.view().scene_to_panel_point(scene_point)
    assert panel is not None
    return panel.toPoint()


def _assert_canvas_coverage(
    harness: MountedQPaneHarness,
    viewer: _MountedViewerRuntime,
    frames: list[PresentedMaskFrame],
) -> None:
    """Assert representative points retain union coverage across the canvas."""
    assert frames
    scene_points = tuple(
        QPointF(x, y) for y in (10.0, 150.0, 290.0) for x in (10.0, 200.0, 390.0)
    )
    points = tuple(_panel_point(viewer, point) for point in scene_points)
    assert all(harness.is_mask_tint(frames[-1].color_at(point)) for point in points)
