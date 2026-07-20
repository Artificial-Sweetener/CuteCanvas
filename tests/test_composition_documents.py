#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Public composition-first document behavior and compatibility adapters."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage

from qpane import QPane, QPaneCompositionPolicy, QPaneLayerInteractionPolicy


def _image(color: str, width: int = 80, height: int = 60) -> QImage:
    """Return one opaque catalog resource."""
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(color))
    return image


def test_empty_composition_is_editable_without_catalog_identity(qapp) -> None:
    """An empty document must own a canvas and accept ordinary layer creation."""
    viewer = QPane(features=())
    try:
        composition_id = viewer.createComposition(
            QRectF(-100.0, -50.0, 640.0, 480.0),
            title="Empty document",
        )

        scene = viewer.currentScene()
        entry = viewer.getCompositionSnapshot().compositions[composition_id]
        assert viewer.currentCompositionID() == composition_id
        assert viewer.currentImageID() is None
        assert scene is not None
        assert scene.bounds == QRectF(-100.0, -50.0, 640.0, 480.0)
        assert scene.layers == ()
        assert entry.kind == "composition"
        assert entry.current_image_id is None
        assert entry.scene_bounds == scene.bounds

        pixels = QImage(32, 24, QImage.Format.Format_ARGB32_Premultiplied)
        pixels.fill(Qt.GlobalColor.transparent)
        layer_id = viewer.addEditableRasterLayer(pixels, label="Paint")
        assert layer_id is not None
        assert viewer.currentImageID() is None
        assert [layer.layer_id for layer in viewer.currentScene().layers] == [layer_id]
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_image_seed_is_an_ordinary_independent_layer(qapp) -> None:
    """Seeding twice from one resource must create independent mutable instances."""
    viewer = QPane(features=())
    image_id = uuid.uuid4()
    try:
        viewer.setImagesByID(
            QPane.imageMapFromLists([_image("red")], ids=[image_id]),
            image_id,
        )
        interaction = QPaneLayerInteractionPolicy(
            selectable=True,
            movable=True,
            pixel_editable=False,
            reorderable=True,
            removable=True,
        )
        first = viewer.createCompositionFromImage(
            image_id,
            title="First seed",
            interaction=interaction,
        )
        first_scene = viewer.currentScene()
        assert first_scene is not None and len(first_scene.layers) == 1
        first_layer = first_scene.layers[0]
        assert first_layer.role == "content"
        assert first_layer.source_id == image_id

        second = viewer.createCompositionFromImage(
            image_id,
            title="Second seed",
            interaction=interaction,
        )
        second_scene = viewer.currentScene()
        assert second_scene is not None and len(second_scene.layers) == 1
        second_layer = second_scene.layers[0]
        assert first != second
        assert first_layer.layer_id != second_layer.layer_id

        assert viewer.removeLayer(second_scene.scene_id, second_layer.layer_id)
        assert viewer.currentScene().layers == ()
        viewer.openComposition(first)
        assert [layer.layer_id for layer in viewer.currentScene().layers] == [
            first_layer.layer_id
        ]
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_generated_navigation_documents_do_not_derive_instance_identity(qapp) -> None:
    """Catalog convenience documents must still own independent layer identities."""
    image_id = uuid.uuid4()
    first = QPane(features=())
    second = QPane(features=())
    try:
        image_map = QPane.imageMapFromLists([_image("red")], ids=[image_id])
        first.setImagesByID(image_map, image_id)
        second.setImagesByID(image_map, image_id)

        first_scene = first.currentScene()
        second_scene = second.currentScene()
        assert first_scene is not None and second_scene is not None
        assert first.currentCompositionID() != second.currentCompositionID()
        assert first_scene.layers[0].layer_id != second_scene.layers[0].layer_id
        assert first_scene.layers[0].source_id == image_id
        assert second_scene.layers[0].source_id == image_id
    finally:
        first.deleteLater()
        second.deleteLater()
        qapp.processEvents()


def test_catalog_resources_place_into_active_composition_with_host_policy(qapp) -> None:
    """Catalog placement and structural operations must resolve the active document."""
    viewer = QPane(features=())
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    try:
        viewer.setImagesByID(
            QPane.imageMapFromLists(
                [_image("red"), _image("blue", 40, 30)],
                ids=[first_id, second_id],
            ),
            first_id,
        )
        composition_id = viewer.createComposition(
            QRectF(0.0, 0.0, 320.0, 240.0),
            title="Assembly",
        )
        locked_id = viewer.addCatalogImageLayer(
            first_id,
            label="Locked",
            interaction=QPaneLayerInteractionPolicy(
                selectable=True,
                movable=False,
                reorderable=False,
                removable=False,
            ),
        )
        movable_id = viewer.addCatalogImageLayer(
            second_id,
            placement=QRectF(100.0, 80.0, 80.0, 60.0),
            label="Movable",
            interaction=QPaneLayerInteractionPolicy(
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


def test_catalog_resource_removal_does_not_delete_independent_document(qapp) -> None:
    """Removing a referenced resource must prune its layer, not its document."""
    viewer = QPane(features=())
    image_id = uuid.uuid4()
    try:
        viewer.setImagesByID(
            QPane.imageMapFromLists([_image("red")], ids=[image_id]),
            image_id,
        )
        composition_id = viewer.createCompositionFromImage(image_id)

        viewer.removeImagesByID((image_id,))

        assert composition_id in viewer.compositionIDs()
        viewer.openComposition(composition_id)
        scene = viewer.currentScene()
        assert scene is not None
        assert scene.layers == ()
        assert viewer.currentImageID() is None
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_empty_composition_accepts_mask_and_vector_domains(qapp) -> None:
    """Composition-scoped authoring must not require a current catalog image."""
    viewer = QPane(features=("mask",))
    try:
        viewer.createComposition(QRectF(0.0, 0.0, 256.0, 192.0))

        mask_id = viewer.createBlankMask(QSize(64, 48))
        vector_layer_id = viewer.createVectorLayer(QSize(80, 60), label="Vector")

        assert mask_id is not None
        assert vector_layer_id is not None
        assert viewer.currentImageID() is None
        assert {layer.source_kind for layer in viewer.currentScene().layers} == {
            "mask",
            "vector",
        }
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_image_free_composition_cycles_masks_in_generic_stack(qapp) -> None:
    """Legacy cycle commands must adapt to the active document without an image."""
    viewer = QPane(features=("mask",))
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
    """Hosts must control document removal and comparison without kind branches."""
    viewer = QPane(features=())
    try:
        composition_id = viewer.createComposition(
            QRectF(0.0, 0.0, 320.0, 240.0),
            title="Policy document",
            policy=QPaneCompositionPolicy(
                removable=False,
                comparison_enabled=False,
            ),
        )
        entry = viewer.getCompositionSnapshot().compositions[composition_id]
        assert entry.policy == QPaneCompositionPolicy(
            removable=False,
            comparison_enabled=False,
        )
        try:
            viewer.removeComposition(composition_id)
        except ValueError:
            pass
        else:
            raise AssertionError("document policy must prevent removal")

        assert viewer.setCompositionPolicy(
            composition_id,
            QPaneCompositionPolicy(removable=True, comparison_enabled=True),
        )
        assert viewer.getCompositionSnapshot().compositions[composition_id].policy == (
            QPaneCompositionPolicy(removable=True, comparison_enabled=True)
        )
        viewer.removeComposition(composition_id)
        assert composition_id not in viewer.compositionIDs()
    finally:
        viewer.deleteLater()
        qapp.processEvents()
