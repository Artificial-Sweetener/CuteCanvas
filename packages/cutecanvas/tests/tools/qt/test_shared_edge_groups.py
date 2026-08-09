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

"""Mounted lifecycle proof for arbitrary-participant shared-edge groups."""

from __future__ import annotations

import uuid
from typing import Protocol, cast

import numpy as np
from cutecanvas import CuteCanvas, LayerPolicy
from cutecanvas.scene.mapping_preview import SceneLayerMappingPreview
from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness
from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QTransform
from PySide6.QtTest import QTest
from qpane.rendering.view import View


class _MountedViewerRuntime(Protocol):
    """Expose live mapping previews and viewport conversion for verification."""

    _scene_mapping_preview: SceneLayerMappingPreview

    def view(self) -> View:
        """Return the mounted rendering view."""
        ...


def test_three_layer_group_previews_commits_and_replays_atomically(qapp) -> None:
    """A T seam must publish three live mappings and one history operation."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 300),
        widget_size=QSize(800, 620),
        mask_count=3,
    )
    viewer = harness.viewer
    runtime = cast(_MountedViewerRuntime, viewer)
    try:
        scene_id, layer_ids = _configure_t_group(harness)
        start = _panel_point(runtime, QPointF(100.0, 120.0))
        end = _panel_point(runtime, QPointF(100.0, 140.0))

        with harness.observe_presented_frames() as probe:
            QTest.mouseMove(viewer, start)
            QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
            before_drag = len(probe.frames)
            QTest.mouseMove(viewer, end, delay=0)
            harness.drain_events(wait_ms=40)

            previews = {
                preview.layer_id: preview.mapping
                for preview in runtime._scene_mapping_preview.previews
            }
            assert set(previews) == set(layer_ids)
            assert previews[layer_ids[0]].map_point(QPointF(100.0, 120.0)) == QPointF(
                100.0, 140.0
            )
            assert previews[layer_ids[1]].map_point(QPointF(100.0, 120.0)) == QPointF(
                100.0, 140.0
            )
            assert previews[layer_ids[2]].map_point(QPointF(200.0, 120.0)) == QPointF(
                200.0, 140.0
            )
            drag_frames = probe.frames[before_drag:]
            assert drag_frames
            assert all(frame.mask_layer_count == 3 for frame in drag_frames)

            QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=end)
            harness.drain_events(wait_ms=40)

        assert runtime._scene_mapping_preview.previews == ()
        committed_points = _mapped_seam_points(viewer, scene_id, layer_ids)
        assert committed_points == (
            QPointF(100.0, 140.0),
            QPointF(100.0, 140.0),
            QPointF(200.0, 140.0),
        )

        assert viewer.undoSceneEdit()
        harness.drain_events()
        assert all(
            viewer.layerTransform(scene_id, layer_id).isIdentity()
            for layer_id in layer_ids
        )
        assert not viewer.undoSceneEdit()

        assert viewer.redoSceneEdit()
        harness.drain_events()
        assert _mapped_seam_points(viewer, scene_id, layer_ids) == committed_points
        assert not viewer.redoSceneEdit()
    finally:
        harness.close()


def test_switching_tools_cancels_every_three_layer_group_preview(qapp) -> None:
    """Cancellation must remove every preview without partially committing a group."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 300),
        widget_size=QSize(800, 620),
        mask_count=3,
    )
    viewer = harness.viewer
    runtime = cast(_MountedViewerRuntime, viewer)
    try:
        scene_id, layer_ids = _configure_t_group(harness)
        start = _panel_point(runtime, QPointF(100.0, 120.0))
        end = _panel_point(runtime, QPointF(100.0, 140.0))
        QTest.mouseMove(viewer, start)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewer, end, delay=0)
        harness.drain_events()
        assert {
            preview.layer_id for preview in runtime._scene_mapping_preview.previews
        } == set(layer_ids)

        assert viewer.setControlMode(viewer.CONTROL_MODE_CURSOR)
        harness.drain_events()

        assert runtime._scene_mapping_preview.previews == ()
        assert all(
            viewer.layerTransform(scene_id, layer_id).isIdentity()
            for layer_id in layer_ids
        )
        assert not viewer.undoSceneEdit()
    finally:
        harness.close()


def _configure_t_group(
    harness: MountedQPaneHarness,
) -> tuple[uuid.UUID, tuple[uuid.UUID, ...]]:
    """Create and enable one top mask joined to two bottom masks."""
    viewer = harness.viewer
    rectangles = (
        (80, 40, 160, 80),
        (80, 120, 80, 100),
        (160, 120, 80, 100),
    )
    for mask_id, rectangle in zip(harness.mask_ids, rectangles, strict=True):
        layer = viewer.mask_service.assets.get_layer(mask_id)
        assert layer is not None
        _paint_rectangle(layer, *rectangle)
    harness.activate_mask(0)
    viewer.invalidateActiveMaskCache()
    viewer.markDirty()
    viewer.update()
    assert harness.wait_for_mask_render_idle()
    entries = {entry.mask_id: entry for entry in viewer.listMasksForComposition()}
    ordered = tuple(entries[mask_id] for mask_id in harness.mask_ids)
    scene_id = cast(uuid.UUID, ordered[0].scene_id)
    layer_ids = cast(
        tuple[uuid.UUID, ...],
        tuple(entry.layer_id for entry in ordered),
    )
    assert all(entry.scene_id == scene_id for entry in ordered)
    assert all(layer_id is not None for layer_id in layer_ids)
    policy = LayerPolicy(selectable=True, movable=True, pixel_editable=True)
    for layer_id in layer_ids:
        viewer.setLayerInteractionPolicy(scene_id, layer_id, policy)
    composition_id = viewer.currentCompositionID()
    assert composition_id is not None
    viewer.compositionService().edit_history.clear_scope(composition_id)
    assert viewer.setControlMode(viewer.CONTROL_MODE_SHARED_EDGE_RESIZE)
    harness.drain_events()
    return scene_id, layer_ids


def _paint_rectangle(
    layer: object,
    left: int,
    top: int,
    width: int,
    height: int,
) -> None:
    """Replace one mask with a deterministic opaque rectangle."""

    def mutate(pixels: np.ndarray, _image: object) -> None:
        """Write occupied coverage without retaining stale pixels."""
        pixels.fill(0)
        pixels[top : top + height, left : left + width] = 255

    layer.coverage.raster.mutate(mutate)


def _mapped_seam_points(
    viewer: CuteCanvas,
    scene_id: uuid.UUID,
    layer_ids: tuple[uuid.UUID, ...],
) -> tuple[QPointF, ...]:
    """Return representative transformed points on every participant span."""
    source_points = (
        QPointF(100.0, 120.0),
        QPointF(100.0, 120.0),
        QPointF(200.0, 120.0),
    )
    result: list[QPointF] = []
    for layer_id, source in zip(layer_ids, source_points, strict=True):
        mapping = viewer.layerTransform(scene_id, layer_id)
        assert mapping is not None
        result.append(
            mapping.map(source)
            if isinstance(mapping, QTransform)
            else mapping.map_point(source)
        )
    return tuple(result)


def _panel_point(viewer: _MountedViewerRuntime, scene_point: QPointF) -> QPoint:
    """Return one integer panel point for a visible scene position."""
    panel = viewer.view().scene_to_panel_point(scene_point)
    assert panel is not None
    return panel.toPoint()
