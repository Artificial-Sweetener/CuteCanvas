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
"""Frame-continuity proof for raster edits of retained mask coverage."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from cutecanvas import CuteCanvas
from cutecanvas_test_support.harness.mounted_qpane import (
    MountedQPaneHarness,
    PresentedMaskFrame,
)
from cutecanvas_test_support.repository import repository_root
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

_HIGH_DPI_RESULT_PREFIX = "HYBRID_MASK_EDIT_CONTINUITY="


def test_retained_mask_raster_edit_never_drops_or_reverts_presented_coverage(
    qapp: QApplication,
) -> None:
    """Every transition frame must retain unaffected and accepted mask coverage."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(3440, 1440),
        widget_size=QSize(1082, 639),
        mask_count=2,
        brush_size=64,
    )
    viewer = harness.viewer
    mask_id = _populate_retained_masks(harness)
    try:
        _assert_complete_mask_frame(harness, expected_layers=2)
        erase_point = _panel_point(viewer, QPointF(900.0, 500.0))
        retained_points = (
            _panel_point(viewer, QPointF(700.0, 300.0)),
            _panel_point(viewer, QPointF(1050.0, 700.0)),
        )
        for point in (*retained_points, erase_point):
            measurement = harness.wait_for_mask_tint(point, timeout_ms=1000)
            assert measurement.latency_ms is not None, (
                point,
                measurement.color.getRgb(),
            )

        viewer.setControlMode(viewer.CONTROL_MODE_ERASER)
        with harness.observe_presented_frames() as probe:
            QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=erase_point)
            harness.drain_events()
            QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=erase_point)
            assert harness.wait_for_mask_undo_depth(mask_id, 3, timeout_ms=3000)
            assert harness.wait_for_mask_render_idle(timeout_ms=3000)
            viewer.repaint()

        assert probe.frames
        assert all(frame.mask_layer_count == 2 for frame in probe.frames), tuple(
            (frame.mask_layer_ids, frame.mask_item_states) for frame in probe.frames
        )
        assert all(
            harness.is_mask_tint(frame.color_at(point))
            for frame in probe.frames
            for point in retained_points
        )
        erased_states = tuple(
            harness.is_mask_tint(frame.color_at(erase_point)) for frame in probe.frames
        )
        first_erased = erased_states.index(False)
        assert not any(erased_states[first_erased:])
        assert (
            harness.wait_for_background(erase_point, timeout_ms=1000).latency_ms
            is not None
        )
    finally:
        harness.close()


