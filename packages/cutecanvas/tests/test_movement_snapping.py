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
"""Mounted Move-tool snapping workflows across real editor layers."""

from __future__ import annotations

import pytest
from cutecanvas import (
    CuteCanvas,
    LayerPolicy,
    VectorShapeKind,
    VectorStyle,
)
from cutecanvas.editor.movement import EditorMovementInteraction
from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QTransform


def _opaque_image(width: int = 100, height: int = 100) -> QImage:
    """Return one detached opaque raster with content-tight full bounds."""
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0xFF4FA3D1)
    return image


def _transparent_padded_image() -> QImage:
    """Return a raster whose meaningful alpha excludes its storage perimeter."""
    image = QImage(100, 80, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    for y in range(30, 42):
        for x in range(20, 30):
            image.setPixelColor(x, y, QColor(40, 120, 220, 255))
    return image


def _panel_point(canvas: CuteCanvas, scene_point: QPointF) -> QPointF:
    """Project a scene point through the mounted QPane viewport."""
    point = canvas.view().scene_to_panel_point(scene_point)
    assert point is not None
    return point


def _movement(canvas: CuteCanvas) -> EditorMovementInteraction:
    """Return the mounted editor's authoritative movement interaction."""
    movement = canvas._editor_movement_interaction
    assert movement is not None
    return movement


def test_move_hover_outline_uses_alpha_tight_layer_geometry(qapp) -> None:
    """Transparent storage padding must not enlarge Move-tool hover feedback."""
    canvas = CuteCanvas(features=())
    canvas.resize(1200, 1200)
    canvas.show()
    try:
        document = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 1000.0, 1000.0), title="Content geometry"
        )
        layer_id = canvas.addEditableRasterLayer(
            _transparent_padded_image(),
            placement=QRectF(100.0, 200.0, 200.0, 160.0),
            label="Padded",
        )
        assert layer_id is not None
        canvas.setZoom1To1()
        qapp.processEvents()
        movement = _movement(canvas)
        content_point = _panel_point(canvas, QPointF(150.0, 270.0))

        assert movement.update_hover(content_point)
        assert movement.hovered is not None
        assert movement.hovered.layer_id == layer_id
        assert movement.hovered_scene_corners == (
            QPointF(140.0, 260.0),
            QPointF(160.0, 260.0),
            QPointF(160.0, 284.0),
            QPointF(140.0, 284.0),
        )
        assert canvas.layerLocalBounds(document.id, layer_id) == QRectF(
            20.0,
            30.0,
            10.0,
            12.0,
        )
    finally:
        canvas.deleteLater()


def test_mounted_move_centers_layer_on_both_canvas_axes(qapp) -> None:
    """One diagonal drag should preview and commit exact canvas centering."""
    canvas = CuteCanvas(features=())
    canvas.resize(1200, 1200)
    canvas.show()
    try:
        document = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 1000.0, 1000.0), title="Center snapping"
        )
        layer_id = canvas.addEditableRasterLayer(_opaque_image(), label="Moving")
        assert layer_id is not None
        canvas.setZoom1To1()
        qapp.processEvents()
        movement = _movement(canvas)
        origin = _panel_point(canvas, QPointF(50.0, 50.0))
        near_center = _panel_point(canvas, QPointF(499.0, 499.0))

        assert movement.begin(origin)
        assert movement.update(near_center)
        assert {guide.axis.value for guide in movement.snap_guides} == {"x", "y"}
        box = movement._layers.transform_box_state()
        assert box is not None
        assert (box.transform.dx, box.transform.dy) == (450.0, 450.0)
        assert movement.finish(near_center)

        committed = document.layer(layer_id)
        assert committed is not None
        assert committed.state.transform == QTransform.fromTranslate(450.0, 450.0)
        assert canvas.undoSceneEdit()
        assert committed.state.transform == QTransform()
        assert canvas.redoSceneEdit()
        assert committed.state.transform == QTransform.fromTranslate(450.0, 450.0)
    finally:
        canvas.deleteLater()


