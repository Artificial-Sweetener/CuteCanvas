#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Mounted and generation-controlled abuse proof for semantic vectors."""

from __future__ import annotations

import statistics
import uuid

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from qpane import (
    VectorPathCommand,
    VectorPathCommandKind,
    VectorShapeKind,
    VectorStyle,
    VectorTextContent,
    VectorTextStyle,
)
from qpane.raster.image_conversion import qimage_to_numpy_argb32
from qpane.scene.render_plan import VectorLayerRenderItem
from tests.harness.mounted_qpane import MountedQPaneHarness
from tests.harness.timing import (
    absolute_latency_assertions_are_isolated,
    interaction_clock,
    stable_latency_samples,
)
from tests.helpers.executor_stubs import StubExecutor

_SUBMISSION_BUDGET_MS = 16.0


def test_large_durable_text_refines_off_thread_without_stale_or_blank_terminal_frame(
    qapp: QApplication,
) -> None:
    """Very large semantic text should submit quickly and settle exactly."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1600, 900),
        widget_size=QSize(960, 540),
        cache_budget_mb=64,
    )
    viewer = harness.viewer
    try:
        scene = viewer.currentScene()
        assert scene is not None
        layer_id = viewer.createVectorLayer(QSize(1600, 900), label="Large text")
        assert layer_id is not None
        content = VectorTextContent(
            "Large semantic text مرحبا שלום 😀 " * 240,
            VectorTextStyle(("Arial",), 22.0),
        )
        started = interaction_clock()
        object_id = viewer.addVectorText(
            scene.scene_id,
            layer_id,
            QRectF(40.0, 30.0, 1500.0, 830.0),
            content,
        )
        assert object_id is not None
        assert (interaction_clock() - started) * 1000.0 < _SUBMISSION_BUDGET_MS
        started = interaction_clock()
        plan = viewer.view().calculateRenderPlan()
        assert plan is not None
        assert (interaction_clock() - started) * 1000.0 < _SUBMISSION_BUDGET_MS

        refined = None
        for _index in range(1500):
            harness.drain_events(wait_ms=2)
            candidate_plan = viewer.view().calculateRenderPlan()
            if candidate_plan is None:
                continue
            candidate = next(
                (
                    item
                    for item in candidate_plan.render_items
                    if isinstance(item, VectorLayerRenderItem)
                    and item.descriptor.layer_id == layer_id
                ),
                None,
            )
            if candidate is not None and candidate.refined_tiles:
                refined = candidate
                break
        assert refined is not None
        assert viewer.view().presenter._vector_refinement.pending_count == 0
        renderer = viewer.view().presenter.renderer
        harness.drain_events(wait_ms=10)
        incremental = renderer.get_base_buffer()
        assert incremental is not None
        pixels = qimage_to_numpy_argb32(incremental.copy())
        viewer.markDirty()
        viewer.update()
        harness.drain_events(wait_ms=10)
        full = renderer.get_base_buffer()
        assert full is not None
        assert (qimage_to_numpy_argb32(full.copy()) == pixels).all()
    finally:
        harness.close()


def test_mounted_semantic_text_editing_is_atomic_responsive_and_redraw_stable(
    qapp: QApplication,
) -> None:
    """Rapid Unicode edits must remain immediate, atomic, and pixel stable."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1600, 900),
        widget_size=QSize(960, 540),
        cache_budget_mb=64,
    )
    viewer = harness.viewer
    try:
        scene = viewer.currentScene()
        assert scene is not None
        layer_id = viewer.createVectorLayer(QSize(1600, 900), label="Text abuse")
        assert layer_id is not None
        original = "Bidirectional مرحبا שלום e\u0301 😀 " * 28
        object_id = viewer.addVectorText(
            scene.scene_id,
            layer_id,
            QRectF(80.0, 60.0, 1240.0, 720.0),
            VectorTextContent(original, VectorTextStyle(("Arial",), 26.0)),
        )
        assert object_id is not None
        assert viewer.setSelectedLayer(scene.scene_id, layer_id)
        viewer.setControlMode(viewer.CONTROL_MODE_VECTOR_TEXT)
        viewer.setFocus()
        harness.drain_events()
        layouts = viewer.view().presenter._vector_cache._text_layouts
        assert layouts is not None
        source_hit = QPointF(100.0, 80.0)
        internal_scene = viewer.view().current_scene_descriptor()
        assert internal_scene is not None
        panel_hit = viewer.view().layer_source_to_panel_point(
            internal_scene.scene_id, layer_id, source_hit
        )
        assert panel_hit is not None
        text_edit_events: list[object] = []
        viewer.vectorTextEditChanged.connect(text_edit_events.append)
        QTest.mouseClick(viewer, Qt.MouseButton.LeftButton, pos=panel_hit.toPoint())
        active = viewer.vectorTextEditState()
        assert (
            active is not None and not active.is_new and active.object_id == object_id
        )
        assert active.scene_id == scene.scene_id
        assert text_edit_events and text_edit_events[-1] == active

        dispatch_samples: list[float] = []
        presented_samples: list[float] = []
        measure_presentation = absolute_latency_assertions_are_isolated()
        for value in " fast عربي עברית" * 3:
            started = interaction_clock()
            QApplication.sendEvent(
                viewer,
                QKeyEvent(
                    QEvent.Type.KeyPress,
                    Qt.Key.Key_unknown,
                    Qt.KeyboardModifier.NoModifier,
                    value,
                ),
            )
            dispatch_samples.append((interaction_clock() - started) * 1000.0)
            presentation_started = interaction_clock()
            harness.drain_events()
            if measure_presentation:
                presented_samples.append(
                    (interaction_clock() - presentation_started) * 1000.0
                )
        QTest.keyClick(viewer, Qt.Key.Key_Space)
        state = viewer.vectorTextEditState()
        assert state is not None and state.text.endswith(" ")
        stable_dispatch_samples = stable_latency_samples(
            dispatch_samples,
            parallel_batch_size=16,
        )
        assert max(stable_dispatch_samples) < _SUBMISSION_BUDGET_MS, [
            (index, value)
            for index, value in enumerate(stable_dispatch_samples)
            if value >= _SUBMISSION_BUDGET_MS
        ]
        if measure_presentation:
            assert max(presented_samples) < _SUBMISSION_BUDGET_MS, [
                (index, value)
                for index, value in enumerate(presented_samples)
                if value >= _SUBMISSION_BUDGET_MS
            ]
        viewer.setControlMode(viewer.CONTROL_MODE_PANZOOM)
        harness.drain_events()
        assert viewer.vectorTextEditState() == state
        viewer.setControlMode(viewer.CONTROL_MODE_VECTOR_TEXT)

        QTest.keyClick(
            viewer,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.ControlModifier,
        )
        assert viewer.vectorTextEditState() is None
        committed = viewer.vectorDocumentState(scene.scene_id, layer_id)
        assert committed is not None
        committed_text = committed.objects[0].text
        assert committed_text is not None and committed_text.text != original
        assert viewer.undoSceneEdit()
        undone = viewer.vectorDocumentState(scene.scene_id, layer_id)
        assert undone is not None and undone.objects[0].text.text == original
        assert viewer.redoSceneEdit()

        assert viewer.beginVectorTextEdit(scene.scene_id, layer_id, object_id)
        QTest.keyClicks(viewer, "discard me")
        QTest.keyClick(viewer, Qt.Key.Key_Escape)
        cancelled = viewer.vectorDocumentState(scene.scene_id, layer_id)
        assert cancelled is not None and cancelled.objects[0].text == committed_text

        layouts.trim_to(0)
        conversion_completions: list[tuple[object, ...]] = []
        viewer.vectorRequestCompleted.connect(
            lambda *values: conversion_completions.append(tuple(values))
        )
        started = interaction_clock()
        conversion_request = viewer.convertVectorTextToPaths(
            scene.scene_id,
            layer_id,
            object_id,
        )
        submission_ms = (interaction_clock() - started) * 1000.0
        assert conversion_request is not None and submission_ms < _SUBMISSION_BUDGET_MS
        unresolved = viewer.vectorDocumentState(scene.scene_id, layer_id)
        assert unresolved is not None and unresolved.objects[0].text == committed_text
        for _index in range(1000):
            harness.drain_events(wait_ms=1)
            matching = [
                values
                for values in conversion_completions
                if values[0] == conversion_request
            ]
            if matching:
                assert matching[-1][3:] == ("text-paths", True, "")
                break
        else:
            raise AssertionError("text-to-path conversion did not settle")
        outlined = viewer.vectorDocumentState(scene.scene_id, layer_id)
        assert outlined is not None and all(
            item.text is None and item.path for item in outlined.objects
        )
        assert viewer.undoSceneEdit()
        restored = viewer.vectorDocumentState(scene.scene_id, layer_id)
        assert restored is not None and restored.objects[0].text == committed_text

        empty_panel = viewer.view().layer_source_to_panel_point(
            internal_scene.scene_id, layer_id, QPointF(1450.0, 820.0)
        )
        assert empty_panel is not None
        QTest.mouseClick(viewer, Qt.MouseButton.LeftButton, pos=empty_panel.toPoint())
        created_session = viewer.vectorTextEditState()
        assert created_session is not None and created_session.is_new
        QTest.keyClicks(viewer, "New text")
        QTest.keyClick(
            viewer,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.ControlModifier,
        )
        created = viewer.vectorDocumentState(scene.scene_id, layer_id)
        assert created is not None and len(created.objects) == 2
        assert viewer.undoSceneEdit()
        restored = viewer.vectorDocumentState(scene.scene_id, layer_id)
        assert restored is not None and len(restored.objects) == 1

        harness.drain_events(wait_ms=10)
        renderer = viewer.view().presenter.renderer
        incremental = renderer.get_base_buffer()
        assert incremental is not None
        incremental_pixels = qimage_to_numpy_argb32(incremental.copy())
        viewer.markDirty()
        viewer.update()
        harness.drain_events(wait_ms=10)
        full = renderer.get_base_buffer()
        assert full is not None
        assert (qimage_to_numpy_argb32(full.copy()) == incremental_pixels).all()
        assert layouts is not None and layouts.usage_bytes <= 8 * 1024 * 1024
    finally:
        harness.close()


