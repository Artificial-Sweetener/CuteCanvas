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

"""Mounted workflow proof for coupled shared-edge resizing."""

from __future__ import annotations

import math

import numpy as np
import pytest
from cutecanvas import LayerGeometryMode, LayerPolicy
from cutecanvas.masks.projection import project_mask_coverage_to_scene
from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtTest import QTest
from qpane.sdk.scene import BilinearLayerTransform, PiecewiseLayerTransform


def test_adjacent_layers_preview_commit_and_undo_as_one_edit(qapp) -> None:
    """Dragging a shared side should resize both layers with one history entry."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 300),
        widget_size=QSize(800, 620),
        mask_count=2,
    )
    viewer = harness.viewer
    try:
        first_id, second_id = harness.mask_ids
        first_asset = viewer.mask_service.assets.get_layer(first_id)
        second_asset = viewer.mask_service.assets.get_layer(second_id)
        assert first_asset is not None and second_asset is not None
        _paint_rectangle(first_asset, 80, 80, 80, 100)
        _paint_rectangle(second_asset, 160, 80, 80, 100)
        viewer.invalidateActiveMaskCache()
        viewer.markDirty()
        viewer.update()
        assert harness.wait_for_mask_render_idle()
        entries = {entry.mask_id: entry for entry in viewer.listMasksForComposition()}
        first = entries[first_id]
        second = entries[second_id]
        assert first.scene_id is not None and first.layer_id is not None
        assert second.scene_id == first.scene_id and second.layer_id is not None
        policy = LayerPolicy(selectable=True, movable=True, pixel_editable=True)
        viewer.setLayerInteractionPolicy(first.scene_id, first.layer_id, policy)
        viewer.setLayerInteractionPolicy(second.scene_id, second.layer_id, policy)
        assert viewer.setControlMode(viewer.CONTROL_MODE_SHARED_EDGE_RESIZE)
        harness.drain_events()

        start = _panel_point(viewer, QPointF(160.0, 130.0))
        end = _panel_point(viewer, QPointF(180.0, 130.0))
        QTest.mouseMove(viewer, start)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewer, end, delay=0)

        assert viewer.layerTransform(first.scene_id, first.layer_id).isIdentity()
        assert viewer.layerTransform(second.scene_id, second.layer_id).isIdentity()

        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=end)
        harness.drain_events()
        first_transform = viewer.layerTransform(first.scene_id, first.layer_id)
        second_transform = viewer.layerTransform(second.scene_id, second.layer_id)
        assert first_transform is not None and second_transform is not None
        assert first_transform.m11() == pytest.approx(1.25, abs=0.02)
        assert second_transform.m11() == pytest.approx(0.75, abs=0.02)

        assert viewer.undoSceneEdit()
        harness.drain_events()
        assert viewer.layerTransform(first.scene_id, first.layer_id).isIdentity()
        assert viewer.layerTransform(second.scene_id, second.layer_id).isIdentity()
    finally:
        harness.close()


def test_tool_switch_cancels_both_shared_edge_previews(qapp) -> None:
    """Changing tools during a drag must restore both authoritative transforms."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 300),
        widget_size=QSize(800, 620),
        mask_count=2,
    )
    viewer = harness.viewer
    try:
        first_id, second_id = harness.mask_ids
        first_asset = viewer.mask_service.assets.get_layer(first_id)
        second_asset = viewer.mask_service.assets.get_layer(second_id)
        assert first_asset is not None and second_asset is not None
        _paint_rectangle(first_asset, 80, 80, 80, 100)
        _paint_rectangle(second_asset, 160, 80, 80, 100)
        viewer.invalidateActiveMaskCache()
        entries = {entry.mask_id: entry for entry in viewer.listMasksForComposition()}
        first = entries[first_id]
        second = entries[second_id]
        assert first.scene_id is not None and first.layer_id is not None
        assert second.layer_id is not None
        assert viewer.setControlMode(viewer.CONTROL_MODE_SHARED_EDGE_RESIZE)
        harness.drain_events()
        start = _panel_point(viewer, QPointF(160.0, 130.0))
        end = _panel_point(viewer, QPointF(180.0, 130.0))
        QTest.mouseMove(viewer, start)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewer, end, delay=0)
        assert viewer.layerTransform(first.scene_id, first.layer_id).isIdentity()
        assert viewer.layerTransform(first.scene_id, second.layer_id).isIdentity()

        assert viewer.setControlMode(viewer.CONTROL_MODE_CURSOR)
        harness.drain_events()

        assert viewer.layerTransform(first.scene_id, first.layer_id).isIdentity()
        assert viewer.layerTransform(first.scene_id, second.layer_id).isIdentity()
    finally:
        harness.close()


