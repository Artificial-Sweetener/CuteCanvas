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
"""Prove durable mask edits invalidate every mounted document viewport."""

from __future__ import annotations

import time
import uuid
from unittest.mock import patch

import pytest
from cutecanvas import (
    CanvasDocument,
    CanvasDocumentRuntime,
    CanvasRenderVariant,
    CanvasViewportInteraction,
    CanvasViewportSource,
    CanvasViewportSpec,
    CuteCanvas,
    PixelSelectionMode,
    VectorShapeKind,
)
from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtTest import QSignalSpy, QTest
from shiboken6 import delete


def test_mask_signals_ignore_a_destroyed_view(
    qapp,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Document-owned mask signals must stop targeting a destroyed canvas view."""

    document = CanvasDocument()
    runtime = CanvasDocumentRuntime(document)
    editor = CuteCanvas(
        document=document,
        document_runtime=runtime,
        features=("mask",),
    )
    masks = editor._masks_controller
    service = masks.mask_service()
    assert service is not None
    controller = service.controller
    live_previews = runtime._mask_live_preview_store
    delete(editor)

    controller.render_dirty.emit(None, QRect())
    controller.mask_updated.emit(None, QRect())
    live_previews.changed.emit(uuid.uuid4(), QRect())
    qapp.processEvents()
    captured = capsys.readouterr()

    runtime.close()
    document.close()
    assert "Internal C++ object" not in captured.err


def test_live_brush_contact_updates_neutral_shared_mask_view(qapp) -> None:
    """Present provisional mask coverage in a passive view before stroke commit."""
    document = CanvasDocument()
    runtime = CanvasDocumentRuntime(document)
    editor = CuteCanvas(
        document=document,
        document_runtime=runtime,
        features=("mask",),
    )
    preview = CuteCanvas(
        document=document,
        document_runtime=runtime,
        features=("mask",),
    )
    pressed = False
    try:
        composition = editor.editor.compositions.create(
            QRectF(0.0, 0.0, 256.0, 256.0),
            title="Shared live mask",
        )
        mask_id = editor.createBlankMask(QSize(256, 256), undoable=False)
        assert mask_id is not None
        assert editor.setActiveMaskID(mask_id)
        mask = editor.listMasksForComposition(composition.id)[0]
        assert mask.layer_id is not None
        preview.setViewportSpec(
            CanvasViewportSpec(
                CanvasViewportSource.content(
                    document.content_reference(
                        composition.id,
                        layer_id=mask.layer_id,
                    )
                ),
                viewport_id=uuid.uuid4(),
                interaction=CanvasViewportInteraction.FIT_ONLY,
                render_variant=CanvasRenderVariant.MASK_COVERAGE,
            )
        )
        editor.resize(320, 320)
        preview.resize(192, 192)
        editor.show()
        preview.show()
        editor.setControlMode(editor.CONTROL_MODE_DRAW_BRUSH)
        editor.setBrushSize(48)
        for _ in range(12):
            qapp.processEvents()
        preview_point = QPoint(96, 96)
        before = preview.grab().toImage().pixelColor(preview_point)

        QTest.mousePress(
            editor,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(160, 160),
        )
        pressed = True
        deadline = time.perf_counter() + 1.0
        after = before
        while after == before and time.perf_counter() < deadline:
            qapp.processEvents()
            QTest.qWait(1)
            after = preview.grab().toImage().pixelColor(preview_point)

        assert after != before
        assert editor.getMaskUndoState(mask_id).undo_depth == 0
    finally:
        if pressed:
            QTest.mouseRelease(
                editor,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                QPoint(160, 160),
            )
        editor.close()
        preview.close()
        runtime.close()
        document.close()


def test_committed_mask_edit_invalidates_passive_shared_view(qapp) -> None:
    """Update a passive mask viewport without polling or forcing a render."""

    document = CanvasDocument()
    runtime = CanvasDocumentRuntime(document)
    editor = CuteCanvas(
        document=document,
        document_runtime=runtime,
        features=("mask",),
    )
    preview = CuteCanvas(
        document=document,
        document_runtime=runtime,
        features=("mask",),
    )
    try:
        composition = editor.editor.compositions.create(
            QRectF(0.0, 0.0, 256.0, 256.0),
            title="Shared mask",
        )
        mask_id = editor.createBlankMask(QSize(256, 256), undoable=False)
        assert mask_id is not None
        assert editor.setActiveMaskID(mask_id)
        mask = editor.listMasksForComposition(composition.id)[0]
        assert mask.layer_id is not None
        preview.setViewportSpec(
            CanvasViewportSpec(
                CanvasViewportSource.content(
                    document.content_reference(
                        composition.id,
                        layer_id=mask.layer_id,
                    )
                ),
                viewport_id=uuid.uuid4(),
                interaction=CanvasViewportInteraction.FIT_ONLY,
                render_variant=CanvasRenderVariant.MASK_COVERAGE,
            )
        )
        editor.resize(320, 320)
        preview.resize(192, 192)
        editor.show()
        preview.show()
        for _ in range(12):
            qapp.processEvents()
        scene_changed = QSignalSpy(preview.sceneChanged)

        editor_view = editor.view()
        preview_view = preview.view()
        with (
            patch.object(
                editor_view,
                "invalidate_content_cache",
                wraps=editor_view.invalidate_content_cache,
            ) as editor_invalidate,
            patch.object(
                preview_view,
                "invalidate_content_cache",
                wraps=preview_view.invalidate_content_cache,
            ) as preview_invalidate,
        ):
            item_id = editor.addCoverageShape(
                VectorShapeKind.RECTANGLE,
                QRectF(48.0, 48.0, 160.0, 160.0),
                PixelSelectionMode.ADD,
            )
        qapp.processEvents()

        assert item_id is not None
        assert scene_changed.count() > 0
        assert editor_invalidate.call_count == 1
        assert preview_invalidate.call_count == 1
    finally:
        editor.close()
        preview.close()
        runtime.close()
        document.close()


def test_shared_mask_undo_invalidates_each_view_cache_once(qapp) -> None:
    """Route one history replay through one presentation path per view."""

    document = CanvasDocument()
    runtime = CanvasDocumentRuntime(document)
    editor = CuteCanvas(
        document=document,
        document_runtime=runtime,
        features=("mask",),
    )
    preview = CuteCanvas(
        document=document,
        document_runtime=runtime,
        features=("mask",),
    )
    try:
        composition = editor.editor.compositions.create(
            QRectF(0.0, 0.0, 256.0, 256.0),
            title="Shared mask",
        )
        mask_id = editor.createBlankMask(QSize(256, 256), undoable=False)
        assert mask_id is not None
        assert editor.setActiveMaskID(mask_id)
        mask = editor.listMasksForComposition(composition.id)[0]
        assert mask.layer_id is not None
        preview.setViewportSpec(
            CanvasViewportSpec(
                CanvasViewportSource.content(
                    document.content_reference(
                        composition.id,
                        layer_id=mask.layer_id,
                    )
                ),
                viewport_id=uuid.uuid4(),
                interaction=CanvasViewportInteraction.FIT_ONLY,
                render_variant=CanvasRenderVariant.MASK_COVERAGE,
            )
        )
        assert (
            editor.addCoverageShape(
                VectorShapeKind.RECTANGLE,
                QRectF(48.0, 48.0, 160.0, 160.0),
                PixelSelectionMode.ADD,
            )
            is not None
        )
        qapp.processEvents()

        editor_view = editor.view()
        preview_view = preview.view()
        with (
            patch.object(
                editor_view,
                "invalidate_content_cache",
                wraps=editor_view.invalidate_content_cache,
            ) as editor_invalidate,
            patch.object(
                preview_view,
                "invalidate_content_cache",
                wraps=preview_view.invalidate_content_cache,
            ) as preview_invalidate,
        ):
            assert editor.editor.history.undo()
            qapp.processEvents()

        assert editor_invalidate.call_count == 1
        assert preview_invalidate.call_count == 1
    finally:
        editor.close()
        preview.close()
        runtime.close()
        document.close()
