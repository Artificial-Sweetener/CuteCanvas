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
"""Public composition-first document and resource behavior."""

from __future__ import annotations

from cutecanvas import CompositionPolicy, CuteCanvas, LayerPolicy
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage


def _image(color: str, width: int = 80, height: int = 60) -> QImage:
    """Return one opaque catalog resource."""
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(color))
    return image


def test_empty_composition_is_editable_without_seed_resource(qapp) -> None:
    """An empty document must own a canvas and accept ordinary layer creation."""
    viewer = CuteCanvas(features=())
    try:
        composition_id = viewer.createComposition(
            QRectF(-100.0, -50.0, 640.0, 480.0),
            title="Empty document",
        )

        scene = viewer.currentScene()
        entry = viewer.getCompositionSnapshot().compositions[composition_id]
        assert viewer.currentCompositionID() == composition_id
        assert scene is not None
        assert scene.bounds == QRectF(-100.0, -50.0, 640.0, 480.0)
        assert scene.layers == ()
        assert entry.kind == "composition"
        assert entry.scene_bounds == scene.bounds

        pixels = QImage(32, 24, QImage.Format.Format_ARGB32_Premultiplied)
        pixels.fill(Qt.GlobalColor.transparent)
        layer_id = viewer.addEditableRasterLayer(pixels, label="Paint")
        assert layer_id is not None
        assert [layer.layer_id for layer in viewer.currentScene().layers] == [layer_id]
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_image_seed_is_an_ordinary_project_resource_layer(qapp) -> None:
    """Each imported image document must own an ordinary independent resource."""
    viewer = CuteCanvas(features=())
    try:
        image = _image("red")
        interaction = LayerPolicy(
            selectable=True,
            movable=True,
            pixel_editable=False,
            reorderable=True,
            removable=True,
        )
        first = viewer.createCompositionFromImage(
            image,
            title="First seed",
            interaction=interaction,
        )
        first_scene = viewer.currentScene()
        assert first_scene is not None and len(first_scene.layers) == 1
        first_layer = first_scene.layers[0]
        assert first_layer.role == "content"
        assert first_layer.source_kind == "imported-raster"

        second = viewer.createCompositionFromImage(
            image,
            title="Second seed",
            interaction=interaction,
        )
        second_scene = viewer.currentScene()
        assert second_scene is not None and len(second_scene.layers) == 1
        second_layer = second_scene.layers[0]
        assert first != second
        assert first_layer.layer_id != second_layer.layer_id
        assert first_layer.source_id != second_layer.source_id

        assert viewer.removeLayer(second_scene.scene_id, second_layer.layer_id)
        assert viewer.currentScene().layers == ()
        viewer.openComposition(first)
        assert [layer.layer_id for layer in viewer.currentScene().layers] == [
            first_layer.layer_id
        ]
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_imported_resources_place_into_active_composition_with_host_policy(
    qapp,
) -> None:
    """Imported images must use ordinary document layer policy."""
    viewer = CuteCanvas(features=())
    try:
        composition_id = viewer.createComposition(
            QRectF(0.0, 0.0, 320.0, 240.0),
            title="Assembly",
        )
        locked_id = viewer.placeEmbeddedAsset(
            _image("red"),
            label="Locked",
            interaction=LayerPolicy(
                selectable=True,
                movable=False,
                reorderable=False,
                removable=False,
            ),
        )
        movable_id = viewer.placeEmbeddedAsset(
            _image("blue", 40, 30),
            placement=QRectF(100.0, 80.0, 80.0, 60.0),
            label="Movable",
            interaction=LayerPolicy(
                selectable=True,
                movable=True,
                reorderable=True,
                removable=True,
            ),
        )
        assert locked_id is not None and movable_id is not None
        scene = viewer.currentScene()
        assert scene is not None and scene.composition_id == composition_id
        assert [layer.layer_id for layer in scene.layers] == [locked_id, movable_id]
        assert not viewer.setLayerIndex(scene.scene_id, locked_id, 1)
        assert not viewer.removeLayer(scene.scene_id, locked_id)
        assert viewer.setLayerIndex(scene.scene_id, movable_id, 0)
        assert viewer.removeLayer(scene.scene_id, movable_id)
        assert [layer.layer_id for layer in viewer.currentScene().layers] == [locked_id]
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_empty_composition_accepts_mask_and_vector_domains(qapp) -> None:
    """Composition-scoped authoring must not require a current catalog image."""
    viewer = CuteCanvas(features=("mask",))
    try:
        viewer.createComposition(QRectF(0.0, 0.0, 256.0, 192.0))

        mask_id = viewer.createBlankMask(QSize(64, 48))
        vector_layer_id = viewer.createVectorLayer(QSize(80, 60), label="Vector")

        assert mask_id is not None
        assert vector_layer_id is not None
        assert {layer.source_kind for layer in viewer.currentScene().layers} == {
            "coverage",
            "vector",
        }
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_image_free_composition_cycles_masks_in_generic_stack(qapp) -> None:
    """Mask cycle commands must adapt to the active document without an image."""
    viewer = CuteCanvas(features=("mask",))
    try:
        viewer.createComposition(QRectF(0.0, 0.0, 256.0, 192.0))
        first_id = viewer.createBlankMask(QSize(64, 48))
        second_id = viewer.createBlankMask(QSize(64, 48))
        assert first_id is not None and second_id is not None

        assert viewer.setActiveMaskID(first_id)
        assert [layer.source_id for layer in viewer.currentScene().layers] == [
            second_id,
            first_id,
        ]
        assert viewer.cycleMasksForward()
        assert viewer.activeMaskID() == second_id
        assert [layer.source_id for layer in viewer.currentScene().layers] == [
            first_id,
            second_id,
        ]
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_document_policy_is_host_controlled_and_origin_independent(qapp) -> None:
    """Hosts must control document removal without content-kind branches."""
    viewer = CuteCanvas(features=())
    try:
        composition_id = viewer.createComposition(
            QRectF(0.0, 0.0, 320.0, 240.0),
            title="Policy document",
            policy=CompositionPolicy(
                removable=False,
            ),
        )
        entry = viewer.getCompositionSnapshot().compositions[composition_id]
        assert entry.policy == CompositionPolicy(
            removable=False,
        )
        try:
            viewer.removeComposition(composition_id)
        except ValueError:
            pass
        else:
            raise AssertionError("document policy must prevent removal")

        assert viewer.setCompositionPolicy(
            composition_id,
            CompositionPolicy(removable=True),
        )
        assert viewer.getCompositionSnapshot().compositions[composition_id].policy == (
            CompositionPolicy(removable=True)
        )
        viewer.removeComposition(composition_id)
        assert composition_id not in viewer.compositionIDs()
    finally:
        viewer.deleteLater()
        qapp.processEvents()
