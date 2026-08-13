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
"""Prove headless document and detachable session lifetime boundaries."""

from __future__ import annotations

import uuid

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

from cutecanvas import CuteCanvas, LayerPolicy, PixelSelectionMode
from cutecanvas.document import CanvasDocument, CanvasViewSession
from cutecanvas.document.inspection import SessionInspectionBinding
from qpane.sdk.inspection import InspectionStateStore
from qpane.sdk.rendering import ViewportZoomMode
from qpane.sdk.types import LinkedGroup
from qpane.sdk.vector import VectorShapeKind


class _InspectionViewport:
    """Provide the minimum viewport state needed by an inspection binding."""

    def __init__(self, zoom: float) -> None:
        """Initialize a deliberately transient viewport zoom."""
        self.zoom = zoom
        self.pan = QPointF()
        self.zoom_mode = ViewportZoomMode.CUSTOM

    def get_zoom_mode(self) -> ViewportZoomMode:
        """Return the current zoom mode."""
        return self.zoom_mode

    def setZoomFit(self) -> None:
        """Apply fit mode for protocol completeness."""
        self.zoom_mode = ViewportZoomMode.FIT

    def setZoomAndPan(self, zoom: float, pan: QPointF) -> None:
        """Apply the projected transform for protocol completeness."""
        self.zoom = zoom
        self.pan = QPointF(pan)


def test_document_content_exists_before_any_widget_mount() -> None:
    """A host can create durable compositions without constructing a QWidget."""
    document = CanvasDocument()
    try:
        record = document.resources.compositions.create_composition(
            QRectF(0.0, 0.0, 640.0, 480.0),
            title="Headless",
        )
        assert document.resources.compositions.composition_ids() == (
            record.composition_id,
        )
    finally:
        document.close()


def test_two_canvas_views_share_content_but_not_activation(qapp) -> None:
    """Two widgets may mount one document with independent active compositions."""
    document = CanvasDocument()
    first_session = CanvasViewSession()
    second_session = CanvasViewSession()
    first = CuteCanvas(
        document=document,
        session=first_session,
        features=(),
    )
    second = CuteCanvas(
        document=document,
        session=second_session,
        features=(),
    )
    try:
        image = QImage(32, 24, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor("royalblue"))
        first_id = first.createCompositionFromImage(image, title="First")
        second_id = first.createComposition(
            QRectF(0.0, 0.0, 80.0, 60.0),
            title="Second",
        )
        first.openComposition(first_id)
        second.openComposition(second_id)

        assert first.currentCompositionID() == first_id
        assert second.currentCompositionID() == second_id
        assert first.compositionService() is second.compositionService()
        assert first.getCompositionSnapshot().order == (first_id, second_id)
        assert second.getCompositionSnapshot().order == (first_id, second_id)

        layer_id = (
            first.getCompositionSnapshot().compositions[first_id].layers[0].layer_id
        )
        assert first.setLayerVisible(first_id, layer_id, False)
        qapp.processEvents()
        shared_layer = second.compositionService().layers.layer(first_id, layer_id)
        assert shared_layer is not None
        assert not shared_layer.visible
        assert second.currentCompositionID() == second_id
    finally:
        first.close()
        second.close()
        document.close()


def test_inspection_shares_only_when_sessions_receive_the_same_store() -> None:
    """Independent sessions do not accidentally synchronize inspection state."""
    isolated_a = CanvasViewSession()
    isolated_b = CanvasViewSession()
    shared = InspectionStateStore()
    linked_a = CanvasViewSession(inspection=shared)
    linked_b = CanvasViewSession(inspection=shared)

    assert isolated_a.inspection is not isolated_b.inspection
    assert linked_a.inspection is linked_b.inspection


def test_inspection_ignores_transient_nonpositive_viewport_zoom() -> None:
    """A detaching view cannot publish invalid normalized inspection state."""
    composition_id = uuid.uuid4()
    session = CanvasViewSession()
    viewport = _InspectionViewport(-0.25)
    binding = SessionInspectionBinding(
        session=session,
        viewport=viewport,
        target_bounds=lambda target_id: (
            QRectF(0.0, 0.0, 640.0, 480.0) if target_id == composition_id else None
        ),
        viewport_size=lambda: QSizeF(640.0, 480.0),
    )
    try:
        assert session.activate(composition_id, available_ids=(composition_id,))

        binding.publish()

        assert session.inspection.state_for(composition_id) is None
    finally:
        binding.close()


