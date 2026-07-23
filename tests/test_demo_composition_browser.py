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
"""Regression tests for the demo's authoritative composition-layer browser."""

from __future__ import annotations

import uuid

from cutecanvas import (
    CatalogLayerRequest,
    CompositionRequest,
    CuteCanvas,
    LayerPolicy,
)
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

from examples.cutecanvas_demo import ExampleOptions, ExampleWindow
from examples.demonstration.catalog.composition_browser import CompositionBrowser


def _image(color: str, size: QSize | None = None) -> QImage:
    """Return one small opaque catalog image."""
    image_size = QSize(20, 20) if size is None else QSize(size)
    image = QImage(image_size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(color))
    return image


def test_browser_nests_all_inactive_layers_and_selects_exact_child(qapp) -> None:
    """The browser must project inactive stacks and route child selection once."""
    viewer = CuteCanvas(features=())
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    bottom_id = uuid.uuid4()
    top_id = uuid.uuid4()
    focused: list[str] = []
    viewer.setImagesByID(
        CuteCanvas.imageMapFromLists(
            [_image("red"), _image("blue")],
            ids=[first_id, second_id],
        ),
        first_id,
    )
    layered_id = viewer.composeScene(
        CompositionRequest(
            composition_id=uuid.uuid4(),
            title="Inactive Layers",
            bounds=QRectF(0.0, 0.0, 40.0, 20.0),
            layers=(
                CatalogLayerRequest(
                    layer_id=bottom_id,
                    image_id=first_id,
                    placement=QRectF(0.0, 0.0, 20.0, 20.0),
                    interaction=LayerPolicy(selectable=True),
                    role="bottom",
                ),
                CatalogLayerRequest(
                    layer_id=top_id,
                    image_id=second_id,
                    placement=QRectF(20.0, 0.0, 20.0, 20.0),
                    interaction=LayerPolicy(selectable=True),
                    role="top",
                ),
            ),
        )
    )
    viewer.setCurrentImageID(first_id)
    browser = CompositionBrowser(
        viewer,
        on_focus_requested=focused.append,
    )
    try:
        assert browser.topLevelItemCount() == 3
        layered = next(
            browser.topLevelItem(index)
            for index in range(browser.topLevelItemCount())
            if "Inactive Layers" in browser.topLevelItem(index).text(0)
        )
        assert layered.childCount() == 2
        assert layered.child(0).data(0, Qt.ItemDataRole.UserRole)[2] == top_id
        assert layered.child(1).data(0, Qt.ItemDataRole.UserRole)[2] == bottom_id

        browser.itemClicked.emit(layered.child(0), 0)

        assert viewer.currentCompositionID() == layered_id
        selected = viewer.selectedLayer()
        assert selected is not None
        assert selected.layer_id == top_id
        assert browser.currentItem() is layered.child(0)
        assert focused == ["image"]
    finally:
        browser.deleteLater()
        viewer.deleteLater()
        qapp.processEvents()


def test_layer_properties_request_opens_one_focused_modal(qapp) -> None:
    """The composition tree should route properties into an uncluttered modal."""
    window = ExampleWindow(ExampleOptions(feature_set="core"))
    try:
        image_id = uuid.uuid4()
        window.qpane.setImagesByID(
            CuteCanvas.imageMapFromLists([_image("green")], ids=[image_id]),
            image_id,
        )
        editable = QImage(20, 20, QImage.Format.Format_ARGB32_Premultiplied)
        editable.fill(Qt.GlobalColor.transparent)
        layer_id = window.qpane.addEditableRasterLayer(editable, label="Editable")
        scene = window.qpane.currentScene()
        composition_id = window.qpane.currentCompositionID()
        assert scene is not None and composition_id is not None and layer_id is not None
        assert window.qpane.setSelectedLayer(scene.scene_id, layer_id)

        assert window.catalog_ui.dock is not None
        window.catalog_ui.dock.layerPropertiesRequested.emit(composition_id, layer_id)
        qapp.processEvents()

        dialog = window.catalog_ui._layer_properties_dialog
        assert dialog is not None and dialog.isVisible() and dialog.isModal()
        assert dialog.raster_storage._target == (scene.scene_id, layer_id)
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_layer_row_checkbox_changes_visibility_and_history(qapp) -> None:
    """The demo should expose generic visibility without a laboratory panel."""
    viewer = CuteCanvas(features=())
    browser = CompositionBrowser(viewer, on_focus_requested=lambda _focus: None)
    try:
        document = viewer.editor.documents.create(QRectF(0.0, 0.0, 80.0, 60.0))
        layer_id = viewer.addEditableRasterLayer(_image("green"), label="Subject")
        assert layer_id is not None
        browser.refresh()
        qapp.processEvents()
        root = browser.topLevelItem(0)
        row = root.child(0)
        assert row.checkState(0) is Qt.CheckState.Checked

        row.setCheckState(0, Qt.CheckState.Unchecked)
        qapp.processEvents()

        layer = document.layer(layer_id)
        assert layer is not None and not layer.state.visible
        assert viewer.undoSceneEdit()
        assert layer.state.visible
    finally:
        browser.deleteLater()
        viewer.deleteLater()
        qapp.processEvents()


