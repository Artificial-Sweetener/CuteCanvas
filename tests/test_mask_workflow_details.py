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

"""Focused tests for mask workflow metadata and resolution helpers."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from cutecanvas import LayerPolicy
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage

pytest_plugins = ("tests.test_mask_workflows",)


def _masks(qpane):
    masks = qpane._masks_controller
    assert masks is not None
    return masks


@pytest.mark.usefixtures("qapp")
def test_mask_workflow_resolve_image_id_prefers_navigation(qpane_with_mask):
    """Navigation events should provide stable image ids for fallbacks."""
    qpane, _, image_id = qpane_with_mask
    masks = _masks(qpane)
    target_id = uuid.uuid4()
    masks._last_navigation_event = SimpleNamespace(target_id=target_id)
    assert masks._resolve_image_id(None) == target_id
    masks._last_navigation_event = SimpleNamespace(target_id="bad")
    assert masks._resolve_image_id(None) == image_id
    assert masks._resolve_image_id(None, use_fallback=False) is None


@pytest.mark.usefixtures("qapp")
def test_mask_info_normalizes_label_and_reads_layer_opacity(qpane_with_mask):
    """MaskInfo should trim labels and read composition presentation."""
    qpane, manager, image_id = qpane_with_mask
    masks = _masks(qpane)
    service = qpane.mask_service
    mask_id = manager.create_mask(QImage(4, 4, QImage.Format_Grayscale8))
    layer = manager.get_layer(mask_id)
    assert layer is not None
    assert service.layers.attach(
        mask_id, image_id, color=QColor(255, 0, 0), opacity=0.5
    )
    instance = service.layer_instance_for_mask(mask_id)
    assert instance is not None
    composition_id = qpane.currentCompositionID()
    assert composition_id is not None
    assert not service.layers.store.update_label(
        composition_id, instance.layer_id, "   "
    )
    info = masks.maskInfo(mask_id)
    assert info is not None
    assert info.label is None
    assert info.opacity == 0.5
    assert image_id in info.image_ids
    assert info.scene_id is not None
    assert info.layer_id == instance.layer_id
    assert info.interaction == LayerPolicy()
    movable = LayerPolicy(selectable=True, movable=True)
    assert qpane.setLayerInteractionPolicy(
        info.scene_id,
        info.layer_id,
        movable,
    )
    moved_policy = masks.maskInfo(mask_id)
    assert moved_policy is not None
    assert moved_policy.interaction == movable
    assert qpane.setLayerPlacement(
        info.scene_id,
        info.layer_id,
        QRectF(3.0, 2.0, 4.0, 4.0),
    )
    moved_instance = service.layer_instance_for_mask(mask_id)
    assert moved_instance is not None
    assert moved_instance.transform.dx == 3.0
    assert moved_instance.transform.dy == 2.0
    assert qpane.undoSceneEdit()
    restored_instance = service.layer_instance_for_mask(mask_id)
    assert restored_instance is not None
    assert restored_instance.transform.dx == 0.0
    assert restored_instance.transform.dy == 0.0
    assert service.layers.store.update_label(
        composition_id, instance.layer_id, "Layer 1"
    )
    updated = masks.maskInfo(mask_id)
    assert updated is not None
    assert updated.label == "Layer 1"
    assert updated.opacity == 0.5


@pytest.mark.usefixtures("qapp")
def test_moved_mask_uses_layer_transform_for_edit_coordinates(
    qpane_with_mask,
    qapp,
) -> None:
    """Mask editing coordinates should follow its generic scene placement."""
    qpane, manager, image_id = qpane_with_mask
    service = qpane.mask_service
    mask_image = QImage(8, 8, QImage.Format_Grayscale8)
    mask_image.fill(255)
    mask_id = manager.create_mask(mask_image)
    manager.set_mask_image(mask_id, mask_image)
    assert service.layers.attach(mask_id, image_id, color=QColor(255, 0, 0))
    assert service.controller.setActiveMaskID(mask_id)
    info = _masks(qpane).maskInfo(mask_id)
    assert info is not None
    assert qpane.setLayerInteractionPolicy(
        info.scene_id,
        info.layer_id,
        LayerPolicy(selectable=True, movable=True),
    )
    assert qpane.setLayerPlacement(
        info.scene_id,
        info.layer_id,
        QRectF(2.0, 1.0, 8.0, 8.0),
    )
    qpane._is_blank = False
    qpane.show()
    qapp.processEvents()
    plan = qpane.view().calculateRenderPlan(is_blank=False)
    assert plan is not None
    mask_item = next(
        item for item in plan.render_items if item.descriptor.layer_id == info.layer_id
    )
    assert mask_item.descriptor.interaction.selectable
    assert manager.get_layer(mask_id).mask_image.pixelColor(3, 4).red() > 0
    assert not qpane._is_blank
    panel_point = qpane.view().layer_source_to_panel_point(
        info.scene_id,
        info.layer_id,
        QPointF(3.0, 4.0),
    )
    assert panel_point is not None

    coordinates = qpane.activeMaskLayerCoordinates()
    source_point = coordinates.panel_to_source(panel_point)

    assert source_point is not None
    assert source_point.x() == pytest.approx(3.0)
    assert source_point.y() == pytest.approx(4.0)
    assert coordinates.source_to_panel(source_point) == panel_point

    target_panel_point = qpane.view().layer_source_to_panel_point(
        info.scene_id,
        info.layer_id,
        QPointF(5.0, 5.0),
    )
    assert target_panel_point is not None
    selection_hit = qpane.view().scene_selection_hit_test(panel_point)
    assert selection_hit is not None
    assert selection_hit.layer_id == info.layer_id
    movement = qpane.sceneLayerMovementInteraction()
    candidate = movement.candidate_at(panel_point)
    assert candidate is not None
    assert movement.begin(candidate)
    assert movement.update(target_panel_point)
    preview_scene = qpane.view().current_scene_descriptor()
    assert preview_scene is not None
    preview_layer = next(
        item for item in preview_scene.layers if item.layer_id == info.layer_id
    )
    assert preview_layer.transform is not None
    assert preview_layer.transform.dx == pytest.approx(4.0)
    assert preview_layer.transform.dy == pytest.approx(2.0)
    assert movement.finish(target_panel_point)
    moved_instance = service.layer_instance_for_mask(mask_id)
    assert moved_instance is not None
    assert moved_instance.transform.dx == pytest.approx(4.0)
    assert moved_instance.transform.dy == pytest.approx(2.0)


@pytest.mark.usefixtures("qapp")
def test_mask_ids_and_listing_filter_by_image(qpane_with_mask):
    """Mask listings should only include masks associated with the target image."""
    qpane, manager, image_id = qpane_with_mask
    masks = _masks(qpane)
    service = qpane.mask_service
    other_id = uuid.uuid4()
    other_image = QImage(4, 4, QImage.Format_ARGB32_Premultiplied)
    other_image.fill(Qt.transparent)
    qpane.catalog().addImage(other_id, other_image, None)
    first = manager.create_mask(QImage(4, 4, QImage.Format_Grayscale8))
    second = manager.create_mask(QImage(4, 4, QImage.Format_Grayscale8))
    first_layer = manager.get_layer(first)
    second_layer = manager.get_layer(second)
    assert first_layer is not None and second_layer is not None
    assert service.layers.attach(first, image_id, color=QColor(255, 0, 0))
    assert service.layers.attach(second, other_id, color=QColor(255, 0, 0))
    assert masks.maskIDsForImage(image_id) == [first]
    listed = masks.listMasksForImage(image_id)
    assert [info.mask_id for info in listed] == [first]


@pytest.mark.usefixtures("qapp")
def test_feature_availability_toggles_with_delegates(qpane_with_mask):
    """Feature availability should reflect attached delegates."""
    qpane, _, _ = qpane_with_mask
    masks = _masks(qpane)
    assert masks.mask_feature_available() is True
    assert masks.sam_feature_available() is False
    masks._sam_delegate = SimpleNamespace(manager=object())
    assert masks.sam_feature_available() is True
    qpane.mask_service = None
    assert masks.mask_feature_available() is False