def test_linked_sessions_project_native_zoom_between_different_sizes(qapp) -> None:
    """Live view linking preserves region while each target keeps native zoom."""
    document = CanvasDocument()
    inspection = InspectionStateStore()
    first_session = CanvasViewSession(inspection=inspection)
    second_session = CanvasViewSession(inspection=inspection)
    first = CuteCanvas(document=document, session=first_session, features=())
    second = CuteCanvas(document=document, session=second_session, features=())
    try:
        first.resize(500, 500)
        second.resize(500, 500)
        first_id = first.createComposition(
            QRectF(0.0, 0.0, 1000.0, 1000.0),
            title="Low resolution",
        )
        second_id = first.createComposition(
            QRectF(0.0, 0.0, 2000.0, 2000.0),
            title="High resolution",
        )
        first.openComposition(first_id)
        second.openComposition(second_id)
        inspection.replace_groups((LinkedGroup(uuid.uuid4(), (first_id, second_id)),))

        first.view().viewport.zoom_mode = ViewportZoomMode.CUSTOM
        first.view().viewport.setZoomAndPan(2.0, QPointF(80.0, -40.0))
        qapp.processEvents()

        assert second.view().viewport.zoom == 1.0
        assert second.view().viewport.pan == QPointF(80.0, -40.0)
    finally:
        first.close()
        second.close()
        document.close()


def test_shared_mask_history_notifies_every_mounted_view(qapp) -> None:
    """Mask replay stays document-owned while every view refreshes its products."""
    document = CanvasDocument()
    first = CuteCanvas(document=document, features=("mask",))
    second = CuteCanvas(document=document, features=("mask",))
    first_changes: list[uuid.UUID] = []
    second_changes: list[uuid.UUID] = []
    first.maskUndoStackChanged.connect(first_changes.append)
    second.maskUndoStackChanged.connect(second_changes.append)
    try:
        composition_id = first.createComposition(
            QRectF(0.0, 0.0, 64.0, 64.0),
            title="Shared mask",
        )
        first.openComposition(composition_id)
        second.openComposition(composition_id)
        mask_id = first.createBlankMask(QSize(64, 64))
        assert mask_id is not None
        second.setActiveMaskID(mask_id)
        image = QImage(64, 64, QImage.Format.Format_Grayscale8)
        image.fill(255)

        assert document.masks.commit_mask_image(mask_id, image)
        assert first.undoSceneEdit()
        qapp.processEvents()

        assert mask_id in first_changes
        assert mask_id in second_changes
        restored = document.masks.get_mask_image_copy(mask_id)
        assert restored is not None
        assert QColor(restored.pixel(32, 32)).red() == 0
    finally:
        first.close()
        second.close()
        document.close()


def test_hybrid_mask_history_survives_view_projection_rebinding(qapp) -> None:
    """Rebinding a view cannot fork hybrid mask state or its chronology."""
    document = CanvasDocument()
    first = CuteCanvas(document=document, features=("mask",))
    second = CuteCanvas(document=document, features=("mask",))
    first_changes: list[uuid.UUID] = []
    second_changes: list[uuid.UUID] = []
    first.maskUndoStackChanged.connect(first_changes.append)
    second.maskUndoStackChanged.connect(second_changes.append)
    try:
        composition_id = first.createComposition(
            QRectF(0.0, 0.0, 64.0, 64.0),
            title="Hybrid mask",
        )
        other_id = first.createComposition(
            QRectF(0.0, 0.0, 32.0, 32.0),
            title="Temporary projection",
        )
        first.openComposition(composition_id)
        second.openComposition(composition_id)
        mask_id = first.createBlankMask(QSize(64, 64))
        assert mask_id is not None
        assert first.setActiveMaskID(mask_id)
        assert second.setActiveMaskID(mask_id)
        assert (
            first.addCoverageShape(
                VectorShapeKind.RECTANGLE,
                QRectF(8.0, 8.0, 48.0, 48.0),
                PixelSelectionMode.ADD,
            )
            is not None
        )
        generated = np.zeros((64, 64), dtype=np.uint8)
        generated[24:40, 24:40] = 255
        first.mask_service.handleGeneratedMask(
            generated,
            np.array((24, 24, 39, 39), dtype=np.int32),
            erase_mode=True,
        )
        erased = document.masks.get_mask_image_copy(mask_id)
        assert erased is not None
        assert erased.pixelColor(32, 32).red() == 0

        second.openComposition(other_id)
        second.openComposition(composition_id)
        assert second.setActiveMaskID(mask_id)
        assert second.undoSceneEdit()
        qapp.processEvents()

        restored = document.masks.get_mask_image_copy(mask_id)
        assert restored is not None
        assert restored.pixelColor(32, 32).red() == 255
        layer = document.masks.get_layer(mask_id)
        assert layer is not None and layer.coverage.has_retained_items
        assert mask_id in first_changes
        assert mask_id in second_changes
    finally:
        first.close()
        second.close()
        document.close()