def test_browser_selection_and_hover_use_transient_content_effects(qapp) -> None:
    """The polished browser lesson highlights layers without editor mutations."""
    viewer = CuteCanvas(features=())
    document = viewer.editor.documents.create(QRectF(0.0, 0.0, 80.0, 60.0))
    layer_id = viewer.addEditableRasterLayer(_image("green"), label="Subject")
    assert layer_id is not None
    layer = document.layer(layer_id)
    assert layer is not None
    history_before = (
        viewer.editor.history.can_undo,
        viewer.editor.history.can_redo,
    )
    browser = CompositionBrowser(viewer, on_focus_requested=lambda _focus: None)
    try:
        layer.select()
        qapp.processEvents()
        root = browser.topLevelItem(0)
        row = next(
            root.child(index)
            for index in range(root.childCount())
            if root.child(index).data(0, Qt.ItemDataRole.UserRole)[2] == layer_id
        )
        selected_effects = viewer.layerPresentationEffects()
        assert len(selected_effects) == 1
        assert selected_effects[0].layer_id == layer_id

        browser._highlight_hovered_layer(row, 0)
        hovered_effects = viewer.layerPresentationEffects()
        assert len(hovered_effects) == 2
        assert all(effect.layer_id == layer_id for effect in hovered_effects)

        browser._highlights.hover(None)
        assert len(viewer.layerPresentationEffects()) == 1
        assert (
            viewer.editor.history.can_undo,
            viewer.editor.history.can_redo,
        ) == history_before
        browser.close()
        qapp.processEvents()
        assert viewer.layerPresentationEffects() == ()
    finally:
        browser.close()
        browser.deleteLater()
        viewer.deleteLater()
        qapp.processEvents()


def test_demo_composition_creation_placement_and_policy_are_intentional(qapp) -> None:
    """The compact browser should expose complete composition-first workflows."""
    window = ExampleWindow(ExampleOptions(feature_set="core"))
    try:
        image_id = uuid.uuid4()
        window.qpane.setImagesByID(
            CuteCanvas.imageMapFromLists([_image("blue")], ids=[image_id]),
            image_id,
        )
        dock = window.catalog_ui.dock
        assert dock is not None

        dock._handle_new_composition()
        empty_id = window.qpane.currentCompositionID()
        empty_scene = window.qpane.currentScene()
        assert empty_id is not None and empty_scene is not None
        assert empty_scene.layers == ()

        dock._add_catalog_image_to_composition(image_id)
        placed_scene = window.qpane.currentScene()
        assert placed_scene is not None and len(placed_scene.layers) == 1
        placed = placed_scene.layers[0]
        assert placed.source_id == image_id
        assert placed.interaction.selectable
        assert not placed.interaction.movable
        assert placed.interaction.removable

        dock._create_from_catalog_image(image_id)
        seeded_id = window.qpane.currentCompositionID()
        seeded_scene = window.qpane.currentScene()
        assert seeded_id is not None and seeded_id != empty_id
        assert seeded_scene is not None and len(seeded_scene.layers) == 1
        assert seeded_scene.layers[0].layer_id != placed.layer_id

        dock.compositionPropertiesRequested.emit(seeded_id)
        qapp.processEvents()
        dialog = window.catalog_ui._composition_properties_dialog
        assert dialog is not None and dialog.isVisible() and dialog.isModal()
        dialog.removable.setChecked(False)
        dialog.comparison_enabled.setChecked(False)
        dialog._save()
        entry = window.qpane.getCompositionSnapshot().compositions[seeded_id]
        assert not entry.policy.removable
        assert not entry.policy.comparison_enabled
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_browser_drag_reorders_one_stack_and_history_restores_it(qapp) -> None:
    """A visible tree drag must use the public chronological stack mutation."""
    viewer = CuteCanvas(features=())
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    bottom_id = uuid.uuid4()
    top_id = uuid.uuid4()
    viewer.setImagesByID(
        CuteCanvas.imageMapFromLists(
            [_image("red"), _image("blue")],
            ids=[first_id, second_id],
        ),
        first_id,
    )
    composition_id = viewer.composeScene(
        CompositionRequest(
            composition_id=uuid.uuid4(),
            title="Reorder",
            bounds=QRectF(0.0, 0.0, 40.0, 20.0),
            layers=(
                CatalogLayerRequest(
                    layer_id=bottom_id,
                    image_id=first_id,
                    placement=QRectF(0.0, 0.0, 20.0, 20.0),
                    interaction=LayerPolicy(selectable=True),
                ),
                CatalogLayerRequest(
                    layer_id=top_id,
                    image_id=second_id,
                    placement=QRectF(20.0, 0.0, 20.0, 20.0),
                    interaction=LayerPolicy(selectable=True),
                ),
            ),
        )
    )
    viewer.openComposition(composition_id)
    assert viewer.currentCompositionID() == composition_id
    browser = CompositionBrowser(viewer, on_focus_requested=lambda _focus: None)
    try:
        browser.resize(260, 220)
        browser.show()
        qapp.processEvents()
        root = next(
            browser.topLevelItem(index)
            for index in range(browser.topLevelItemCount())
            if "Reorder" in browser.topLevelItem(index).text(0)
        )
        assert root.childCount() == 2
        moved = root.takeChild(0)
        assert moved is not None
        payload = moved.data(0, Qt.ItemDataRole.UserRole)
        root.insertChild(1, moved)
        browser._commit_visual_reorder(moved, payload)

        entry = viewer.getCompositionSnapshot().compositions[composition_id]
        assert tuple(layer.layer_id for layer in entry.layers) == (top_id, bottom_id)
        assert viewer.undoSceneEdit()
        restored = viewer.getCompositionSnapshot().compositions[composition_id]
        assert tuple(layer.layer_id for layer in restored.layers) == (
            bottom_id,
            top_id,
        )
    finally:
        browser.close()
        browser.deleteLater()
        viewer.deleteLater()
        qapp.processEvents()