def test_large_visible_path_refines_asynchronously_without_stale_frames(
    qapp: QApplication,
) -> None:
    """Complex visible paths must remain responsive, exact, and latest-only."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1600, 900),
        widget_size=QSize(960, 540),
        cache_budget_mb=64,
    )
    viewer = harness.viewer
    try:
        scene = viewer.currentScene()
        assert scene is not None
        layer_id = viewer.createVectorLayer(QSize(1600, 900), label="Refined path")
        assert layer_id is not None
        assert viewer.view().calculateRenderPlan() is not None
        commands = [
            VectorPathCommand(VectorPathCommandKind.MOVE, (QPointF(20.0, 450.0),))
        ]
        commands.extend(
            VectorPathCommand(
                VectorPathCommandKind.LINE,
                (
                    QPointF(
                        20.0 + index * 1.9,
                        450.0 + ((index * 37) % 300) - 150.0,
                    ),
                ),
            )
            for index in range(800)
        )
        commands.append(VectorPathCommand(VectorPathCommandKind.CLOSE))
        started = interaction_clock()
        object_id = viewer.addVectorPath(
            scene.scene_id,
            layer_id,
            tuple(commands),
            VectorStyle(
                fill=QColor(20, 180, 220, 145),
                stroke=QColor(245, 245, 245, 230),
                stroke_width=3.0,
            ),
        )
        assert object_id is not None
        assert (interaction_clock() - started) * 1000.0 < _SUBMISSION_BUDGET_MS

        started = interaction_clock()
        first_plan = viewer.view().calculateRenderPlan()
        assert (interaction_clock() - started) * 1000.0 < _SUBMISSION_BUDGET_MS
        assert first_plan is not None
        first_item = next(
            item
            for item in first_plan.render_items
            if isinstance(item, VectorLayerRenderItem)
            and item.descriptor.layer_id == layer_id
        )
        assert not first_item.refined_tiles

        refined_item = None
        deadline = 3000
        while deadline > 0:
            harness.drain_events(wait_ms=2)
            plan = viewer.view().calculateRenderPlan()
            if plan is not None:
                candidate = next(
                    (
                        item
                        for item in plan.render_items
                        if isinstance(item, VectorLayerRenderItem)
                        and item.descriptor.layer_id == layer_id
                    ),
                    None,
                )
                if candidate is not None and candidate.refined_tiles:
                    refined_item = candidate
                    break
            deadline -= 2
        assert refined_item is not None

        samples: list[float] = []
        for index in range(32):
            step = index + 1
            transform = QTransform()
            transform.translate(float(step % 9), float(-(step % 7)))
            started = interaction_clock()
            assert viewer.updateVectorObject(
                scene.scene_id,
                layer_id,
                object_id,
                transform=transform,
            )
            samples.append((interaction_clock() - started) * 1000.0)
        assert max(stable_latency_samples(samples, parallel_batch_size=8)) < (
            _SUBMISSION_BUDGET_MS
        )
        harness.drain_events(wait_ms=10)

        deadline = 3000
        while deadline > 0:
            harness.drain_events(wait_ms=2)
            presenter = viewer.view().presenter
            if presenter._vector_refinement.pending_count == 0:
                break
            deadline -= 2
        assert viewer.view().presenter._vector_refinement.pending_count == 0
        harness.drain_events(wait_ms=10)
        renderer = viewer.view().presenter.renderer
        incremental = renderer.get_base_buffer()
        assert incremental is not None
        before = qimage_to_numpy_argb32(incremental.copy())
        viewer.markDirty()
        viewer.update()
        harness.drain_events(wait_ms=10)
        full = renderer.get_base_buffer()
        assert full is not None
        assert (qimage_to_numpy_argb32(full.copy()) == before).all()
        cache = viewer.view().presenter._vector_tile_cache
        assert 0 < cache.usage_bytes <= cache.budget_bytes
        assert statistics.median(samples) < _SUBMISSION_BUDGET_MS / 2.0
    finally:
        harness.close()


def test_mounted_many_object_vectors_convert_without_blocking_or_visual_drift(
    qapp: QApplication,
) -> None:
    """Large document conversion should stay async, exact, and redraw-stable."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1600, 900),
        widget_size=QSize(960, 540),
        cache_budget_mb=64,
    )
    viewer = harness.viewer
    try:
        scene = viewer.currentScene()
        assert scene is not None
        layer_id = viewer.createVectorLayer(QSize(1600, 900), label="Vector abuse")
        assert layer_id is not None
        object_ids: list[uuid.UUID] = []
        for index in range(320):
            x = float((index * 83) % 1500)
            y = float((index * 47) % 820)
            object_id = viewer.addVectorShape(
                scene.scene_id,
                layer_id,
                (VectorShapeKind.ELLIPSE if index % 2 else VectorShapeKind.RECTANGLE),
                QRectF(x, y, 72.0, 54.0),
                VectorStyle(
                    fill=QColor(20, 170, 220, 90 + index % 150),
                    stroke=QColor(245, 245, 245, 220),
                    stroke_width=2.0 + index % 5,
                    dash_pattern=(3.0, 2.0) if index % 3 == 0 else (),
                ),
            )
            assert object_id is not None
            object_ids.append(object_id)
        harness.drain_events(wait_ms=10)

        completions: list[tuple] = []
        viewer.vectorRequestCompleted.connect(
            lambda *values: completions.append(tuple(values))
        )
        submission_samples: list[float] = []
        for object_id in object_ids[-12:]:
            started = interaction_clock()
            request_id = viewer.convertVectorToPixelSelection(
                scene.scene_id,
                layer_id,
                (object_id,),
            )
            submission_samples.append((interaction_clock() - started) * 1000.0)
            assert request_id is not None
        request_id = viewer.convertVectorToPixelSelection(scene.scene_id, layer_id)
        assert request_id is not None
        assert max(submission_samples) < _SUBMISSION_BUDGET_MS
        deadline = 3000
        while deadline > 0 and not any(item[0] == request_id for item in completions):
            harness.drain_events(wait_ms=2)
            deadline -= 2
        assert any(item[0] == request_id and item[4] for item in completions)
        assert viewer.pixelSelectionState().has_selection
        assert len({item[0] for item in completions}) == len(completions)

        started = interaction_clock()
        raster_request = viewer.rasterizeVectorLayer(
            scene.scene_id,
            layer_id,
            QSize(1600, 900),
        )
        raster_submission_ms = (interaction_clock() - started) * 1000.0
        assert raster_request is not None
        assert raster_submission_ms < _SUBMISSION_BUDGET_MS
        deadline = 3000
        while deadline > 0 and not any(
            item[0] == raster_request for item in completions
        ):
            harness.drain_events(wait_ms=2)
            deadline -= 2
        assert any(item[0] == raster_request and item[4] for item in completions)
        assert viewer.editableRasterLayerImage(scene.scene_id, layer_id) is not None
        harness.drain_events()

        renderer = viewer.view().presenter.renderer
        incremental = renderer.get_base_buffer()
        assert incremental is not None
        before = qimage_to_numpy_argb32(incremental.copy())
        viewer.markDirty()
        viewer.update()
        harness.drain_events(wait_ms=10)
        full = renderer.get_base_buffer()
        assert full is not None
        assert (qimage_to_numpy_argb32(full.copy()) == before).all()
        assert statistics.median(submission_samples) < _SUBMISSION_BUDGET_MS / 2.0
    finally:
        harness.close()


