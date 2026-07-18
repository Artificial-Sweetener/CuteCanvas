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

"""Tests for composition-owned image scene layer instances."""

import uuid

from PySide6.QtGui import QColor

from qpane.composition.layers import (
    CompositionLayerInstance,
    CompositionLayerSourceKind,
    ImageSceneLayerStore,
)


def _mask_instance(mask_id: uuid.UUID) -> CompositionLayerInstance:
    """Return a representative mask layer instance."""
    return CompositionLayerInstance(
        layer_id=uuid.uuid4(),
        source_kind=CompositionLayerSourceKind.MASK,
        source_id=mask_id,
        opacity=0.5,
        tint=QColor(255, 0, 0),
        role="mask",
    )


def test_layers_reorder_across_source_kinds_and_preserve_instances():
    store = ImageSceneLayerStore()
    image_id = uuid.uuid4()
    first = _mask_instance(uuid.uuid4())
    second = _mask_instance(uuid.uuid4())
    assert store.add_layer(image_id, first)
    assert store.add_layer(image_id, second)
    assert store.reorder_layer(image_id, second.layer_id, 0)
    layers = store.layers_for_image(image_id)
    assert [layer.layer_id for layer in layers] == [
        second.layer_id,
        layers[1].layer_id,
        first.layer_id,
    ]
    assert layers[1].source_kind == CompositionLayerSourceKind.CATALOG_IMAGE


def test_layer_removal_does_not_delete_other_instances_of_source():
    store = ImageSceneLayerStore()
    source_id = uuid.uuid4()
    first_image = uuid.uuid4()
    second_image = uuid.uuid4()
    first = _mask_instance(source_id)
    second = _mask_instance(source_id)
    store.add_layer(first_image, first)
    store.add_layer(second_image, second)
    assert store.remove_layer(first_image, first.layer_id)
    assert store.image_ids_for_source(CompositionLayerSourceKind.MASK, source_id) == (
        second_image,
    )
    assert store.layer(second_image, second.layer_id) == second


def test_presentation_updates_are_value_owned_by_layer_instance():
    store = ImageSceneLayerStore()
    image_id = uuid.uuid4()
    instance = _mask_instance(uuid.uuid4())
    store.add_layer(image_id, instance)
    assert store.update_presentation(
        image_id,
        instance.layer_id,
        opacity=0.25,
        tint=QColor(0, 255, 0),
    )
    updated = store.layer(image_id, instance.layer_id)
    assert updated is not None
    assert updated.opacity == 0.25
    assert updated.tint == QColor(0, 255, 0)
    assert instance.opacity == 0.5