def test_mounted_move_aligns_adjacent_layer_corners_on_both_axes(qapp) -> None:
    """Flat sides should meet while their adjacent corners align in one drag."""
    canvas = CuteCanvas(features=())
    canvas.resize(1200, 1200)
    canvas.show()
    try:
        document = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 1000.0, 1000.0), title="Edge snapping"
        )
        moving_id = canvas.addEditableRasterLayer(_opaque_image(), label="Moving")
        target_id = canvas.addEditableRasterLayer(_opaque_image(), label="Target")
        assert moving_id is not None and target_id is not None
        assert document.layer(target_id) is not None
        assert document.layer(target_id).set_transform(
            QTransform.fromTranslate(200.0, 200.0)
        )
        canvas.setZoom1To1()
        qapp.processEvents()
        movement = _movement(canvas)
        origin = _panel_point(canvas, QPointF(50.0, 50.0))
        near_adjacent_corner = _panel_point(canvas, QPointF(149.0, 249.0))

        assert movement.begin(origin)
        assert movement.update(near_adjacent_corner)
        box = movement._layers.transform_box_state()
        assert box is not None
        assert (box.transform.dx, box.transform.dy) == (100.0, 200.0)
        assert {guide.axis.value for guide in movement.snap_guides} == {"x", "y"}
        assert movement.finish(near_adjacent_corner)

        committed = document.layer(moving_id)
        assert committed is not None
        assert committed.state.transform == QTransform.fromTranslate(100.0, 200.0)
    finally:
        canvas.deleteLater()


def test_mounted_asymmetric_edges_do_not_lock_to_shape_centers(qapp) -> None:
    """Crossing a target center must not prevent reaching its adjacent edge."""
    canvas = CuteCanvas(features=())
    canvas.resize(1200, 1200)
    canvas.show()
    try:
        document = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 1000.0, 1000.0), title="Relationship snapping"
        )
        moving_id = canvas.addEditableRasterLayer(
            _opaque_image(300, 200), label="Moving"
        )
        target_id = canvas.addEditableRasterLayer(
            _opaque_image(300, 60), label="Target"
        )
        assert moving_id is not None and target_id is not None
        target = document.layer(target_id)
        assert target is not None
        assert target.set_transform(QTransform.fromTranslate(100.0, 100.0))
        assert canvas.setSelectedLayer(document.id, moving_id)
        moving = document.layer(moving_id)
        assert moving is not None
        assert moving.set_transform(QTransform.fromTranslate(100.0, 0.0))
        canvas.setZoom1To1()
        qapp.processEvents()
        movement = _movement(canvas)
        origin = _panel_point(canvas, QPointF(250.0, 50.0))

        assert movement.begin(origin)
        for proposed_delta in (127.0, 131.0, 129.0, 133.0, 130.0):
            center_crossing = _panel_point(
                canvas, QPointF(250.0, 50.0 + proposed_delta)
            )
            assert movement.update(center_crossing)
            box = movement._layers.transform_box_state()
            assert box is not None
            assert box.transform.dy == pytest.approx(proposed_delta)
            assert all(guide.axis.value != "y" for guide in movement.snap_guides)

        near_adjacent_edge = _panel_point(canvas, QPointF(250.0, 203.0))
        assert movement.update(near_adjacent_edge)
        box = movement._layers.transform_box_state()
        assert box is not None
        assert box.transform.dy == pytest.approx(160.0)
        assert {guide.axis.value for guide in movement.snap_guides} == {"x", "y"}
        assert movement.finish(near_adjacent_edge)
        assert moving.state.transform == QTransform.fromTranslate(100.0, 160.0)
    finally:
        canvas.deleteLater()