def test_vector_conversion_storm_rejects_stale_edits_and_tears_down_cleanly(
    qapp: QApplication,
) -> None:
    """Late vector jobs must not overwrite edits, selections, or removed layers."""
    executor = StubExecutor(name="vector-abuse")
    from qpane import QPane

    viewer = QPane(features=(), task_executor=executor)
    image = QImage(320, 240, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor("white"))
    image_id = uuid.uuid4()
    viewer.setImagesByID(viewer.imageMapFromLists((image,), ids=(image_id,)), image_id)
    completions: list[tuple] = []
    viewer.vectorRequestCompleted.connect(
        lambda *values: completions.append(tuple(values))
    )
    try:
        scene = viewer.currentScene()
        assert scene is not None
        layer_id = viewer.createVectorLayer(QSize(320, 240))
        assert layer_id is not None
        object_id = viewer.addVectorShape(
            scene.scene_id,
            layer_id,
            VectorShapeKind.ELLIPSE,
            QRectF(30.0, 20.0, 180.0, 140.0),
        )
        assert object_id is not None

        stale_request = viewer.convertVectorToPixelSelection(scene.scene_id, layer_id)
        assert stale_request is not None
        moved = QTransform()
        moved.translate(11.0, 7.0)
        assert viewer.updateVectorObject(
            scene.scene_id,
            layer_id,
            object_id,
            transform=moved,
        )
        executor.run_category("vector_conversion")
        qapp.processEvents()

        stale = next(item for item in completions if item[0] == stale_request)
        assert stale[4] is False
        assert not viewer.pixelSelectionState().has_selection

        text_id = viewer.addVectorText(
            scene.scene_id,
            layer_id,
            QRectF(20.0, 20.0, 260.0, 100.0),
            VectorTextContent("stale outline", VectorTextStyle(("Arial",), 42.0)),
        )
        assert text_id is not None
        text_request = viewer.convertVectorTextToPaths(
            scene.scene_id,
            layer_id,
            text_id,
        )
        assert text_request is not None
        changed_text = VectorTextContent(
            "newer semantic text",
            VectorTextStyle(("Arial",), 42.0),
        )
        assert viewer.updateVectorText(
            scene.scene_id,
            layer_id,
            text_id,
            content=changed_text,
        )
        executor.run_category("vector_conversion")
        qapp.processEvents()
        text_completion = next(item for item in completions if item[0] == text_request)
        assert text_completion[3:] == (
            "text-paths",
            False,
            "vector layer changed during conversion",
        )
        current = viewer.vectorDocumentState(scene.scene_id, layer_id)
        assert current is not None
        retained_text = next(
            item for item in current.objects if item.object_id == text_id
        )
        assert retained_text.text == changed_text

        requests = [
            viewer.convertVectorToPixelSelection(scene.scene_id, layer_id)
            for _index in range(24)
        ]
        assert all(request is not None for request in requests)
        executor.run_category("vector_conversion")
        qapp.processEvents()
        qapp.processEvents()
        assert all(
            sum(item[0] == request for item in completions) == 1 for request in requests
        )
        assert next(item for item in completions if item[0] == requests[-1])[4]
        assert viewer.pixelSelectionState().has_selection

        raster_request = viewer.rasterizeVectorLayer(scene.scene_id, layer_id)
        assert raster_request is not None
        for _index in range(10):
            if all(
                layer.layer_id != layer_id for layer in viewer.currentScene().layers
            ):
                break
            assert viewer.undoSceneEdit()
        executor.run_category("vector_conversion")
        qapp.processEvents()
        qapp.processEvents()
        assert (
            next(item for item in completions if item[0] == raster_request)[4] is False
        )
        assert all(layer.layer_id != layer_id for layer in viewer.currentScene().layers)
        assert executor.snapshot().queued_by_category.get("vector_conversion", 0) == 0
    finally:
        viewer.clearImages()
        viewer.deleteLater()
        qapp.processEvents()


