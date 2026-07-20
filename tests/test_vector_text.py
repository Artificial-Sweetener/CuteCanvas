#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Semantic text shaping, editing, rendering, and persistence contracts."""

from __future__ import annotations

import time

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QColor

from qpane import (
    VectorParagraphStyle,
    VectorTextAlignment,
    VectorTextContent,
    VectorTextDirection,
    VectorTextSpan,
    VectorTextStyle,
)
from qpane.vector.text_layout import SemanticTextLayoutCache

pytest_plugins = ("tests.test_mask_workflows",)


def test_unicode_text_shapes_exact_outlines_carets_and_bounded_cache(qapp) -> None:
    """Qt shaping should retain Unicode semantics under a strict byte ceiling."""
    emphasis = VectorTextStyle(
        ("Arial",),
        28.0,
        700,
        True,
        0.5,
        QColor(210, 40, 90, 220),
    )
    value = "Latin e\u0301 😀\nمرحبا שלום"
    content = VectorTextContent(
        value,
        VectorTextStyle(("Arial",), 24.0),
        (VectorTextSpan(6, 4, emphasis),),
        VectorParagraphStyle(
            VectorTextAlignment.CENTER,
            VectorTextDirection.AUTO,
            1.15,
        ),
    )
    cache = SemanticTextLayoutCache(32 * 1024)
    product = cache.product(content, QRectF(0.0, 0.0, 180.0, 160.0))

    assert not product.picture.isNull()
    assert not product.outline.isEmpty()
    assert len(product.cursor_rects) == len(value) + 1
    assert all(rect.height() > 0.0 for rect in product.cursor_rects)
    assert len(product.font_resolutions) == 2
    assert cache.product(content, QRectF(0.0, 0.0, 180.0, 160.0)) is product
    assert cache.usage_bytes <= 32 * 1024
    cache.set_budget(0)
    assert cache.entry_count == 0
    assert cache.usage_bytes == 0

    missing = (
        SemanticTextLayoutCache()
        .product(
            VectorTextContent(
                "Fallback",
                VectorTextStyle(("Definitely Missing QPane Font", "Arial"), 20.0),
            ),
            QRectF(0.0, 0.0, 160.0, 60.0),
        )
        .font_resolutions[0]
    )
    assert missing.requested_families == (
        "Definitely Missing QPane Font",
        "Arial",
    )
    assert missing.resolved_family
    assert not missing.exact_match


def test_public_semantic_text_is_editable_and_replays_as_one_command(
    qpane_with_mask,
) -> None:
    """Text content and box updates should preserve semantics through history."""
    viewer, _manager, _image_id = qpane_with_mask
    scene = viewer.currentScene()
    assert scene is not None
    layer_id = viewer.createVectorLayer(QSize(480, 320), label="Typography")
    assert layer_id is not None
    original = VectorTextContent(
        "Hello\n世界",
        VectorTextStyle(("Arial",), 30.0, color=QColor(20, 40, 70)),
    )
    object_id = viewer.addVectorText(
        scene.scene_id,
        layer_id,
        QRectF(20.0, 30.0, 280.0, 140.0),
        original,
    )
    assert object_id is not None
    state = viewer.vectorDocumentState(scene.scene_id, layer_id)
    assert state is not None and state.objects[0].text == original

    updated = VectorTextContent(
        "Hello, editor 😀",
        VectorTextStyle(("Arial",), 36.0, 600, color=QColor(180, 30, 80)),
    )
    assert viewer.updateVectorText(
        scene.scene_id,
        layer_id,
        object_id,
        bounds=QRectF(40.0, 45.0, 340.0, 180.0),
        content=updated,
    )
    state = viewer.vectorDocumentState(scene.scene_id, layer_id)
    assert state is not None and state.objects[0].text == updated
    assert state.objects[0].bounds == QRectF(40.0, 45.0, 340.0, 180.0)
    assert viewer.undoSceneEdit()
    state = viewer.vectorDocumentState(scene.scene_id, layer_id)
    assert state is not None and state.objects[0].text == original
    assert viewer.redoSceneEdit()
    state = viewer.vectorDocumentState(scene.scene_id, layer_id)
    assert state is not None and state.objects[0].text == updated


