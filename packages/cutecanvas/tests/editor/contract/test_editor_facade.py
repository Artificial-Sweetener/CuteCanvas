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
"""Public typed-handle contracts for CuteCanvas's focused editor facade."""

from __future__ import annotations

import pytest
from cutecanvas import (
    CloneStampAlignment,
    CloneStampSampleMode,
    CloneStampTransform,
    CuteCanvas,
)
from cutecanvas_test_support.harness.timing import interaction_clock
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QImage, QTransform
from qpane.sdk.rendering import PanelPoint, ScenePoint


def test_canvas_emits_public_control_mode_changes(qapp) -> None:
    """Hosts should observe public and internal tool transitions through CuteCanvas."""

    del qapp
    canvas = CuteCanvas(features=())
    try:
        observed: list[str] = []
        canvas.controlModeChanged.connect(observed.append)

        canvas.setControlMode(canvas.CONTROL_MODE_MOVE)
        canvas.interaction.set_control_mode(canvas.CONTROL_MODE_PANZOOM)

        assert observed == [
            canvas.CONTROL_MODE_MOVE,
            canvas.CONTROL_MODE_PANZOOM,
        ]
    finally:
        canvas.deleteLater()


def test_scene_rect_mapping_tracks_the_mounted_viewport(qapp) -> None:
    """Host overlays should map scene geometry without reaching into QPane."""
    canvas = CuteCanvas(features=())
    canvas.resize(800, 600)
    canvas.show()
    try:
        assert canvas.sceneToPanelRect(QRectF(0.0, 0.0, 10.0, 10.0)) is None
        with pytest.raises(TypeError, match="QRectF"):
            canvas.sceneToPanelRect(None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="valid QRectF"):
            canvas.sceneToPanelRect(QRectF())
        canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 400.0, 300.0),
            title="Mapped document",
        )
        image = QImage(400, 300, QImage.Format_ARGB32_Premultiplied)
        image.fill(0xFF336699)
        assert canvas.addEditableRasterLayer(image, label="Background") is not None
        canvas.setZoomFit()
        qapp.processEvents()

        scene_rect = QRectF(120.0, 90.0, 80.0, 60.0)
        panel_rect = canvas.sceneToPanelRect(scene_rect)
        assert panel_rect is not None and panel_rect.isValid()
        hit = canvas.sceneHitTest(panel_rect.center().toPoint())
        assert hit is not None
        assert hit.scene_point.x() == pytest.approx(scene_rect.center().x(), abs=0.6)
        assert hit.scene_point.y() == pytest.approx(scene_rect.center().y(), abs=0.6)

        canvas.applyZoom(canvas.currentZoom() * 1.25, panel_rect.center())
        qapp.processEvents()
        zoomed = canvas.sceneToPanelRect(scene_rect)
        assert zoomed is not None
        assert zoomed.width() > panel_rect.width()
        assert zoomed.height() > panel_rect.height()
    finally:
        canvas.close()
        canvas.deleteLater()
        qapp.processEvents()


def test_typed_handles_route_document_layer_tool_and_history_workflows(qapp) -> None:
    """Common editing should not require callers to pass scene/layer ID pairs."""
    canvas = CuteCanvas(features=())
    try:
        document = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 640.0, 480.0),
            title="Handle document",
        )
        image = QImage(80, 60, QImage.Format_ARGB32_Premultiplied)
        image.fill(0xFF336699)
        layer_id = canvas.addEditableRasterLayer(image, label="Paint")
        assert layer_id is not None

        layer = document.layer(layer_id)
        assert layer is not None
        assert layer.state.label == "Paint"
        assert layer.select()
        assert layer.set_transform(QTransform.fromTranslate(25.0, 35.0))
        assert canvas.editor.history.can_undo
        assert canvas.editor.history.undo()
        assert canvas.editor.history.can_redo

        canvas.editor.tools.activate(canvas.CONTROL_MODE_MOVE)
        assert canvas.editor.tools.active == canvas.CONTROL_MODE_MOVE
        assert canvas.editor.selection.state is not None

        other = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 320.0, 240.0),
            title="Other",
        )
        assert other.is_open
        with pytest.raises(RuntimeError, match="open the layer's composition"):
            layer.select()
        document.open()
        assert layer.select()
    finally:
        canvas.deleteLater()


def test_reopening_active_composition_is_a_fast_viewport_preserving_noop(qapp) -> None:
    """Repeated active-row actions must not refit or republish the composition."""
    canvas = CuteCanvas(features=())
    canvas.resize(900, 700)
    canvas.show()
    try:
        document = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 1600.0, 1200.0),
            title="Active composition",
        )
        image = QImage(1600, 1200, QImage.Format_ARGB32_Premultiplied)
        image.fill(0xFF336699)
        assert canvas.addEditableRasterLayer(image, label="Background") is not None
        qapp.processEvents()
        canvas.applyZoom(2.25)
        canvas.setPan(QPointF(185.0, 130.0))
        qapp.processEvents()
        zoom_before = canvas.currentZoom()
        pan_before = QPointF(canvas.view().viewport.pan)
        scene_events: list[object] = []
        selection_events: list[object] = []
        canvas.sceneChanged.connect(scene_events.append)
        canvas.compositionSelectionChanged.connect(selection_events.append)

        started = interaction_clock()
        for _index in range(500):
            document.open()
        elapsed = interaction_clock() - started

        assert elapsed < 0.25
        assert canvas.currentZoom() == zoom_before
        assert canvas.view().viewport.pan == pan_before
        assert scene_events == []
        assert selection_events == []
    finally:
        canvas.close()
        canvas.deleteLater()
        qapp.processEvents()