def test_mounted_vector_mask_edits_remain_exact_under_hostile_transforms(
    qapp: QApplication,
) -> None:
    """Rapid semantic mask edits must redraw exactly without stale fast paths."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1200, 800),
        widget_size=QSize(900, 600),
        cache_budget_mb=48,
    )
    viewer = harness.viewer
    try:
        scene = viewer.currentScene()
        assert scene is not None
        base = scene.layers[0]
        vector_layer = viewer.createVectorLayer(QSize(1200, 800), label="Mask geometry")
        assert vector_layer is not None
        object_ids = []
        for index in range(96):
            object_id = viewer.addVectorShape(
                scene.scene_id,
                vector_layer,
                VectorShapeKind.ELLIPSE,
                QRectF(
                    float((index * 71) % 1080),
                    float((index * 43) % 680),
                    120.0,
                    120.0,
                ),
                VectorStyle(fill=QColor("white"), stroke=None),
            )
            assert object_id is not None
            object_ids.append(object_id)
        assert viewer.setVectorMask(
            scene.scene_id,
            vector_layer,
            base.layer_id,
        )
        harness.drain_events(wait_ms=15)

        latencies: list[float] = []
        edited_id = object_ids[-1]
        for index in range(80):
            transform = QTransform()
            transform.translate(
                float((index * 29) % 340 - 170),
                float((index * 17) % 220 - 110),
            )
            transform.rotate(float(index % 19 - 9))
            started = interaction_clock()
            assert viewer.updateVectorObject(
                scene.scene_id,
                base.layer_id,
                edited_id,
                transform=transform,
            )
            harness.drain_events()
            latencies.append((interaction_clock() - started) * 1000.0)

        plan = viewer.view().calculateRenderPlan()
        base_item = next(
            item
            for item in plan.render_items
            if item.descriptor.layer_id == base.layer_id
        )
        assert base_item.effect_clip_path is not None
        assert base_item.effect_clip_path.elementCount() > 0
        renderer = viewer.view().presenter.renderer
        incremental = renderer.get_base_buffer()
        assert incremental is not None
        incremental_pixels = qimage_to_numpy_argb32(incremental.copy())
        viewer.markDirty()
        viewer.update()
        harness.drain_events(wait_ms=10)
        full = renderer.get_base_buffer()
        assert full is not None
        assert (qimage_to_numpy_argb32(full.copy()) == incremental_pixels).all()
        assert statistics.median(latencies) < 16.0
        assert viewer.undoSceneEdit()
        assert viewer.redoSceneEdit()
        assert viewer.vectorMaskState(scene.scene_id, base.layer_id) is not None
    finally:
        harness.close()


def test_mounted_vector_node_preview_survives_space_and_commits_once(
    qapp: QApplication,
) -> None:
    """Rapid node editing must stay immediate, exact, cancellable, and atomic."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1200, 800),
        widget_size=QSize(900, 600),
        cache_budget_mb=48,
    )
    viewer = harness.viewer
    try:
        scene = viewer.currentScene()
        assert scene is not None
        layer_id = viewer.createVectorLayer(QSize(1200, 800), label="Node abuse")
        assert layer_id is not None
        for index in range(160):
            assert viewer.addVectorShape(
                scene.scene_id,
                layer_id,
                VectorShapeKind.ELLIPSE,
                QRectF(
                    float((index * 67) % 1120),
                    float((index * 41) % 720),
                    72.0,
                    56.0,
                ),
                VectorStyle(fill=QColor(60, 155, 220, 120), stroke=None),
            )
        commands = (
            VectorPathCommand(
                VectorPathCommandKind.MOVE,
                (QPointF(180.0, 250.0),),
            ),
            VectorPathCommand(
                VectorPathCommandKind.CUBIC,
                (
                    QPointF(320.0, 80.0),
                    QPointF(540.0, 620.0),
                    QPointF(720.0, 260.0),
                ),
            ),
        )
        object_id = viewer.addVectorPath(
            scene.scene_id,
            layer_id,
            commands,
            VectorStyle(fill=None, stroke=QColor("white"), stroke_width=8.0),
        )
        assert object_id is not None
        assert viewer.setSelectedLayer(scene.scene_id, layer_id)
        assert viewer.setSelectedVectorObjects(scene.scene_id, layer_id, (object_id,))
        viewer.setControlMode(viewer.CONTROL_MODE_VECTOR_NODE)
        harness.drain_events(wait_ms=10)
        rendered_scene = viewer.view().current_scene_descriptor()
        assert rendered_scene is not None

        origin = viewer.view().layer_source_to_panel_point(
            rendered_scene.scene_id,
            layer_id,
            QPointF(180.0, 250.0),
        )
        assert origin is not None
        durable_before = viewer.vectorDocumentState(scene.scene_id, layer_id)
        assert durable_before is not None
        renderer = viewer.view().presenter.renderer
        baseline = renderer.get_base_buffer()
        assert baseline is not None
        baseline_pixels = qimage_to_numpy_argb32(baseline.copy())

        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, origin.toPoint())
        latencies: list[float] = []
        final_document_point = QPointF(180.0, 250.0)
        for index in range(120):
            final_document_point = QPointF(
                180.0 + float((index * 17) % 260),
                250.0 + float((index * 29) % 180 - 90),
            )
            panel_point = viewer.view().layer_source_to_panel_point(
                rendered_scene.scene_id,
                layer_id,
                final_document_point,
            )
            assert panel_point is not None
            started = interaction_clock()
            QTest.mouseMove(viewer, panel_point.toPoint())
            harness.drain_events()
            latencies.append((interaction_clock() - started) * 1000.0)
        assert viewer.vectorDocumentState(scene.scene_id, layer_id) == durable_before
        assert viewer.vectorNodeSelectionState() is not None
        preview = renderer.get_base_buffer()
        assert preview is not None
        assert not (qimage_to_numpy_argb32(preview.copy()) == baseline_pixels).all()

        QTest.keyPress(viewer, Qt.Key_Space)
        harness.drain_events()
        suspended = renderer.get_base_buffer()
        assert suspended is not None
        suspended_pixels = qimage_to_numpy_argb32(suspended.copy())
        QTest.keyRelease(viewer, Qt.Key_Space)
        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, origin.toPoint())
        harness.drain_events()
        assert (
            qimage_to_numpy_argb32(renderer.get_base_buffer().copy())
            == suspended_pixels
        ).all()
        assert viewer.vectorDocumentState(scene.scene_id, layer_id) == durable_before

        resumed = viewer.view().layer_source_to_panel_point(
            rendered_scene.scene_id,
            layer_id,
            final_document_point,
        )
        assert resumed is not None
        committed_point = QPointF(520.0, 410.0)
        committed_panel = viewer.view().layer_source_to_panel_point(
            rendered_scene.scene_id,
            layer_id,
            committed_point,
        )
        assert committed_panel is not None
        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, resumed.toPoint())
        QTest.mouseMove(viewer, committed_panel.toPoint())
        QTest.mouseRelease(
            viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            committed_panel.toPoint(),
        )
        harness.drain_events(wait_ms=5)
        committed = viewer.vectorDocumentState(scene.scene_id, layer_id)
        assert committed is not None
        assert committed.revision == durable_before.revision + 1
        assert committed.objects[-1].path[0].points[0].manhattanLength() > 0.0
        assert committed.objects[-1].path[0].points[0] != commands[0].points[0]

        incremental = renderer.get_base_buffer()
        assert incremental is not None
        incremental_pixels = qimage_to_numpy_argb32(incremental.copy())
        viewer.markDirty()
        viewer.update()
        harness.drain_events(wait_ms=10)
        assert (
            qimage_to_numpy_argb32(renderer.get_base_buffer().copy())
            == incremental_pixels
        ).all()
        assert viewer.undoSceneEdit()
        assert viewer.vectorDocumentState(scene.scene_id, layer_id) == durable_before
        assert viewer.redoSceneEdit()
        assert statistics.median(latencies) < 16.0

        selected_handle = viewer.view().layer_source_to_panel_point(
            rendered_scene.scene_id,
            layer_id,
            committed.objects[-1].path[0].points[0],
        )
        assert selected_handle is not None
        before_cancel = viewer.vectorDocumentState(scene.scene_id, layer_id)
        QTest.mousePress(
            viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            selected_handle.toPoint(),
        )
        QTest.mouseMove(viewer, origin.toPoint())
        QTest.keyClick(viewer, Qt.Key_Escape)
        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, origin.toPoint())
        harness.drain_events(wait_ms=5)
        assert viewer.vectorDocumentState(scene.scene_id, layer_id) == before_cancel
    finally:
        harness.close()