def test_floating_replay_restores_only_its_originating_view_session(qapp) -> None:
    """Shared pixel history must not replace another view's transient selection."""
    document = CanvasDocument()
    first = CuteCanvas(document=document, features=("mask",))
    second = CuteCanvas(document=document, features=("mask",))
    image = QImage(256, 256, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("midnightblue"))
    composition_id = first.createCompositionFromImage(image, title="Shared")
    first.resize(512, 512)
    second.resize(512, 512)
    first.show()
    second.show()
    try:
        first.openComposition(composition_id)
        second.openComposition(composition_id)
        first.setZoomFit()
        second.setZoomFit()
        qapp.processEvents()
        base_layer = (
            first.getCompositionSnapshot().compositions[composition_id].layers[0]
        )
        mask_id = first.createBlankMask(QSize(256, 256))
        assert mask_id is not None
        mask = first.mask_service.assets.get_layer(mask_id)
        mask_info = next(
            item for item in first.listMasksForComposition() if item.mask_id == mask_id
        )
        assert mask is not None
        assert mask_info.scene_id is not None
        assert mask_info.layer_id is not None
        first_scene = first.currentScene()
        second_scene = second.currentScene()
        assert first_scene is not None and second_scene is not None
        first.setActiveMaskID(mask_id)
        qapp.processEvents()
        first.setLayerInteractionPolicy(
            first_scene.scene_id,
            mask_info.layer_id,
            LayerPolicy(selectable=True, movable=True, pixel_editable=True),
        )
        first.setSelectedLayer(first_scene.scene_id, mask_info.layer_id)
        second.setSelectedLayer(second_scene.scene_id, base_layer.layer_id)
        assert first.selectedLayer() is not None
        assert first.selectedLayer().layer_id == mask_info.layer_id
        assert second.selectedLayer() is not None
        assert second.selectedLayer().layer_id == base_layer.layer_id

        def paint_square(pixels: np.ndarray, _image: QImage) -> None:
            """Author one compact payload for the selected-pixel move."""
            pixels[60:100, 60:100] = 255

        mask.coverage.raster.mutate(paint_square)
        first.invalidateActiveMaskCache()
        qapp.processEvents()
        selection = QImage(40, 40, QImage.Format.Format_Grayscale8)
        selection.fill(255)
        assert first.setPixelSelection(selection, QRect(60, 60, 40, 40))
        coordinates = first.activeMaskLayerCoordinates()
        start = coordinates.source_to_panel(QPoint(80, 80))
        finish = coordinates.source_to_panel(QPoint(130, 110))
        assert start is not None and finish is not None
        first.setControlMode(first.CONTROL_MODE_MOVE)
        QTest.mousePress(first, Qt.LeftButton, Qt.NoModifier, start.toPoint())
        QTest.mouseMove(first, finish.toPoint(), delay=0)
        QTest.mouseRelease(first, Qt.LeftButton, Qt.NoModifier, finish.toPoint())
        assert first.floatingPixelEditState() is not None
        assert first.anchorFloatingPixels()
        assert first.floatingPixelEditState() is None
        first.setSelectedLayer(first_scene.scene_id, base_layer.layer_id)
        assert first.selectedLayer().layer_id == base_layer.layer_id

        assert first.undoSceneEdit()
        qapp.processEvents()

        assert first.selectedLayer() is not None
        assert first.selectedLayer().layer_id == mask_info.layer_id
        second_selection = second.selectedLayer()
        assert second_selection is not None
        assert second_selection.layer_id == base_layer.layer_id
    finally:
        first.close()
        second.close()
        document.close()
