#    QPane - High-performance PySide6 image viewer
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
    assert not service.layers.store.update_label(image_id, instance.layer_id, "   ")
    info = masks.maskInfo(mask_id)
    assert info is not None
    assert info.label is None
    assert info.opacity == 0.5
    assert image_id in info.image_ids
    assert service.layers.store.update_label(image_id, instance.layer_id, "Layer 1")
    updated = masks.maskInfo(mask_id)
    assert updated is not None
    assert updated.label == "Layer 1"
    assert updated.opacity == 0.5


@pytest.mark.usefixtures("qapp")
def test_mask_ids_and_listing_filter_by_image(qpane_with_mask):
    """Mask listings should only include masks associated with the target image."""
    qpane, manager, image_id = qpane_with_mask
    masks = _masks(qpane)
    service = qpane.mask_service
    other_id = uuid.uuid4()
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