def test_mounted_vector_mask_nodes_preview_and_commit_through_target_layer(
    qapp: QApplication,
) -> None:
    """Node edits on an attached mask must clip live and retain one undo step."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(800, 600),
        widget_size=QSize(800, 600),
        cache_budget_mb=32,
    )
    viewer = harness.viewer
    try:
        scene = viewer.currentScene()
        assert scene is not None
        base = scene.layers[0]
        vector_layer = viewer.createVectorLayer(QSize(800, 600), label="Mask nodes")
        assert vector_layer is not None
        object_id = viewer.addVectorShape(
            scene.scene_id,
            vector_layer,
            VectorShapeKind.RECTANGLE,
            QRectF(80.0, 80.0, 300.0, 240.0),
            VectorStyle(fill=QColor("white"), stroke=None),
        )
        assert object_id is not None
        assert viewer.setVectorMask(
            scene.scene_id,
            vector_layer,
            base.layer_id,
            (object_id,),
        )
        viewer.setControlMode(viewer.CONTROL_MODE_VECTOR_NODE)
        harness.drain_events(wait_ms=5)
        rendered_scene = viewer.view().current_scene_descriptor()
        assert rendered_scene is not None
        origin = viewer.view().layer_source_to_panel_point(
            rendered_scene.scene_id,
            base.layer_id,
            QPointF(80.0, 80.0),
        )
        destination = viewer.view().layer_source_to_panel_point(
            rendered_scene.scene_id,
            base.layer_id,
            QPointF(180.0, 150.0),
        )
        assert origin is not None and destination is not None
        durable_before = viewer.vectorDocumentState(scene.scene_id, base.layer_id)
        assert durable_before is not None

        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, origin.toPoint())
        QTest.mouseMove(viewer, destination.toPoint())
        harness.drain_events()
        assert (
            viewer.vectorDocumentState(scene.scene_id, base.layer_id) == durable_before
        )
        preview_plan = viewer.view().calculateRenderPlan()
        preview_base = next(
            item
            for item in preview_plan.render_items
            if item.descriptor.layer_id == base.layer_id
        )
        assert preview_base.effect_clip_path is not None
        assert not preview_base.effect_clip_path.contains(QPointF(100.0, 100.0))
        assert preview_base.effect_clip_path.contains(QPointF(200.0, 180.0))

        QTest.mouseRelease(
            viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            destination.toPoint(),
        )
        harness.drain_events(wait_ms=5)
        committed = viewer.vectorDocumentState(scene.scene_id, base.layer_id)
        assert committed is not None
        assert committed.revision == durable_before.revision + 1
        assert committed.objects[0].bounds == QRectF(180.0, 150.0, 200.0, 170.0)
        assert viewer.undoSceneEdit()
        assert (
            viewer.vectorDocumentState(scene.scene_id, base.layer_id) == durable_before
        )
    finally:
        harness.close()