def test_high_dpi_retained_mask_raster_edit_never_drops_a_presented_layer() -> None:
    """A delayed high-DPI handoff must preserve every visible mask layer."""
    environment = dict(os.environ)
    tests_root = Path(__file__).resolve().parents[2]
    python_path = environment.get("PYTHONPATH")
    environment.update(
        {
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
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result_line = next(
        (
            line
            for line in completed.stdout.splitlines()
            if line.startswith(_HIGH_DPI_RESULT_PREFIX)
        ),
        None,
    )
    assert result_line is not None, completed.stdout + completed.stderr
    result = json.loads(result_line.removeprefix(_HIGH_DPI_RESULT_PREFIX))
    assert result["device_pixel_ratio"] == pytest.approx(1.75)
    assert result["retained_before"] == 2
    assert result["retained_after"] == 0
    assert result["frame_count"] > 0
    assert result["mask_layer_counts"] == [2] * result["frame_count"], result
    assert all(all(point_states) for point_states in result["retained_point_states"])
    erased_states = result["erased_point_states"]
    first_erased = erased_states.index(False)
    assert not any(erased_states[first_erased:])


def _populate_retained_masks(harness: MountedQPaneHarness) -> uuid.UUID:
    """Author overlapping retained coverage and reactivate its primary mask."""
    viewer = harness.viewer
    primary_mask_id = harness.mask_ids[0]
    assert viewer.editor.coverage.rectangle(QRectF(644.0, 225.0, 542.0, 567.0))
    assert viewer.editor.coverage.rectangle(QRectF(800.0, 300.0, 886.0, 581.0))
    harness.activate_mask(1)
    assert viewer.editor.coverage.rectangle(QRectF(1186.0, 202.0, 328.0, 663.0))
    harness.activate_mask(0)
    return primary_mask_id


def _panel_point(viewer: CuteCanvas, source_point: QPointF) -> QPoint:
    """Project one active-mask source point into integer panel coordinates."""
    coordinates = viewer.activeMaskLayerCoordinates()
    panel_point = coordinates.source_to_panel(source_point)
    if panel_point is None:
        raise AssertionError("active mask source point must project into the panel")
    return QPoint(round(panel_point.x()), round(panel_point.y()))


def _assert_complete_mask_frame(
    harness: MountedQPaneHarness,
    *,
    expected_layers: int,
) -> None:
    """Require a settled visual baseline before observing one transition."""
    assert harness.wait_for_mask_render_idle(timeout_ms=3000)
    assert harness.wait_for_render_refinement_idle(
        timeout_ms=3000,
        include_prefetch=True,
    )
    with harness.observe_presented_frames() as probe:
        harness.viewer.repaint()
    assert probe.frames
    assert probe.frames[-1].mask_layer_count == expected_layers


def _physical_frame_color(frame: PresentedMaskFrame, point: QPoint) -> QColor:
    """Sample a logical panel point from one physical backing-buffer frame."""
    device_pixel_ratio = frame.image.devicePixelRatio()
    return frame.image.pixelColor(
        round(point.x() * device_pixel_ratio) + frame.overscan_margin,
        round(point.y() * device_pixel_ratio) + frame.overscan_margin,
    )


def _high_dpi_probe() -> dict[str, object]:
    """Exercise the retained-to-raster handoff in an isolated Qt runtime."""
    application = QApplication.instance() or QApplication(sys.argv[:1])
    harness = MountedQPaneHarness(
        application,
        image_size=QSize(3440, 1440),
        widget_size=QSize(1082, 639),
        mask_count=2,
        brush_size=64,
    )
    viewer = harness.viewer
    mask_id = _populate_retained_masks(harness)
    try:
        _assert_complete_mask_frame(harness, expected_layers=2)
        layer = viewer.mask_service.assets.get_layer(mask_id)
        assert layer is not None
        retained_before = len(layer.coverage.retained.items)
        erase_point = _panel_point(viewer, QPointF(900.0, 500.0))
        retained_points = (
            _panel_point(viewer, QPointF(700.0, 300.0)),
            _panel_point(viewer, QPointF(1050.0, 700.0)),
        )
        viewer.setControlMode(viewer.CONTROL_MODE_ERASER)
        with harness.observe_presented_frames() as probe:
            QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=erase_point)
            harness.drain_events()
            QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=erase_point)
            assert harness.wait_for_mask_undo_depth(mask_id, 3, timeout_ms=3000)
            assert harness.wait_for_mask_render_idle(timeout_ms=3000)
            viewer.repaint()
        return {
            "device_pixel_ratio": viewer.devicePixelRatioF(),
            "retained_before": retained_before,
            "retained_after": len(layer.coverage.retained.items),
            "frame_count": len(probe.frames),
            "mask_layer_counts": [frame.mask_layer_count for frame in probe.frames],
            "mask_item_states": [frame.mask_item_states for frame in probe.frames],
            "retained_point_states": [
                [
                    harness.is_mask_tint(_physical_frame_color(frame, point))
                    for frame in probe.frames
                ]
                for point in retained_points
            ],
            "erased_point_states": [
                harness.is_mask_tint(_physical_frame_color(frame, erase_point))
                for frame in probe.frames
            ],
        }
    finally:
        harness.close()


if __name__ == "__main__":
    if sys.argv[1:] != ["--high-dpi-probe"]:
        raise SystemExit("expected --high-dpi-probe")
    print(_HIGH_DPI_RESULT_PREFIX + json.dumps(_high_dpi_probe(), sort_keys=True))