@pytest.mark.parametrize("source_kind", ("placed", "vector"))
def test_mounted_source_neutral_layers_share_adjacent_corner_snapping(
    qapp,
    source_kind: str,
) -> None:
    """Placed and vector sources should enter the same movement snap session."""
    canvas = CuteCanvas(features=())
    canvas.resize(1200, 1200)
    canvas.show()
    try:
        document = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 1000.0, 1000.0), title="Source-neutral snapping"
        )
        target_id = canvas.addEditableRasterLayer(_opaque_image(), label="Target")
        assert target_id is not None
        target = document.layer(target_id)
        assert target is not None
        assert target.set_transform(QTransform.fromTranslate(200.0, 200.0))
        policy = LayerPolicy(selectable=True, movable=True)
        if source_kind == "placed":
            moving_id = canvas.placeEmbeddedAsset(
                _opaque_image(),
                placement=QRectF(0.0, 0.0, 100.0, 100.0),
                label="Placed",
                interaction=policy,
            )
        else:
            moving_id = canvas.createVectorLayer(QSize(100, 100), label="Vector")
            assert moving_id is not None
            assert (
                canvas.addVectorShape(
                    document.id,
                    moving_id,
                    VectorShapeKind.RECTANGLE,
                    QRectF(0.0, 0.0, 100.0, 100.0),
                    VectorStyle(fill=QColor(40, 210, 150, 255)),
                )
                is not None
            )
            canvas.setLayerInteractionPolicy(document.id, moving_id, policy)
        assert moving_id is not None
        moving_bounds = canvas.layerLocalBounds(document.id, moving_id)
        assert moving_bounds is not None
        expected_dx = 200.0 - moving_bounds.right()
        expected_dy = 300.0 - moving_bounds.bottom()
        canvas.setZoom1To1()
        qapp.processEvents()
        movement = _movement(canvas)
        origin = _panel_point(canvas, QPointF(50.0, 50.0))
        near_adjacent_corner = _panel_point(canvas, QPointF(149.0, 249.0))

        assert movement.begin(origin)
        assert movement.update(near_adjacent_corner)
        box = movement._layers.transform_box_state()
        assert box is not None
        assert box.transform.dx == pytest.approx(expected_dx)
        assert box.transform.dy == pytest.approx(expected_dy)
        assert movement.finish(near_adjacent_corner)

        moving = document.layer(moving_id)
        assert moving is not None
        assert moving.state.transform.dx() == pytest.approx(expected_dx)
        assert moving.state.transform.dy() == pytest.approx(expected_dy)
    finally:
        canvas.deleteLater()


def test_fractional_rotated_vector_bounds_snap_without_quantization(qapp) -> None:
    """Affine target bounds should remain continuous through a two-axis snap."""
    canvas = CuteCanvas(features=())
    canvas.resize(1200, 1200)
    canvas.show()
    try:
        document = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 1000.0, 1000.0), title="Affine snapping"
        )
        moving_id = canvas.addEditableRasterLayer(_opaque_image(40, 30), label="Moving")
        target_id = canvas.createVectorLayer(QSize(400, 300), label="Target")
        assert moving_id is not None and target_id is not None
        assert canvas.addVectorShape(
            document.id,
            target_id,
            VectorShapeKind.RECTANGLE,
            QRectF(100.25, 120.5, 80.75, 60.25),
            VectorStyle(
                fill=QColor("white"),
                stroke=QColor("blue"),
                stroke_width=3.5,
            ),
        )
        target_transform = QTransform()
        target_transform.translate(260.125, 180.375)
        target_transform.rotate(17.0)
        target_transform.scale(1.25, 0.75)
        assert document.layer(target_id) is not None
        assert document.layer(target_id).set_transform(target_transform)
        target_local = canvas.layerLocalBounds(document.id, target_id)
        assert target_local is not None
        mapped_target = target_transform.mapRect(target_local)
        expected_dx = mapped_target.left() - 40.0
        expected_dy = mapped_target.bottom() - 30.0
        canvas.setZoom1To1()
        qapp.processEvents()
        movement = _movement(canvas)
        origin = _panel_point(canvas, QPointF(20.0, 15.0))
        endpoint = _panel_point(
            canvas,
            QPointF(20.0 + expected_dx + 0.5, 15.0 + expected_dy - 0.5),
        )

        assert movement.begin(origin)
        assert movement.update(endpoint)
        box = movement._layers.transform_box_state()
        assert box is not None
        assert box.transform.dx == pytest.approx(expected_dx)
        assert box.transform.dy == pytest.approx(expected_dy)
        assert movement.finish(endpoint)

        committed = canvas.layerTransform(document.id, moving_id)
        assert committed is not None
        assert committed.dx() + 40.0 == pytest.approx(mapped_target.left())
        assert committed.dy() + 30.0 == pytest.approx(mapped_target.bottom())
    finally:
        canvas.deleteLater()


