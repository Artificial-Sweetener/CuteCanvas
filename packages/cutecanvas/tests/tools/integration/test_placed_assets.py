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
"""Public and source-domain tests for non-destructive placed assets."""

from __future__ import annotations

import time
from pathlib import Path

from cutecanvas import CuteCanvas, LayerPolicy
from cutecanvas.resources import ProjectResourceReference
from cutecanvas_test_support.execution_backend import RejectingExecutionBackend
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage
from qpane.sdk.execution import ExecutionRuntime


def _image(color: QColor, width: int = 12, height: int = 8) -> QImage:
    """Return one opaque test image."""
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(color)
    return image


def _wait_for_completion(qapp, completions: list[tuple], request_id) -> tuple:
    """Pump queued worker delivery until one request terminates."""
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        matching = [item for item in completions if item[0] == request_id]
        if matching:
            return matching[-1]
        time.sleep(0.002)
    raise AssertionError("placed asset request did not complete")


def test_embedded_placement_duplicates_source_and_replays_lifecycle(
    qpane_with_mask,
) -> None:
    """Placed instances share source pixels while retaining independent geometry."""
    qpane, _manager, _image_id = qpane_with_mask
    scene = qpane.currentScene()
    assert scene is not None
    first_id = qpane.placeEmbeddedAsset(
        _image(QColor("magenta")),
        placement=QRectF(3.0, 4.0, 24.0, 16.0),
        label="Embedded art",
        interaction=LayerPolicy(selectable=True, movable=True),
    )
    assert first_id is not None
    first_state = qpane.placedAssetState(scene.scene_id, first_id)
    assert first_state is not None
    assert first_state.mode == "embedded"
    assert first_state.status == "ready"

    second_id = qpane.duplicateLayer(scene.scene_id, first_id)
    assert second_id is not None
    updated = qpane.currentScene()
    assert updated is not None
    first = next(layer for layer in updated.layers if layer.layer_id == first_id)
    second = next(layer for layer in updated.layers if layer.layer_id == second_id)
    assert first.source_id == second.source_id == first_state.asset_id
    assert qpane.setLayerPlacement(
        scene.scene_id,
        second_id,
        QRectF(40.0, 5.0, 24.0, 16.0),
    )
    moved = qpane.currentScene()
    assert moved is not None
    assert next(
        layer for layer in moved.layers if layer.layer_id == first_id
    ).placement == QRectF(3.0, 4.0, 24.0, 16.0)

    assert qpane.undoSceneEdit()
    restored = qpane.currentScene()
    assert restored is not None
    assert next(
        layer for layer in restored.layers if layer.layer_id == second_id
    ).placement == QRectF(3.0, 4.0, 24.0, 16.0)
    assert qpane.undoSceneEdit()
    assert all(layer.layer_id != second_id for layer in qpane.currentScene().layers)
    assert qpane.redoSceneEdit()
    assert any(layer.layer_id == second_id for layer in qpane.currentScene().layers)


def test_brush_keeps_selected_placed_layer_and_exposes_forbidden_cursor(
    qpane_with_mask,
) -> None:
    """Brush activation must not silently replace immutable content with a mask."""
    qpane, _manager, _image_id = qpane_with_mask
    scene = qpane.currentScene()
    assert scene is not None
    layer_id = qpane.placeEmbeddedAsset(
        _image(QColor("cyan")),
        interaction=LayerPolicy(selectable=True, movable=True),
    )
    assert layer_id is not None
    assert qpane.setSelectedLayer(scene.scene_id, layer_id)
    assert qpane.paintTargetState() is None

    qpane.setControlMode(qpane.CONTROL_MODE_DRAW_BRUSH)
    qpane.refreshCursor()

    selected = qpane.selectedLayer()
    assert selected is not None
    assert selected.layer_id == layer_id
    assert qpane.cursor().shape() is Qt.CursorShape.ForbiddenCursor


def test_linked_refresh_is_async_and_failure_retains_last_valid_pixels(
    qapp,
    qpane_with_mask,
    tmp_path: Path,
) -> None:
    """Missing or corrupt reloads must not replace the last valid display product."""
    qpane, _manager, _image_id = qpane_with_mask
    path = tmp_path / "linked.png"
    assert _image(QColor("cyan")).save(str(path))
    completions: list[tuple] = []
    qpane.placedAssetRequestCompleted.connect(
        lambda *values: completions.append(tuple(values))
    )

    request_id = qpane.placeLinkedAsset(path, label="Linked art")
    assert request_id is not None
    completed = _wait_for_completion(qapp, completions, request_id)
    assert completed[3] is True
    layer_id = completed[2]
    assert layer_id is not None
    scene = qpane.currentScene()
    assert scene is not None
    state = qpane.placedAssetState(scene.scene_id, layer_id)
    assert state is not None
    assert state.mode == "linked"
    source = ProjectResourceReference(state.asset_id)
    before = qpane.layerSourceCapabilities().rasters.source_image(source)
    assert before is not None

    path.write_bytes(b"not an image")
    refresh_id = qpane.refreshPlacedAsset(scene.scene_id, layer_id)
    assert refresh_id is not None
    failed = _wait_for_completion(qapp, completions, refresh_id)
    assert failed[3] is False
    failed_state = qpane.placedAssetState(scene.scene_id, layer_id)
    assert failed_state is not None
    assert failed_state.status == "error"
    assert failed_state.error
    assert qpane.layerSourceCapabilities().rasters.source_image(source) == before
    assert sum(item[0] == refresh_id for item in completions) == 1

    path.unlink()
    missing_id = qpane.refreshPlacedAsset(scene.scene_id, layer_id)
    assert missing_id is not None
    missing = _wait_for_completion(qapp, completions, missing_id)
    assert missing[3] is False
    missing_state = qpane.placedAssetState(scene.scene_id, layer_id)
    assert missing_state is not None
    assert missing_state.status == "missing"
    assert qpane.layerSourceCapabilities().rasters.source_image(source) == before
    assert sum(item[0] == missing_id for item in completions) == 1