def test_text_to_paths_preserves_painted_colors_and_atomic_history(
    qapp,
    qpane_with_mask,
) -> None:
    """Async conversion should produce editable outlines and undo to text."""
    viewer, _manager, _image_id = qpane_with_mask
    scene = viewer.currentScene()
    assert scene is not None
    layer_id = viewer.createVectorLayer(QSize(420, 240), label="Outlined text")
    assert layer_id is not None
    red = QColor(220, 30, 70)
    blue = QColor(30, 90, 220)
    content = VectorTextContent(
        "ABCD",
        VectorTextStyle(("Arial",), 72.0, color=red),
        (VectorTextSpan(2, 2, VectorTextStyle(("Arial",), 72.0, color=blue)),),
    )
    text_id = viewer.addVectorText(
        scene.scene_id,
        layer_id,
        QRectF(20.0, 20.0, 360.0, 160.0),
        content,
    )
    assert text_id is not None

    completions: list[tuple] = []
    viewer.vectorRequestCompleted.connect(
        lambda *values: completions.append(tuple(values))
    )
    request_id = viewer.convertVectorTextToPaths(scene.scene_id, layer_id, text_id)
    assert request_id is not None
    before_completion = viewer.vectorDocumentState(scene.scene_id, layer_id)
    assert (
        before_completion is not None and before_completion.objects[0].text == content
    )
    completion = _wait_for_request(qapp, completions, request_id)
    assert completion[3] == "text-paths"
    converted = viewer.vectorDocumentState(scene.scene_id, layer_id)
    assert converted is not None
    path_ids = tuple(item.object_id for item in converted.objects)
    assert len(path_ids) == 2
    assert tuple(item.object_id for item in converted.objects) == path_ids
    assert {item.style.fill.rgba() for item in converted.objects} == {
        red.rgba(),
        blue.rgba(),
    }
    assert all(item.text is None and item.path for item in converted.objects)

    assert viewer.undoSceneEdit()
    restored = viewer.vectorDocumentState(scene.scene_id, layer_id)
    assert restored is not None and restored.objects[0].text == content
    assert viewer.redoSceneEdit()
    redone = viewer.vectorDocumentState(scene.scene_id, layer_id)
    assert (
        redone is not None
        and tuple(item.object_id for item in redone.objects) == path_ids
    )


def test_semantic_text_uses_existing_selection_and_raster_conversion_boundaries(
    qapp,
    qpane_with_mask,
) -> None:
    """Text appearance should convert through the shared vector workers."""
    viewer, _manager, _image_id = qpane_with_mask
    scene = viewer.currentScene()
    assert scene is not None
    layer_id = viewer.createVectorLayer(QSize(320, 200), label="Convertible text")
    assert layer_id is not None
    text_id = viewer.addVectorText(
        scene.scene_id,
        layer_id,
        QRectF(20.0, 20.0, 260.0, 120.0),
        VectorTextContent(
            "Selection",
            VectorTextStyle(("Arial",), 52.0, color=QColor(30, 150, 220, 180)),
        ),
    )
    assert text_id is not None
    completions: list[tuple] = []
    viewer.vectorRequestCompleted.connect(
        lambda *values: completions.append(tuple(values))
    )

    selection_request = viewer.convertVectorToPixelSelection(
        scene.scene_id, layer_id, (text_id,)
    )
    assert selection_request is not None
    _wait_for_request(qapp, completions, selection_request)
    assert viewer.pixelSelectionState().has_selection
    assert viewer.undoSceneEdit()

    raster_request = viewer.rasterizeVectorLayer(scene.scene_id, layer_id)
    assert raster_request is not None
    _wait_for_request(qapp, completions, raster_request)
    image = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
    assert image is not None
    assert any(
        image.pixelColor(x, y).alpha() > 0
        for y in range(image.height())
        for x in range(image.width())
    )


def _wait_for_request(qapp, completions: list[tuple], request_id) -> tuple:
    """Pump queued worker delivery until one vector request terminates."""
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        matching = [item for item in completions if item[0] == request_id]
        if matching:
            assert matching[-1][4], matching[-1][5]
            return matching[-1]
        time.sleep(0.002)
    raise AssertionError("vector request did not complete")
