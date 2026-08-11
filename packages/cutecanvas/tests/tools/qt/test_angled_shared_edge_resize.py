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

"""Mounted continuity proof for repeatedly manipulating an angled shared edge."""

from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Protocol, cast

import pytest
from cutecanvas import LayerPolicy
from cutecanvas.scene.mapping_preview import SceneLayerMappingPreview
from cutecanvas_test_support.harness.mounted_qpane import (
    MountedQPaneHarness,
    PresentedMaskFrame,
)
from cutecanvas_test_support.repository import repository_root
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qpane.rendering.view import View
from qpane.sdk.scene import PiecewiseLayerTransform

_HIGH_DPI_PROBE = "CUTECANVAS_SHARED_EDGE_HIGH_DPI_PROBE"


class _MountedViewerRuntime(Protocol):
    """Expose the internal presentation state required by mounted proof."""

    _scene_mapping_preview: SceneLayerMappingPreview

    def view(self) -> View:
        """Return the mounted rendering view."""
        ...


def test_angled_shared_edge_keeps_endpoint_and_suppresses_midpoint(qapp) -> None:
    """Angled seams retain point editing without exposing side translation."""
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
        assert viewer.editor.coverage.rectangle(QRectF(80.0, 80.0, 80.0, 100.0))
        harness.activate_mask(1)
        assert viewer.editor.coverage.rectangle(QRectF(160.0, 80.0, 80.0, 160.0))
        harness.activate_mask(0)
        assert harness.wait_for_mask_render_idle()
        assert harness.wait_for_render_refinement_idle(timeout_ms=20_000)
        entries = {entry.mask_id: entry for entry in viewer.listMasksForComposition()}
        first = entries[first_id]
        second = entries[second_id]
        assert first.scene_id is not None and first.layer_id is not None
        assert second.layer_id is not None
        policy = LayerPolicy(selectable=True, movable=True, pixel_editable=True)
        viewer.setLayerInteractionPolicy(first.scene_id, first.layer_id, policy)
        viewer.setLayerInteractionPolicy(first.scene_id, second.layer_id, policy)
        assert viewer.setControlMode(viewer.CONTROL_MODE_SHARED_EDGE_RESIZE)

        pivot_start = _panel_point(runtime, QPointF(160.0, 80.0))
        pivot_target = _panel_point(runtime, QPointF(180.0, 80.0))
        QTest.mouseMove(viewer, pivot_start)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=pivot_start)
        QTest.mouseMove(viewer, pivot_target, delay=0)
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=pivot_target)
        harness.drain_events()

        angled = _preview_mappings(runtime)[first.layer_id]
        assert isinstance(angled, PiecewiseLayerTransform)
        source_start = QPointF(160.0, 80.0)
        source_end = QPointF(160.0, 180.0)
        angled_start = angled.map_point(source_start)
        endpoint_start = _panel_point(runtime, angled_start)
        endpoint_target = _panel_point(runtime, angled_start + QPointF(10.0, 0.0))
        QTest.mouseMove(viewer, endpoint_start)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=endpoint_start)
        QTest.mouseMove(viewer, endpoint_target, delay=0)
        assert len(runtime._scene_mapping_preview.previews) == 2
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=endpoint_target)
        harness.drain_events()

        endpoint_previews = _preview_mappings(runtime)
        endpoint_adjusted = endpoint_previews[first.layer_id]
        assert isinstance(endpoint_adjusted, PiecewiseLayerTransform)
        adjusted_start = endpoint_adjusted.map_point(source_start)
        adjusted_end = endpoint_adjusted.map_point(source_end)
        assert adjusted_start.x() > angled_start.x() + 5.0
        midpoint = (adjusted_start + adjusted_end) * 0.5
        seam = adjusted_end - adjusted_start
        seam_length = math.hypot(seam.x(), seam.y())
        displacement = QPointF(seam.y(), -seam.x()) * (16.0 / seam_length)
        drag_start = _panel_point(runtime, midpoint)
        drag_target = _panel_point(runtime, midpoint + displacement)
        second_before = endpoint_previews[second.layer_id]
        retained_points = (
            _panel_point(runtime, QPointF(100.0, 140.0)),
            _panel_point(runtime, QPointF(210.0, 210.0)),
        )

        with harness.observe_presented_frames() as probe:
            QTest.mouseMove(viewer, drag_start)
            QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=drag_start)
            QTest.mouseMove(viewer, drag_target, delay=0)
            assert _preview_mappings(runtime) == endpoint_previews
            QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=drag_target)
            assert harness.wait_for_mask_render_idle(timeout_ms=20_000)
            assert harness.wait_for_render_refinement_idle(timeout_ms=20_000)
            viewer.repaint()

        assert _preview_mappings(runtime) == endpoint_previews
        assert probe.frames
        assert all(frame.mask_layer_count == 2 for frame in probe.frames)
        assert all(
            harness.is_mask_tint(frame.color_at(point))
            for frame in probe.frames
            for point in retained_points
        )
        QTest.keyClick(viewer, Qt.Key.Key_Return)
        assert (
            viewer.layerTransform(first.scene_id, first.layer_id) == endpoint_adjusted
        )
        assert viewer.layerTransform(first.scene_id, second.layer_id) == second_before
    finally:
        harness.close()