def test_rejected_async_work_returns_correlatable_terminal_request(
    qapp,
    tmp_path: Path,
) -> None:
    """Executor pressure must return the UUID emitted by each terminal failure."""
    backend = RejectingExecutionBackend(
        rejection_counts={
            "editor.placed.decode": 1,
            "editor.placed.rasterize": 1,
        }
    )
    runtime = ExecutionRuntime(backend)
    qpane = CuteCanvas(features=(), execution_runtime=runtime)
    base = _image(QColor("black"))
    qpane.createCompositionFromImage(base, title="Async rejection")
    completions: list[tuple] = []
    qpane.placedAssetRequestCompleted.connect(
        lambda *values: completions.append(tuple(values))
    )
    try:
        linked_id = qpane.placeLinkedAsset(tmp_path / "source.png")
        assert linked_id is not None
        assert [item[0] for item in completions] == [linked_id]
        assert completions[0][3] is False

        scene = qpane.currentScene()
        assert scene is not None
        layer_id = qpane.placeEmbeddedAsset(_image(QColor("cyan")))
        assert layer_id is not None
        raster_id = qpane.rasterizeLayer(scene.scene_id, layer_id)
        assert raster_id is not None
        assert [item[0] for item in completions] == [linked_id, raster_id]
        assert completions[-1][1:4] == (scene.scene_id, layer_id, False)
    finally:
        qpane.deleteLater()
        qapp.processEvents()
        runtime.shutdown()


def test_embed_linked_asset_is_undoable_without_changing_pixels(
    qapp,
    qpane_with_mask,
    tmp_path: Path,
) -> None:
    """Embed and undo must restore provenance around identical source pixels."""
    qpane, _manager, _image_id = qpane_with_mask
    path = tmp_path / "source.png"
    assert _image(QColor("yellow")).save(str(path))
    completions: list[tuple] = []
    qpane.placedAssetRequestCompleted.connect(
        lambda *values: completions.append(tuple(values))
    )
    request_id = qpane.placeLinkedAsset(path)
    assert request_id is not None
    layer_id = _wait_for_completion(qapp, completions, request_id)[2]
    scene = qpane.currentScene()
    assert scene is not None and layer_id is not None

    assert qpane.embedPlacedAsset(scene.scene_id, layer_id)
    embedded = qpane.placedAssetState(scene.scene_id, layer_id)
    assert embedded is not None
    assert embedded.mode == "embedded"
    assert embedded.source_path is None
    assert qpane.undoSceneEdit()
    linked = qpane.placedAssetState(scene.scene_id, layer_id)
    assert linked is not None
    assert linked.mode == "linked"
    assert linked.source_path == path
    assert qpane.redoSceneEdit()
    assert qpane.placedAssetState(scene.scene_id, layer_id).mode == "embedded"


def test_rasterize_atomically_swaps_source_and_preserves_display_geometry(
    qapp,
    qpane_with_mask,
) -> None:
    """Rasterization should become editable as one undoable source transition."""
    qpane, _manager, _image_id = qpane_with_mask
    scene = qpane.currentScene()
    assert scene is not None
    layer_id = qpane.placeEmbeddedAsset(
        _image(QColor(10, 20, 30, 180)),
        placement=QRectF(7.0, 9.0, 30.0, 20.0),
    )
    assert layer_id is not None
    completions: list[tuple] = []
    qpane.placedAssetRequestCompleted.connect(
        lambda *values: completions.append(tuple(values))
    )

    request_id = qpane.rasterizeLayer(
        scene.scene_id,
        layer_id,
        QSize(24, 16),
    )
    assert request_id is not None
    assert _wait_for_completion(qapp, completions, request_id)[3] is True
    rasterized = qpane.currentScene()
    assert rasterized is not None
    layer = next(item for item in rasterized.layers if item.layer_id == layer_id)
    assert layer.source_kind == "raster"
    assert layer.placement == QRectF(7.0, 9.0, 30.0, 20.0)
    pixels = qpane.editableRasterLayerImage(scene.scene_id, layer_id)
    assert pixels is not None
    assert pixels.size() == QSize(24, 16)
    assert pixels.pixelColor(12, 8).alpha() == 180

    assert qpane.undoSceneEdit()
    placed = next(
        item for item in qpane.currentScene().layers if item.layer_id == layer_id
    )
    assert placed.source_kind == "imported-raster"
    assert placed.placement == QRectF(7.0, 9.0, 30.0, 20.0)
    assert qpane.redoSceneEdit()
    redone = next(
        item for item in qpane.currentScene().layers if item.layer_id == layer_id
    )
    assert redone.source_kind == "raster"