def test_common_corner_pivots_on_rail_and_undoes_as_one_edit(qapp) -> None:
    """Dragging one eligible endpoint must projectively reshape both layers."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 300),
        widget_size=QSize(800, 620),
        mask_count=2,
    )
    viewer = harness.viewer
    try:
        first_id, second_id = harness.mask_ids
        first_asset = viewer.mask_service.assets.get_layer(first_id)
        second_asset = viewer.mask_service.assets.get_layer(second_id)
        assert first_asset is not None and second_asset is not None
        _paint_rectangle(first_asset, 80, 80, 80, 100)
        _paint_rectangle(second_asset, 160, 80, 80, 100)
        viewer.invalidateActiveMaskCache()
        viewer.markDirty()
        viewer.update()
        assert harness.wait_for_mask_render_idle()
        entries = {entry.mask_id: entry for entry in viewer.listMasksForComposition()}
        first = entries[first_id]
        second = entries[second_id]
        assert first.scene_id is not None and first.layer_id is not None
        assert second.layer_id is not None
        policy = LayerPolicy(selectable=True, movable=True, pixel_editable=True)
        viewer.setLayerInteractionPolicy(first.scene_id, first.layer_id, policy)
        viewer.setLayerInteractionPolicy(first.scene_id, second.layer_id, policy)
        assert viewer.setControlMode(viewer.CONTROL_MODE_SHARED_EDGE_RESIZE)
        harness.drain_events()

        start = _panel_point(viewer, QPointF(160.0, 80.0))
        end = _panel_point(viewer, QPointF(180.0, 80.0))
        QTest.mouseMove(viewer, start)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewer, end, delay=0)
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=end)
        harness.drain_events()

        first_mapping = viewer.layerTransform(first.scene_id, first.layer_id)
        second_mapping = viewer.layerTransform(first.scene_id, second.layer_id)
        assert first_mapping is not None and second_mapping is not None
        assert first_mapping.map_point(QPointF(160.0, 80.0)) == QPointF(180.0, 80.0)
        assert first_mapping.map_point(QPointF(160.0, 180.0)) == QPointF(160.0, 180.0)
        assert second_mapping.map_point(QPointF(160.0, 80.0)) == QPointF(180.0, 80.0)
        assert second_mapping.map_point(QPointF(160.0, 180.0)) == QPointF(160.0, 180.0)

        assert viewer.undoSceneEdit()
        harness.drain_events()
        assert viewer.layerTransform(first.scene_id, first.layer_id).isIdentity()
        assert viewer.layerTransform(first.scene_id, second.layer_id).isIdentity()
    finally:
        harness.close()


def test_partial_shared_edge_inserts_fixed_topology_and_commits_once(qapp) -> None:
    """A shorter participant supplies a fixed vertex to its longer neighbor."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 300),
        widget_size=QSize(800, 620),
        mask_count=2,
    )
    viewer = harness.viewer
    try:
        first_id, second_id = harness.mask_ids
        first_asset = viewer.mask_service.assets.get_layer(first_id)
        second_asset = viewer.mask_service.assets.get_layer(second_id)
        assert first_asset is not None and second_asset is not None
        _paint_rectangle(first_asset, 80, 80, 80, 100)
        _paint_rectangle(second_asset, 160, 80, 80, 160)
        viewer.invalidateActiveMaskCache()
        viewer.markDirty()
        viewer.update()
        assert harness.wait_for_mask_render_idle()
        entries = {entry.mask_id: entry for entry in viewer.listMasksForComposition()}
        first = entries[first_id]
        second = entries[second_id]
        assert first.scene_id is not None and first.layer_id is not None
        assert second.layer_id is not None
        policy = LayerPolicy(selectable=True, movable=True, pixel_editable=True)
        viewer.setLayerInteractionPolicy(first.scene_id, first.layer_id, policy)
        viewer.setLayerInteractionPolicy(first.scene_id, second.layer_id, policy)
        assert viewer.setControlMode(viewer.CONTROL_MODE_SHARED_EDGE_RESIZE)
        harness.drain_events()

        start = _panel_point(viewer, QPointF(160.0, 80.0))
        end = _panel_point(viewer, QPointF(180.0, 80.0))
        QTest.mouseMove(viewer, start)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewer, end, delay=0)
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=end)
        harness.drain_events()

        first_mapping = viewer.layerTransform(first.scene_id, first.layer_id)
        second_mapping = viewer.layerTransform(first.scene_id, second.layer_id)
        assert isinstance(first_mapping, PiecewiseLayerTransform)
        assert isinstance(second_mapping, PiecewiseLayerTransform)
        assert len(first_mapping.source_boundary) == 4
        assert len(second_mapping.source_boundary) == 5
        assert second_mapping.map_point(QPointF(160.0, 180.0)) == QPointF(
            160.0,
            180.0,
        )
        assert viewer.undoSceneEdit()
        harness.drain_events()
        assert viewer.layerTransform(first.scene_id, first.layer_id).isIdentity()
        assert viewer.layerTransform(first.scene_id, second.layer_id).isIdentity()
    finally:
        harness.close()