def test_persistence_facade_round_trips_complete_raster_document(
    qapp, tmp_path
) -> None:
    """The focused facade should preserve document and resource identity."""
    canvas = CuteCanvas(features=())
    try:
        document = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 640.0, 480.0),
            title="Archive document",
        )
        image = QImage(96, 72, QImage.Format_ARGB32_Premultiplied)
        image.fill(0xFFCC8844)
        layer_id = canvas.addEditableRasterLayer(image, label="Archived pixels")
        assert layer_id is not None
        archive_path = tmp_path / "document.cutecanvas"

        canvas.editor.persistence.save(document, archive_path)
        document.remove()
        assert canvas.editor.compositions.get(document.id) is None

        restored = canvas.editor.persistence.load(archive_path)
        assert restored.id == document.id
        assert restored.is_open
        assert [layer.state.label for layer in restored.layers] == ["Archived pixels"]
        restored_layer = restored.layer(layer_id)
        assert restored_layer is not None
        assert restored_layer.select()
    finally:
        canvas.deleteLater()


def test_clone_stamp_facade_configures_and_activates_the_shared_brush_tool(
    qapp,
) -> None:
    """Hosts can configure the complete Clone Stamp workflow through one subfacade."""
    canvas = CuteCanvas(features=())
    try:
        document = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 64.0, 48.0),
            title="Clone document",
        )
        image = QImage(64, 48, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0xFF336699)
        layer_id = canvas.addEditableRasterLayer(image, label="Clone target")
        assert layer_id is not None
        assert canvas.setPaintTarget(document.id, layer_id)

        clone_stamp = canvas.editor.clone_stamp
        assert clone_stamp.set_alignment(CloneStampAlignment.UNALIGNED)
        assert clone_stamp.set_sample_mode(CloneStampSampleMode.VISIBLE_COMPOSITE)
        transform = CloneStampTransform(
            rotation_degrees=22.5,
            scale_x=1.25,
            scale_y=0.75,
            mirror_vertical=True,
        )
        assert clone_stamp.set_transform(transform)
        assert clone_stamp.set_source(QPointF(12.0, 18.0))
        clone_stamp.activate()

        assert clone_stamp.state.alignment is CloneStampAlignment.UNALIGNED
        assert clone_stamp.state.sample_mode is CloneStampSampleMode.VISIBLE_COMPOSITE
        assert clone_stamp.state.transform == transform
        assert clone_stamp.state.source is not None
        assert clone_stamp.state.source.scene_point() == QPointF(12.0, 18.0)
        assert canvas.editor.tools.active == canvas.CONTROL_MODE_CLONE_STAMP
        other = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 32.0, 32.0),
            title="Other document",
        )
        assert other.is_open
        assert not canvas.cloneStampOperation().source_is_available()
        assert canvas.cloneStampOperation().source_scene_point() is None
        document.open()
        assert canvas.setPaintTarget(document.id, layer_id)
        assert canvas.cloneStampOperation().source_is_available()
        assert clone_stamp.clear_source()
        assert not clone_stamp.state.source_set
    finally:
        canvas.deleteLater()


def test_coordinate_system_tracks_the_active_editor_scene(qapp) -> None:
    """The inherited QPane facade must project only CuteCanvas's active scene."""
    canvas = CuteCanvas(features=())
    canvas.resize(480, 360)
    canvas.show()
    try:
        first = canvas.editor.compositions.create(
            QRectF(-40.0, 15.0, 320.0, 240.0),
            title="First coordinate scene",
        )
        qapp.processEvents()
        coordinates = canvas.coordinateSystem()
        assert coordinates is canvas.view().coordinates
        first_render_scene = canvas.sceneMutationCoordinator().active_scene()
        assert first_render_scene is not None
        first_point = coordinates.panel_to_scene(PanelPoint(240.0, 180.0))
        assert first_point is not None
        assert first_point.scene_id == first_render_scene.scene_id

        second = canvas.editor.compositions.create(
            QRectF(120.0, -60.0, 160.0, 120.0),
            title="Second coordinate scene",
        )
        qapp.processEvents()
        second_render_scene = canvas.sceneMutationCoordinator().active_scene()
        assert second_render_scene is not None
        assert second_render_scene.scene_id != first_render_scene.scene_id
        second_point = coordinates.panel_to_scene(PanelPoint(240.0, 180.0))
        assert second_point is not None
        assert second_point.scene_id == second_render_scene.scene_id
        assert (
            coordinates.scene_to_panel(
                ScenePoint(first_render_scene.scene_id, 0.0, 0.0)
            )
            is None
        )

        first.open()
        qapp.processEvents()
        reopened_scene = canvas.sceneMutationCoordinator().active_scene()
        assert reopened_scene is not None
        assert reopened_scene.scene_id == first_render_scene.scene_id
        assert coordinates.panel_to_scene(PanelPoint(240.0, 180.0)).scene_id == (
            reopened_scene.scene_id
        )
        assert second.is_open is False
    finally:
        canvas.close()
        canvas.deleteLater()
