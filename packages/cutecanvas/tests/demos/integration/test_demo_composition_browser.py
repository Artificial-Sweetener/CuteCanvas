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
"""Regression tests for the demo's authoritative composition-layer browser."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

from cutecanvas import CuteCanvas
from cutecanvas_demo import ExampleOptions, ExampleWindow
from cutecanvas_test_support.harness import MountedQPaneHarness
from demonstration.compositions.browser import CompositionBrowser


def _image(color: str, size: QSize | None = None) -> QImage:
    """Return one small opaque catalog image."""
    image_size = QSize(20, 20) if size is None else QSize(size)
    image = QImage(image_size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(color))
    return image


def test_browser_nests_all_inactive_layers_and_selects_exact_child(qapp) -> None:
    """The browser must project inactive stacks and route child selection once."""
    viewer = CuteCanvas(features=())
    focused: list[str] = []
    first_id = viewer.createCompositionFromImage(
        _image("red"),
        title="Red",
        label="Red",
    )
    viewer.createCompositionFromImage(
        _image("blue"),
        title="Blue",
        label="Blue",
    )
    layered_id = viewer.createComposition(
        QRectF(0.0, 0.0, 40.0, 20.0),
        title="Inactive Layers",
    )
    bottom_id = viewer.addEditableRasterLayer(
        _image("red"),
        placement=QRectF(0.0, 0.0, 20.0, 20.0),
        label="Bottom",
    )
    top_id = viewer.addEditableRasterLayer(
        _image("blue"),
        placement=QRectF(20.0, 0.0, 20.0, 20.0),
        label="Top",
    )
    assert bottom_id is not None and top_id is not None
    viewer.openComposition(first_id)
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
        assert focused == ["raster"]
    finally:
        browser.deleteLater()
        viewer.deleteLater()
        qapp.processEvents()


def test_layer_properties_request_opens_one_focused_modal(qapp) -> None:
    """Layer properties must open without disturbing the active viewport."""
    window = ExampleWindow(ExampleOptions())
    try:
        window.resize(900, 700)
        window.show()
        window.qpane.createCompositionFromImage(
            _image("green", QSize(1600, 1200)),
            title="Green",
            label="Background",
        )
        editable = QImage(
            QSize(800, 600),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        editable.fill(Qt.GlobalColor.transparent)
        layer_id = window.qpane.addEditableRasterLayer(editable, label="Editable")
        scene = window.qpane.currentScene()
        composition_id = window.qpane.currentCompositionID()
        assert scene is not None and composition_id is not None and layer_id is not None
        assert window.qpane.setSelectedLayer(scene.scene_id, layer_id)
        qapp.processEvents()
        fitted_zoom = window.qpane.currentZoom()
        window.qpane.applyZoom(2.25)
        window.qpane.setPan(QPointF(185.0, 130.0))
        qapp.processEvents()
        zoom_before = window.qpane.currentZoom()
        pan_before = QPointF(window.qpane.view().viewport.pan)
        assert zoom_before != fitted_zoom

        assert window.composition_ui.dock is not None
        browser = window.composition_ui.dock._browser
        layer_item = browser._layer_items[(composition_id, layer_id)]
        browser._activate_item(layer_item, 0)
        window.composition_ui.dock.layerPropertiesRequested.emit(
            composition_id,
            layer_id,
        )
        qapp.processEvents()

        dialog = window.composition_ui._layer_properties_dialog
        assert dialog is not None and dialog.isVisible() and dialog.isModal()
        assert dialog.raster_storage._target == (scene.scene_id, layer_id)
        assert window.qpane.currentZoom() == zoom_before
        assert window.qpane.view().viewport.pan == pan_before
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_layer_row_checkbox_changes_visibility_and_history(qapp) -> None:
    """The demo should expose generic visibility without a laboratory panel."""
    viewer = CuteCanvas(features=())
    browser = CompositionBrowser(viewer, on_focus_requested=lambda _focus: None)
    try:
        document = viewer.editor.compositions.create(QRectF(0.0, 0.0, 80.0, 60.0))
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


def test_hiding_only_raster_clears_immediately_and_keeps_canvas_navigation(
    qapp,
) -> None:
    """A semantic mask and empty raster frame must retain the composition canvas."""
    viewer = CuteCanvas(features=("mask",))
    browser = CompositionBrowser(viewer, on_focus_requested=lambda _focus: None)
    try:
        viewer.resize(320, 240)
        viewer.show()
        viewer.createCompositionFromImage(
            _image("red", QSize(160, 120)),
            title="Red",
            label="Background",
        )
        assert viewer.createBlankMask(QSize(160, 120)) is not None
        qapp.processEvents()
        browser.refresh()
        qapp.processEvents()

        scene = viewer.currentScene()
        composition_id = viewer.currentCompositionID()
        assert scene is not None and composition_id is not None
        raster = next(
            layer for layer in scene.layers if layer.source_kind == "imported-raster"
        )
        root = browser._composition_items[composition_id]
        row = next(
            root.child(index)
            for index in range(root.childCount())
            if root.child(index).data(0, Qt.ItemDataRole.UserRole)[2] == raster.layer_id
        )
        renderer = viewer.view().presenter.renderer
        viewer.grab()
        visible_buffer = renderer.get_base_buffer()
        assert visible_buffer is not None
        assert (
            visible_buffer.pixelColor(
                visible_buffer.width() // 2,
                visible_buffer.height() // 2,
            ).red()
            > 0
        )

        row.setCheckState(0, Qt.CheckState.Unchecked)
        qapp.processEvents()

        plan = viewer.view().calculateRenderPlan()
        assert plan is not None
        assert plan.render_items == ()
        viewer.grab()
        hidden_buffer = renderer.get_base_buffer()
        assert hidden_buffer is not None
        assert (
            hidden_buffer.pixelColor(
                hidden_buffer.width() // 2,
                hidden_buffer.height() // 2,
            ).alpha()
            == 0
        )

        viewer.applyZoom(3.0)
        viewer.setPan(QPointF(25.0, 15.0))
        qapp.processEvents()

        assert viewer.view().viewport.pan == QPointF(25.0, 15.0)
        navigated_plan = renderer.get_current_render_plan()
        assert navigated_plan is not None
        assert navigated_plan.render_items == ()
        assert navigated_plan.current_pan == QPointF(25.0, 15.0)
    finally:
        browser.deleteLater()
        viewer.deleteLater()
        qapp.processEvents()


def test_browser_selection_and_hover_use_transient_content_effects(qapp) -> None:
    """The polished browser lesson highlights layers without editor mutations."""
    viewer = CuteCanvas(features=())
    document = viewer.editor.compositions.create(QRectF(0.0, 0.0, 80.0, 60.0))
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


def test_mask_pixels_never_change_during_browser_layer_selection(qapp) -> None:
    """Layer-browser emphasis must remain outside translucent mask content."""
    probe = MountedQPaneHarness(qapp)
    browser = CompositionBrowser(
        probe.viewer,
        on_focus_requested=lambda _focus: None,
    )
    try:
        mask_id = probe.mask_ids[0]
        service = probe.viewer.mask_service
        assert service is not None
        mask_layer = service.assets.get_layer(mask_id)
        assert mask_layer is not None

        def fill_center(pixels: np.ndarray, _image: QImage) -> None:
            """Fill a broad mask interior away from its visible boundary."""
            pixels[100:300, 100:300] = 255

        mask_layer.coverage.raster.mutate(fill_center)
        service.invalidateMaskCache(mask_id)
        service.controller.mask_updated.emit(None, QRect())
        probe.viewer.setControlMode(probe.viewer.CONTROL_MODE_PANZOOM)
        probe.drain_events(wait_ms=20)

        scene = probe.viewer.currentScene()
        assert scene is not None
        rendered_mask = next(
            layer for layer in scene.layers if layer.source_id == mask_id
        )
        background = next(
            layer for layer in scene.layers if layer.layer_id != rendered_mask.layer_id
        )
        assert probe.viewer.setSelectedLayer(scene.scene_id, background.layer_id)
        probe.drain_events(wait_ms=20)
        sample = QPoint(200, 200)
        expected = probe.capture().pixelColor(sample)

        with probe.observe_presented_frames() as frames:
            for _ in range(8):
                assert probe.viewer.setSelectedLayer(
                    scene.scene_id,
                    rendered_mask.layer_id,
                )
                probe.drain_events()
                assert probe.viewer.setSelectedLayer(
                    scene.scene_id,
                    background.layer_id,
                )
                probe.drain_events()

        assert frames.frames
        assert all(frame.color_at(sample) == expected for frame in frames.frames)
        assert probe.capture().pixelColor(sample) == expected
    finally:
        browser.close()
        browser.deleteLater()
        probe.close()


def test_demo_composition_creation_placement_and_policy_are_intentional(qapp) -> None:
    """The compact browser should expose complete composition-first workflows."""
    window = ExampleWindow(ExampleOptions())
    try:
        seeded_id = window.qpane.createCompositionFromImage(
            _image("blue"),
            title="Blue",
            label="Background",
        )
        dock = window.composition_ui.dock
        assert dock is not None

        dock._create_composition()
        empty_id = window.qpane.currentCompositionID()
        empty_scene = window.qpane.currentScene()
        assert empty_id is not None and empty_scene is not None
        assert empty_scene.layers == ()

        placed_id = window.qpane.placeComposition(seeded_id)
        placed_scene = window.qpane.currentScene()
        assert (
            placed_id is not None
            and placed_scene is not None
            and len(placed_scene.layers) == 1
        )
        placed = placed_scene.layers[0]
        assert placed.source_id == seeded_id
        assert placed.interaction.selectable
        assert placed.interaction.movable
        assert placed.interaction.removable

        window.qpane.openComposition(seeded_id)
        seeded_scene = window.qpane.currentScene()
        assert seeded_id is not None and seeded_id != empty_id
        assert seeded_scene is not None and len(seeded_scene.layers) == 1
        assert seeded_scene.layers[0].layer_id != placed.layer_id
        assert window.qpane.setSelectedLayer(
            seeded_scene.scene_id,
            seeded_scene.layers[0].layer_id,
        )
        window.tools.editor_controls.layer_policy.reconcile()
        seeded_layer = window.qpane.currentScene().layers[0]
        assert seeded_layer.interaction.movable
        assert not seeded_layer.interaction.pixel_editable

        dock.compositionPropertiesRequested.emit(seeded_id)
        qapp.processEvents()
        dialog = window.composition_ui._composition_properties_dialog
        assert dialog is not None and dialog.isVisible() and dialog.isModal()
        dialog.removable.setChecked(False)
        dialog._save()
        entry = window.qpane.getCompositionSnapshot().compositions[seeded_id]
        assert not entry.policy.removable
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_browser_drag_reorders_one_stack_and_history_restores_it(qapp) -> None:
    """A visible tree drag must use the public chronological stack mutation."""
    viewer = CuteCanvas(features=())
    composition_id = viewer.createComposition(
        QRectF(0.0, 0.0, 40.0, 20.0),
        title="Reorder",
    )
    bottom_id = viewer.addEditableRasterLayer(
        _image("red"),
        placement=QRectF(0.0, 0.0, 20.0, 20.0),
        label="Bottom",
    )
    top_id = viewer.addEditableRasterLayer(
        _image("blue"),
        placement=QRectF(20.0, 0.0, 20.0, 20.0),
        label="Top",
    )
    assert bottom_id is not None and top_id is not None
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
    window = ExampleWindow(ExampleOptions())
    try:
        first_composition = window.qpane.createCompositionFromImage(
            _image("red"),
            title="Red",
            label="Background",
        )
        second_composition = window.qpane.createCompositionFromImage(
            _image("blue"),
            title="Blue",
            label="Background",
        )
        window.qpane.openComposition(first_composition)
        assert window.composition_ui.dock is not None
        browser = window.composition_ui.dock._browser
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
    window = ExampleWindow(ExampleOptions())
    try:
        first_id = window.qpane.createCompositionFromImage(
            _image("red", QSize(2048, 1536)),
            title="Red",
            label="Background",
        )
        second_id = window.qpane.createCompositionFromImage(
            _image("blue", QSize(2048, 1536)),
            title="Blue",
            label="Background",
        )
        composition_ids = (first_id, second_id)
        assert window.composition_ui.dock is not None
        browser = window.composition_ui.dock._browser
        window.show()
        window.composition_ui.dock.show()
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