def test_angled_endpoint_drag_storm_never_drops_current_mask_coverage() -> None:
    """Every 1.75x live frame retains coverage through repeated point movement."""
    if os.environ.get(_HIGH_DPI_PROBE) != "1":
        environment = dict(os.environ)
        tests_root = Path(__file__).resolve().parents[2]
        python_path = environment.get("PYTHONPATH")
        environment.update(
            {
                _HIGH_DPI_PROBE: "1",
                "PYTHONPATH": (
                    str(tests_root)
                    if not python_path
                    else os.pathsep.join((str(tests_root), python_path))
                ),
                "QT_QPA_PLATFORM": "offscreen",
                "QT_SCALE_FACTOR": "1.75",
            }
        )
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--high-dpi-probe"],
            cwd=repository_root(),
            env=environment,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        return
    qapp = QApplication.instance() or QApplication(sys.argv[:1])
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(3440, 1440),
        widget_size=QSize(1088, 903),
        mask_count=2,
    )
    viewer = harness.viewer
    runtime = cast(_MountedViewerRuntime, viewer)
    try:
        assert viewer.devicePixelRatioF() == pytest.approx(1.75)
        first_id, second_id = harness.mask_ids
        assert viewer.editor.coverage.rectangle(QRectF(640.0, 200.0, 800.0, 800.0))
        harness.activate_mask(1)
        assert viewer.editor.coverage.rectangle(QRectF(1440.0, 200.0, 800.0, 1100.0))
        harness.activate_mask(0)
        assert harness.wait_for_mask_render_idle()
        assert harness.wait_for_render_refinement_idle(timeout_ms=20_000)
        entries = {entry.mask_id: entry for entry in viewer.listMasksForComposition()}
        first = entries[first_id]
        second = entries[second_id]
        assert first.scene_id is not None and first.layer_id is not None
        assert second.layer_id is not None
        policy = LayerPolicy(selectable=True, movable=True, pixel_editable=True)
        viewer.setLayerInteractionPolicy(first.scene_id, first.layer_id, policy)
        viewer.setLayerInteractionPolicy(first.scene_id, second.layer_id, policy)
        assert viewer.setControlMode(viewer.CONTROL_MODE_SHARED_EDGE_RESIZE)

        drag_start = _panel_point(runtime, QPointF(1440.0, 200.0))
        targets = (1520.0, 1600.0, 1480.0, 1560.0, 1500.0, 1580.0) * 3

        with harness.observe_presented_frames() as probe:
            QTest.mouseMove(viewer, drag_start)
            QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=drag_start)
            for target_x in targets:
                before = len(probe.frames)
                target = _panel_point(runtime, QPointF(target_x, 200.0))
                QTest.mouseMove(viewer, target, delay=0)
                harness.drain_events(wait_ms=40)
                assert len(probe.frames) > before
                previews = {
                    preview.layer_id: preview.mapping
                    for preview in runtime._scene_mapping_preview.previews
                }
                assert set(previews) == {first.layer_id, second.layer_id}
                current_points = (
                    _panel_point(
                        runtime,
                        previews[first.layer_id].map_point(QPointF(800.0, 600.0)),
                    ),
                    _panel_point(
                        runtime,
                        previews[second.layer_id].map_point(QPointF(2000.0, 800.0)),
                    ),
                )
                assert all(
                    harness.is_mask_tint(_physical_frame_color(frame, point))
                    for frame in probe.frames[before:]
                    for point in current_points
                ), (
                    target_x,
                    tuple(frame.mask_item_states for frame in probe.frames[before:]),
                )
            QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=target)
            assert harness.wait_for_mask_render_idle(timeout_ms=20_000)
            assert harness.wait_for_render_refinement_idle(timeout_ms=20_000)

        assert probe.frames
        assert all(frame.mask_layer_count == 2 for frame in probe.frames)
    finally:
        harness.close()


def _panel_point(viewer: _MountedViewerRuntime, scene_point: QPointF) -> QPoint:
    """Return an integer panel point for one visible scene position."""
    panel = viewer.view().scene_to_panel_point(scene_point)
    assert panel is not None
    return panel.toPoint()


def _preview_mappings(
    viewer: _MountedViewerRuntime,
) -> dict[object, object]:
    """Return the current provisional mapping by participant layer."""
    return {
        preview.layer_id: preview.mapping
        for preview in viewer._scene_mapping_preview.previews
    }


def _physical_frame_color(frame: PresentedMaskFrame, point: QPoint) -> QColor:
    """Sample one logical panel point from a physical backing frame."""
    image = frame.image
    device_pixel_ratio = image.devicePixelRatio()
    return image.pixelColor(
        round(point.x() * device_pixel_ratio) + frame.overscan_margin,
        round(point.y() * device_pixel_ratio) + frame.overscan_margin,
    )


if __name__ == "__main__":
    if sys.argv[1:] != ["--high-dpi-probe"]:
        raise SystemExit("expected --high-dpi-probe")
    os.environ[_HIGH_DPI_PROBE] = "1"
    test_angled_endpoint_drag_storm_never_drops_current_mask_coverage()