def test_partial_shared_edge_preview_and_commit_never_flash_mask_layers(qapp) -> None:
    """Every gesture and settlement frame retains both unaffected interiors."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 300),
        widget_size=QSize(800, 620),
        mask_count=2,
    )
    viewer = harness.viewer
    try:
        first_id, second_id = harness.mask_ids
        first_asset = viewer.mask_service.assets.get_layer(first_id)
        second_asset = viewer.mask_service.assets.get_layer(second_id)
        assert first_asset is not None and second_asset is not None
        _paint_rectangle(first_asset, 80, 80, 80, 100)
        _paint_rectangle(second_asset, 160, 80, 80, 160)
        viewer.invalidateActiveMaskCache()
        viewer.markDirty()
        viewer.update()
        assert harness.wait_for_mask_render_idle()
        entries = {entry.mask_id: entry for entry in viewer.listMasksForComposition()}
        first = entries[first_id]
        second = entries[second_id]
        assert first.scene_id is not None and first.layer_id is not None
        assert second.layer_id is not None
        policy = LayerPolicy(selectable=True, movable=True, pixel_editable=True)
        viewer.setLayerInteractionPolicy(first.scene_id, first.layer_id, policy)
        viewer.setLayerInteractionPolicy(first.scene_id, second.layer_id, policy)
        assert viewer.setControlMode(viewer.CONTROL_MODE_SHARED_EDGE_RESIZE)
        harness.drain_events()
        retained_points = (
            _panel_point(viewer, QPointF(100.0, 140.0)),
            _panel_point(viewer, QPointF(210.0, 210.0)),
        )
        start = _panel_point(viewer, QPointF(160.0, 80.0))
        end = _panel_point(viewer, QPointF(180.0, 80.0))

        with harness.observe_presented_frames() as probe:
            QTest.mouseMove(viewer, start)
            QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(viewer, end, delay=0)
            QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=end)
            assert harness.wait_for_mask_render_idle(timeout_ms=3000)
            assert harness.wait_for_render_refinement_idle(timeout_ms=3000)
            viewer.repaint()

        assert probe.frames
        assert all(frame.mask_layer_count == 2 for frame in probe.frames)
        assert all(
            harness.is_mask_tint(frame.color_at(point))
            for frame in probe.frames
            for point in retained_points
        )
    finally:
        harness.close()


def test_raster_edit_after_piecewise_resize_never_reverts_vector_mask_pixels(
    qapp,
) -> None:
    """A resized vector mask keeps exact raster-transition continuity."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 300),
        widget_size=QSize(800, 620),
        mask_count=2,
        brush_size=28,
    )
    viewer = harness.viewer
    try:
        first_id, second_id = harness.mask_ids
        assert viewer.editor.coverage.rectangle(QRectF(80.0, 80.0, 80.0, 100.0))
        harness.activate_mask(1)
        assert viewer.editor.coverage.rectangle(QRectF(160.0, 80.0, 80.0, 160.0))
        harness.activate_mask(0)
        assert harness.wait_for_mask_render_idle()
        entries = {entry.mask_id: entry for entry in viewer.listMasksForComposition()}
        first = entries[first_id]
        second = entries[second_id]
        assert first.scene_id is not None and first.layer_id is not None
        assert second.layer_id is not None
        policy = LayerPolicy(selectable=True, movable=True, pixel_editable=True)
        viewer.setLayerInteractionPolicy(first.scene_id, first.layer_id, policy)
        viewer.setLayerInteractionPolicy(first.scene_id, second.layer_id, policy)
        assert viewer.setControlMode(viewer.CONTROL_MODE_SHARED_EDGE_RESIZE)
        start = _panel_point(viewer, QPointF(160.0, 80.0))
        end = _panel_point(viewer, QPointF(180.0, 80.0))
        QTest.mouseMove(viewer, start)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewer, end, delay=0)
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=end)
        assert harness.wait_for_mask_render_idle(timeout_ms=3000)
        mapping = viewer.layerTransform(first.scene_id, first.layer_id)
        assert isinstance(mapping, PiecewiseLayerTransform)
        first_asset = viewer.mask_service.assets.get_layer(first_id)
        assert first_asset is not None
        exported = viewer.exportMaskImage(first_id)
        assert exported is not None and not exported.isNull()
        erase_point = _panel_point(viewer, mapping.map_point(QPointF(120.0, 120.0)))
        retained_point = _panel_point(viewer, mapping.map_point(QPointF(100.0, 160.0)))
        projected_before_erase = project_mask_coverage_to_scene(
            first_asset.coverage.snapshot(),
            mapping,
        )
        assert projected_before_erase is not None
        assert viewer.setControlMode(viewer.CONTROL_MODE_ERASER)

        with harness.observe_presented_frames() as probe:
            QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=erase_point)
            harness.drain_events()
            QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=erase_point)
            assert harness.wait_for_mask_render_idle(timeout_ms=3000)
            assert harness.wait_for_render_refinement_idle(timeout_ms=3000)
            viewer.repaint()

        assert probe.frames
        assert all(
            harness.is_mask_tint(frame.color_at(retained_point))
            for frame in probe.frames
        )
        erased_states = tuple(
            harness.is_mask_tint(frame.color_at(erase_point)) for frame in probe.frames
        )
        first_erased = erased_states.index(False)
        assert not any(erased_states[first_erased:])

        scene_center = mapping.map_point(QPointF(120.0, 120.0))
        for y in range(80, 180):
            for x in range(80, 160):
                mapped = mapping.map_point(QPointF(x + 0.5, y + 0.5))
                distance = math.hypot(
                    mapped.x() - scene_center.x(),
                    mapped.y() - scene_center.y(),
                )
                coverage = first_asset.coverage.coverage_value(
                    math.floor(mapped.x()),
                    math.floor(mapped.y()),
                )
                before_coverage = _snapshot_value(
                    projected_before_erase,
                    math.floor(mapped.x()),
                    math.floor(mapped.y()),
                )
                if distance <= 12.0:
                    assert coverage == 0, (x, y, distance, coverage)
                elif distance >= 16.0:
                    assert coverage == before_coverage, (
                        x,
                        y,
                        distance,
                        coverage,
                        before_coverage,
                    )

        assert viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
        with harness.observe_presented_frames() as paint_probe:
            QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=erase_point)
            harness.drain_events()
            QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=erase_point)
            assert harness.wait_for_mask_render_idle(timeout_ms=3000)
            assert harness.wait_for_render_refinement_idle(timeout_ms=3000)
            viewer.repaint()
        assert paint_probe.frames
        painted_states = tuple(
            harness.is_mask_tint(frame.color_at(erase_point))
            for frame in paint_probe.frames
        )
        first_painted = painted_states.index(True)
        assert all(painted_states[first_painted:])
        assert (
            first_asset.coverage.coverage_value(
                math.floor(scene_center.x()),
                math.floor(scene_center.y()),
            )
            > 0
        )
    finally:
        harness.close()