def test_mounted_floating_selection_uses_same_two_axis_layer_candidates(qapp) -> None:
    """Selected pixels should snap to another layer before becoming floating."""
    canvas = CuteCanvas(features=())
    canvas.resize(1200, 1200)
    canvas.show()
    try:
        document = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 1000.0, 1000.0), title="Selection snapping"
        )
        moving_id = canvas.addEditableRasterLayer(
            _opaque_image(200, 200), label="Editable"
        )
        target_id = canvas.addEditableRasterLayer(_opaque_image(), label="Target")
        assert moving_id is not None and target_id is not None
        target = document.layer(target_id)
        assert target is not None
        assert target.set_transform(QTransform.fromTranslate(300.0, 300.0))
        assert canvas.setSelectedLayer(document.id, moving_id)
        selection = QImage(100, 100, QImage.Format.Format_Grayscale8)
        selection.fill(255)
        assert canvas.setPixelSelection(selection, QRect(0, 0, 100, 100))
        canvas.setZoom1To1()
        qapp.processEvents()
        movement = _movement(canvas)
        origin = _panel_point(canvas, QPointF(50.0, 50.0))
        near_adjacent_corner = _panel_point(canvas, QPointF(249.0, 349.0))

        assert movement.begin(origin)
        assert movement.update(near_adjacent_corner)
        box = movement.pixels.transform_box_state()
        assert box is not None
        assert box.transform.dx == pytest.approx(200.0)
        assert box.transform.dy == pytest.approx(300.0)
        assert movement.finish(near_adjacent_corner)
        floating = canvas.floatingPixelEditState()
        assert floating is not None
        assert (floating.offset.x(), floating.offset.y()) == (200, 300)
        assert canvas.anchorFloatingPixels()
        assert canvas.undoSceneEdit()
        assert canvas.redoSceneEdit()
    finally:
        canvas.deleteLater()


def test_scene_switch_clears_active_snap_session_and_guides(qapp) -> None:
    """A context switch must not retain gesture state from the old document."""
    canvas = CuteCanvas(features=())
    canvas.resize(1200, 1200)
    canvas.show()
    try:
        document = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 1000.0, 1000.0), title="Old"
        )
        moving_id = canvas.addEditableRasterLayer(_opaque_image(), label="Moving")
        target_id = canvas.addEditableRasterLayer(_opaque_image(), label="Target")
        assert moving_id is not None and target_id is not None
        target = document.layer(target_id)
        assert target is not None
        assert target.set_transform(QTransform.fromTranslate(200.0, 200.0))
        canvas.setZoom1To1()
        qapp.processEvents()
        movement = _movement(canvas)
        origin = _panel_point(canvas, QPointF(50.0, 50.0))
        near_corner = _panel_point(canvas, QPointF(149.0, 249.0))
        assert movement.begin(origin)
        assert movement.update(near_corner)
        assert movement.snap_guides

        replacement = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 500.0, 500.0), title="New"
        )
        qapp.processEvents()

        assert replacement.is_open
        assert not movement.snap_guides
        assert movement._active is None
        assert not movement.finish(near_corner)
    finally:
        canvas.deleteLater()