def test_browser_refreshes_each_composition_immediately_after_layer_lifecycle(
    qapp,
) -> None:
    """Each composition row must reflect layer additions without incidental refreshes."""
    window = ExampleWindow(ExampleOptions(feature_set="core"))
    try:
        first_id = uuid.uuid4()
        second_id = uuid.uuid4()
        window.qpane.setImagesByID(
            CuteCanvas.imageMapFromLists(
                [_image("red"), _image("blue")],
                ids=[first_id, second_id],
            ),
            first_id,
        )
        assert window.catalog_ui.dock is not None
        browser = window.catalog_ui.dock._composition_browser
        first_composition = window.qpane.currentCompositionID()
        assert first_composition is not None
        qapp.processEvents()
        composition_events = []
        window.qpane.compositionChanged.connect(composition_events.append)
        first_layer = window.qpane.addEditableRasterLayer(
            _image("green"),
            label="First paint",
        )
        assert first_layer is not None
        qapp.processEvents()
        assert composition_events
        first_event_count = len(composition_events)

        second_composition = next(
            entry.composition_id
            for entry in window.qpane.getCompositionSnapshot().compositions.values()
            if entry.current_image_id == second_id
        )
        window.qpane.openComposition(second_composition)
        second_layer = window.qpane.addEditableRasterLayer(
            _image("yellow"),
            label="Second paint",
        )
        assert second_layer is not None
        qapp.processEvents()
        assert len(composition_events) > first_event_count

        first_item = browser._composition_items[first_composition]
        second_item = browser._composition_items[second_composition]
        assert [
            first_item.child(index).text(0) for index in range(first_item.childCount())
        ] == [
            "First paint",
            "Background",
        ]
        assert [
            second_item.child(index).text(0)
            for index in range(second_item.childCount())
        ] == ["Second paint", "Background"]
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_demo_browser_survives_repeated_cross_composition_layer_activation(
    qapp,
) -> None:
    """Repeated tree activation must never retain deleted rows or lose child stacks."""
    window = ExampleWindow(ExampleOptions(feature_set="mask"))
    try:
        first_id = uuid.uuid4()
        second_id = uuid.uuid4()
        window.qpane.setImagesByID(
            CuteCanvas.imageMapFromLists(
                [
                    _image("red", QSize(2048, 1536)),
                    _image("blue", QSize(2048, 1536)),
                ],
                ids=[first_id, second_id],
            ),
            first_id,
        )
        composition_ids = tuple(window.qpane.compositionIDs())
        assert len(composition_ids) == 2
        assert window.catalog_ui.dock is not None
        browser = window.catalog_ui.dock._composition_browser
        window.show()
        window.catalog_ui.dock.show()
        browser.show()
        qapp.processEvents()
        for composition_id, color in zip(composition_ids, ("green", "yellow")):
            window.qpane.openComposition(composition_id)
            assert window.qpane.addEditableRasterLayer(
                _image(color, QSize(1024, 768)),
                label=f"Paint {color}",
            )
            assert window.qpane.createBlankMask(QSize(2048, 1536)) is not None
            qapp.processEvents()

        for index in range(100):
            composition_id = composition_ids[index % len(composition_ids)]
            composition_item = browser._composition_items[composition_id]
            item = composition_item.child(0) if index % 2 == 0 else composition_item
            payload = item.data(0, Qt.ItemDataRole.UserRole)
            browser.scrollToItem(item)
            qapp.processEvents()
            QTest.mouseClick(
                browser.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                browser.visualItemRect(item).center(),
            )
            qapp.processEvents()
            assert window.qpane.currentCompositionID() == composition_id
            assert browser.currentItem() is not None
            current_payload = browser.currentItem().data(0, Qt.ItemDataRole.UserRole)
            assert current_payload[1] == composition_id
            if payload[0] == "layer":
                assert current_payload == payload
            assert browser._composition_items[composition_id].childCount() == 3
            if index % 4 == 0:
                assert not window.qpane.grab().isNull()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()