def test_brush_and_eraser_after_angled_resize_edit_exact_vector_mask_region(
    qapp,
) -> None:
    """Angled mask edits must publish at the pointer's exact inverse-mapped region."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 300),
        widget_size=QSize(800, 620),
        mask_count=2,
        brush_size=20,
    )
    viewer = harness.viewer
    try:
        first_id, second_id = harness.mask_ids
        assert viewer.editor.coverage.polygon(
            (
                QPointF(80.0, 80.0),
                QPointF(160.0, 80.0),
                QPointF(160.0, 180.0),
            )
        )
        harness.activate_mask(1)
        assert viewer.editor.coverage.rectangle(QRectF(160.0, 80.0, 80.0, 160.0))
        harness.activate_mask(0)
        assert harness.wait_for_mask_render_idle()
        entries = {entry.mask_id: entry for entry in viewer.listMasksForComposition()}
        first = entries[first_id]
        second = entries[second_id]
        assert first.scene_id is not None and first.layer_id is not None
        assert second.layer_id is not None
        policy = LayerPolicy(selectable=True, movable=True, pixel_editable=True)
        viewer.setLayerInteractionPolicy(first.scene_id, first.layer_id, policy)
        viewer.setLayerInteractionPolicy(first.scene_id, second.layer_id, policy)
        assert viewer.setControlMode(viewer.CONTROL_MODE_SHARED_EDGE_RESIZE)
        start = _panel_point(viewer, QPointF(160.0, 80.0))
        end = _panel_point(viewer, QPointF(81.0, 80.0))
        QTest.mouseMove(viewer, start)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewer, end, delay=0)
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=end)
        assert harness.wait_for_mask_render_idle(timeout_ms=3000)
        mapping = viewer.layerTransform(first.scene_id, first.layer_id)
        assert isinstance(mapping, BilinearLayerTransform)
        first_asset = viewer.mask_service.assets.get_layer(first_id)
        assert first_asset is not None

        paint_source = QPointF(95.0, 165.0)
        paint_panel = _panel_point(viewer, mapping.map_point(paint_source))
        before_paint = first_asset.coverage.snapshot_array()
        assert before_paint[165, 95] == 0
        assert viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
        with harness.observe_presented_frames() as paint_probe:
            QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=paint_panel)
            harness.drain_events()
            QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=paint_panel)
            assert harness.wait_for_mask_render_idle(timeout_ms=3000)
            assert harness.wait_for_render_refinement_idle(timeout_ms=3000)
            viewer.repaint()
        assert paint_probe.frames
        painted_states = tuple(
            harness.is_mask_tint(frame.color_at(paint_panel))
            for frame in paint_probe.frames
        )
        first_painted = painted_states.index(True)
        assert all(painted_states[first_painted:])
        mapped_paint = mapping.map_point(paint_source)
        assert (
            first_asset.coverage.coverage_value(
                math.floor(mapped_paint.x()),
                math.floor(mapped_paint.y()),
            )
            > 0
        )
        exported = viewer.exportMaskImage(first_id)
        assert exported is not None and not exported.isNull()
        assert (
            exported.pixelColor(
                math.floor(mapped_paint.x()),
                math.floor(mapped_paint.y()),
            ).red()
            > 0
        )

        erase_source = QPointF(145.0, 105.0)
        mapped_erase = mapping.map_point(erase_source)
        mapped_retained = mapping.map_point(QPointF(155.0, 165.0))
        erase_panel = _panel_point(viewer, mapped_erase)
        assert (
            first_asset.coverage.coverage_value(
                math.floor(mapped_erase.x()),
                math.floor(mapped_erase.y()),
            )
            == 255
        )
        assert (
            first_asset.coverage.coverage_value(
                math.floor(mapped_retained.x()),
                math.floor(mapped_retained.y()),
            )
            == 255
        )
        assert viewer.setControlMode(viewer.CONTROL_MODE_ERASER)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=erase_panel)
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=erase_panel)
        assert harness.wait_for_mask_render_idle(timeout_ms=3000)
        assert (
            first_asset.coverage.coverage_value(
                math.floor(mapped_erase.x()),
                math.floor(mapped_erase.y()),
            )
            == 0
        )
        assert (
            first_asset.coverage.coverage_value(
                math.floor(mapped_retained.x()),
                math.floor(mapped_retained.y()),
            )
            == 255
        )

        geometry = viewer.layerGeometryPolicy(first.scene_id, first.layer_id)
        assert geometry is not None
        assert geometry.mode is LayerGeometryMode.BOUNDARY
        assert geometry.boundary_points() == tuple(mapping.target_boundary)

        assert viewer.setControlMode(viewer.CONTROL_MODE_SHARED_EDGE_RESIZE)
        seam_start = mapping.target_boundary[1]
        seam_end = mapping.target_boundary[2]
        seam_midpoint = (seam_start + seam_end) * 0.5
        drag_start = _panel_point(viewer, seam_midpoint)
        drag_end = _panel_point(viewer, seam_midpoint + QPointF(10.0, 0.0))
        first_before = viewer.layerTransform(first.scene_id, first.layer_id)
        second_before = viewer.layerTransform(first.scene_id, second.layer_id)
        QTest.mouseMove(viewer, drag_start)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=drag_start)
        QTest.mouseMove(viewer, drag_end, delay=0)
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=drag_end)
        harness.drain_events()

        assert viewer.layerTransform(first.scene_id, first.layer_id) == first_before
        assert viewer.layerTransform(first.scene_id, second.layer_id) == second_before
    finally:
        harness.close()


def test_brush_after_angled_resize_can_expand_mask_beyond_old_mapping_cage(
    qapp,
) -> None:
    """A finite deformation must not turn an unbounded mask into an input cage."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 300),
        widget_size=QSize(800, 620),
        mask_count=2,
        brush_size=20,
    )
    viewer = harness.viewer
    try:
        first_id, second_id = harness.mask_ids
        assert viewer.editor.coverage.rectangle(QRectF(80.0, 80.0, 80.0, 100.0))
        harness.activate_mask(1)
        assert viewer.editor.coverage.rectangle(QRectF(160.0, 80.0, 80.0, 160.0))
        harness.activate_mask(0)
        assert harness.wait_for_mask_render_idle()
        entries = {entry.mask_id: entry for entry in viewer.listMasksForComposition()}
        first = entries[first_id]
        second = entries[second_id]
        assert first.scene_id is not None and first.layer_id is not None
        assert second.layer_id is not None
        policy = LayerPolicy(selectable=True, movable=True, pixel_editable=True)
        viewer.setLayerInteractionPolicy(first.scene_id, first.layer_id, policy)
        viewer.setLayerInteractionPolicy(first.scene_id, second.layer_id, policy)
        assert viewer.setControlMode(viewer.CONTROL_MODE_SHARED_EDGE_RESIZE)
        start = _panel_point(viewer, QPointF(160.0, 80.0))
        end = _panel_point(viewer, QPointF(81.0, 80.0))
        QTest.mouseMove(viewer, start)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewer, end, delay=0)
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=end)
        assert harness.wait_for_mask_render_idle(timeout_ms=3000)
        mapping = viewer.layerTransform(first.scene_id, first.layer_id)
        assert isinstance(mapping, BilinearLayerTransform)

        outside_scene = QPointF(280.0, 150.0)
        assert mapping.inverse_map(outside_scene) is None
        outside_panel = _panel_point(viewer, outside_scene)
        assert viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
        with harness.observe_presented_frames() as probe:
            QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=outside_panel)
            QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=outside_panel)
            assert harness.wait_for_mask_render_idle(timeout_ms=3000)
            assert harness.wait_for_render_refinement_idle(timeout_ms=3000)
            viewer.repaint()
        assert probe.frames
        assert harness.is_mask_tint(probe.frames[-1].color_at(outside_panel))
        assert viewer.layerTransform(first.scene_id, first.layer_id).isIdentity()

        assert viewer.undoSceneEdit()
        assert harness.wait_for_mask_render_idle(timeout_ms=3000)
        assert viewer.layerTransform(first.scene_id, first.layer_id) == mapping
        first_asset = viewer.mask_service.assets.get_layer(first_id)
        assert first_asset is not None and first_asset.coverage.has_retained_items
        assert first_asset.coverage.coverage_value(280, 150) == 0

        assert viewer.redoSceneEdit()
        assert harness.wait_for_mask_render_idle(timeout_ms=3000)
        assert viewer.layerTransform(first.scene_id, first.layer_id).isIdentity()
        assert first_asset.coverage.coverage_value(280, 150) > 0
    finally:
        harness.close()


