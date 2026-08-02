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

"""Regressions for movement snapping and transient mask clipping."""

from __future__ import annotations

import numpy as np
import pytest
from cutecanvas import LayerPolicy
from cutecanvas.snapping.engine import SnapSession
from cutecanvas.snapping.model import bounds_candidates
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

from tests.harness.mounted_qpane import MountedQPaneHarness
from tests.harness.timing import (
    average_interaction_latency_ms,
    interaction_clock,
    tail_interaction_latency_ms,
)


def test_moving_top_edge_acquires_document_center_while_left_edge_stays_snapped() -> (
    None
):
    """A moving edge may acquire a perpendicular document center relationship."""
    session = SnapSession(
        "rectangle",
        QRectF(0.0, 600.0, 200.0, 100.0),
        bounds_candidates(
            "document",
            QRectF(0.0, 0.0, 1000.0, 800.0),
            cross_feature_center=True,
        ),
    )

    result = session.resolve(
        QPointF(0.0, -197.0),
        scene_units_per_device_pixel=1.0,
    )

    assert result.delta == QPointF(0.0, -200.0)
    assert result.snapped_x and result.snapped_y
    assert {guide.position for guide in result.guides} == {0.0, 400.0}


@pytest.mark.interactive_performance
def test_cross_feature_snapping_stays_bounded_under_dense_reversals() -> None:
    """New edge/center relationships retain bounded construction and pointer cost."""
    candidates = tuple(
        candidate
        for index in range(500)
        for candidate in bounds_candidates(
            f"layer:{index}",
            QRectF(index * 20.0, index * 13.0, 10.0, 8.0),
        )
    )
    construction_ms = average_interaction_latency_ms(
        lambda: SnapSession(
            "source",
            QRectF(1.0, 2.0, 10.0, 8.0),
            candidates,
        ),
        repetitions=1_000,
    )
    session = SnapSession("source", QRectF(1.0, 2.0, 10.0, 8.0), candidates)

    latencies_ms: list[float] = []
    for index in range(2_000):
        point = QPointF(9_000.0, 6_000.0) if index % 2 else QPointF(1_000.0, 650.0)
        started = interaction_clock()
        session.resolve(point, scene_units_per_device_pixel=1.0)
        latencies_ms.append((interaction_clock() - started) * 1000.0)

    assert construction_ms < 0.5
    assert tail_interaction_latency_ms(latencies_ms) < 0.1


def _paint_square(layer: object, left: int, top: int, size: int) -> None:
    """Replace a real hybrid mask with one opaque square."""

    def mutate(pixels: np.ndarray, _image: object) -> None:
        """Write deterministic occupied coverage."""
        pixels.fill(0)
        pixels[top : top + size, left : left + size] = 255

    layer.coverage.raster.mutate(mutate)


def _pixel_at_scene(viewer: object, image: QImage, point: QPointF) -> QColor:
    """Return one captured device pixel addressed by a scene coordinate."""
    panel_point = viewer.view().scene_to_panel_point(point)
    assert panel_point is not None
    scale = image.devicePixelRatio()
    return image.pixelColor(
        round(panel_point.x() * scale),
        round(panel_point.y() * scale),
    )


def _drag(viewer: object, start: QPointF, end: QPointF, *, release: bool) -> None:
    """Drive one real Move gesture between scene-space points."""
    panel_start = viewer.view().scene_to_panel_point(start)
    panel_end = viewer.view().scene_to_panel_point(end)
    assert panel_start is not None and panel_end is not None
    QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=panel_start.toPoint())
    QTest.mouseMove(viewer, panel_end.toPoint(), delay=0)
    if release:
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=panel_end.toPoint())


def test_mask_move_preview_keeps_canvas_clip_before_and_after_inside_commit(
    qapp,
) -> None:
    """Every outside drag must use the same canvas aperture as its settled scene."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1000, 800),
        widget_size=QSize(1400, 900),
    )
    viewer = harness.viewer
    try:
        mask_id = harness.mask_ids[0]
        asset = viewer.mask_service.assets.get_layer(mask_id)
        assert asset is not None
        _paint_square(asset, 800, 300, 200)
        assert viewer.setMaskProperties(
            mask_id,
            color=QColor(20, 240, 80),
            opacity=1.0,
        )
        viewer.invalidateActiveMaskCache()
        viewer.markDirty()
        viewer.update()
        assert harness.wait_for_mask_render_idle()
        assert harness.wait_for_render_refinement_idle()

        entry = next(
            entry
            for entry in viewer.listMasksForComposition()
            if entry.mask_id == mask_id
        )
        assert entry.scene_id is not None and entry.layer_id is not None
        viewer.setLayerInteractionPolicy(
            entry.scene_id,
            entry.layer_id,
            LayerPolicy(selectable=True, movable=True, pixel_editable=True),
        )
        assert viewer.setActiveMaskID(mask_id)
        viewer.setSelectedLayer(entry.scene_id, entry.layer_id)
        selected = viewer.selectedLayer()
        assert selected is not None and selected.layer_id == entry.layer_id
        assert viewer.configureSnapping(enabled=False)
        viewer.setControlMode(viewer.CONTROL_MODE_MOVE)
        harness.drain_events()

        sample_point = QPointF(1050.0, 350.0)
        baseline = _pixel_at_scene(viewer, harness.capture(), sample_point)
        original_scene = viewer.view().current_scene_descriptor()
        assert original_scene is not None
        original_layer = next(
            layer for layer in original_scene.layers if layer.layer_id == entry.layer_id
        )
        assert original_layer.clip is None

        _drag(viewer, QPointF(850.0, 350.0), QPointF(950.0, 350.0), release=False)
        harness.drain_events()
        preview_scene = viewer.view().current_scene_descriptor()
        assert preview_scene is not None
        preview_layer = next(
            layer for layer in preview_scene.layers if layer.layer_id == entry.layer_id
        )
        assert preview_layer.placement.x == pytest.approx(
            original_layer.placement.x + 100.0,
            abs=1.0,
        )
        assert preview_layer.clip is not None
        assert _pixel_at_scene(viewer, harness.capture(), sample_point) == baseline

        panel_end = viewer.view().scene_to_panel_point(QPointF(950.0, 350.0))
        assert panel_end is not None
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=panel_end.toPoint())
        harness.drain_events()
        assert _pixel_at_scene(viewer, harness.capture(), sample_point) == baseline

        _drag(viewer, QPointF(950.0, 350.0), QPointF(850.0, 350.0), release=True)
        harness.drain_events()
        _drag(viewer, QPointF(850.0, 350.0), QPointF(950.0, 350.0), release=False)
        harness.drain_events()
        repeated_scene = viewer.view().current_scene_descriptor()
        assert repeated_scene is not None
        repeated_layer = next(
            layer for layer in repeated_scene.layers if layer.layer_id == entry.layer_id
        )
        assert repeated_layer.clip is not None
        assert _pixel_at_scene(viewer, harness.capture(), sample_point) == baseline
    finally:
        harness.close()