def test_eraser_at_collapsed_mapping_patch_join_has_one_scene_circular_footprint(
    qapp,
) -> None:
    """One dab spanning mapping patches must erase one continuous scene-space tip."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 300),
        widget_size=QSize(800, 620),
        mask_count=2,
        brush_size=24,
    )
    viewer = harness.viewer
    try:
        first_id, second_id = harness.mask_ids
        first_asset = viewer.mask_service.assets.get_layer(first_id)
        second_asset = viewer.mask_service.assets.get_layer(second_id)
        assert first_asset is not None and second_asset is not None
        _paint_rectangle(first_asset, 80, 80, 80, 100)
        _paint_rectangle(second_asset, 160, 80, 80, 160)
        viewer.invalidateActiveMaskCache()
        viewer.markDirty()
        viewer.update()
        assert harness.wait_for_mask_render_idle()
        entries = {entry.mask_id: entry for entry in viewer.listMasksForComposition()}
        first = entries[first_id]
        second = entries[second_id]
        assert first.scene_id is not None and first.layer_id is not None
        assert second.layer_id is not None
        policy = LayerPolicy(selectable=True, movable=True, pixel_editable=True)
        viewer.setLayerInteractionPolicy(first.scene_id, first.layer_id, policy)
        viewer.setLayerInteractionPolicy(first.scene_id, second.layer_id, policy)
        assert viewer.setControlMode(viewer.CONTROL_MODE_SHARED_EDGE_RESIZE)
        start = _panel_point(viewer, QPointF(160.0, 80.0))
        end = _panel_point(viewer, QPointF(81.0, 80.0))
        QTest.mouseMove(viewer, start)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewer, end, delay=0)
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=end)
        assert harness.wait_for_mask_render_idle(timeout_ms=3000)
        mapping = viewer.layerTransform(first.scene_id, first.layer_id)
        assert isinstance(mapping, BilinearLayerTransform)

        source_center = QPointF(120.0, 82.0)
        scene_center = mapping.map_point(source_center)
        projected_before_erase = project_mask_coverage_to_scene(
            first_asset.coverage.snapshot(),
            mapping,
        )
        assert projected_before_erase is not None
        assert viewer.setControlMode(viewer.CONTROL_MODE_ERASER)
        panel_center = _panel_point(viewer, scene_center)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=panel_center)
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=panel_center)
        assert harness.wait_for_mask_render_idle(timeout_ms=3000)

        for y in range(80, 180):
            for x in range(80, 160):
                mapped = mapping.map_point(QPointF(x + 0.5, y + 0.5))
                distance = math.hypot(
                    mapped.x() - scene_center.x(),
                    mapped.y() - scene_center.y(),
                )
                coverage = first_asset.coverage.coverage_value(
                    math.floor(mapped.x()),
                    math.floor(mapped.y()),
                )
                before_coverage = _snapshot_value(
                    projected_before_erase,
                    math.floor(mapped.x()),
                    math.floor(mapped.y()),
                )
                if distance <= 11.0:
                    assert coverage == 0, (x, y, distance, coverage)
                elif distance >= 13.0:
                    assert coverage == before_coverage, (
                        x,
                        y,
                        distance,
                        coverage,
                        before_coverage,
                    )
    finally:
        harness.close()


def _paint_rectangle(
    layer: object,
    left: int,
    top: int,
    width: int,
    height: int,
) -> None:
    """Replace one real mask with a deterministic opaque rectangle."""

    def mutate(pixels: np.ndarray, _image: object) -> None:
        """Write occupied coverage without retaining stale pixels."""
        pixels.fill(0)
        pixels[top : top + height, left : left + width] = 255

    layer.coverage.raster.mutate(mutate)


def _snapshot_value(snapshot, x: int, y: int) -> int:
    """Return one coverage value from an explicitly bounded snapshot."""
    bounds = snapshot.bounds
    if (
        bounds is None
        or x < bounds.x
        or x >= bounds.right
        or y < bounds.y
        or y >= bounds.bottom
    ):
        return 0
    return int(snapshot.pixels[y - bounds.y, x - bounds.x])


def _panel_point(viewer: object, scene_point: QPointF):
    """Return an integer panel point for a visible scene position."""
    panel = viewer.view().scene_to_panel_point(scene_point)
    assert panel is not None
    return panel.toPoint()
