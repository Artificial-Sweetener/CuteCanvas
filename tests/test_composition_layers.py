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

from qpane.composition.history import LayerPlacementHistory
from qpane.composition.layers import (
    CompositionLayerInstance,
    CompositionLayerSourceKind,
    ImageSceneLayerStore,
)
from qpane.scene.model import (
    LayerInteractionPolicy,
    LayerPlacement,
    LayerPlacementChange,
)
from qpane.scene.raster import LayerTransform, RasterBounds

_PLACEMENT = LayerPlacement(0.0, 0.0, 100.0, 80.0)


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
    store.ensure_image(image_id, _PLACEMENT)
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
    store.ensure_image(first_image, _PLACEMENT)
    store.ensure_image(second_image, _PLACEMENT)
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
    store.ensure_image(image_id, _PLACEMENT)
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


def test_layer_instances_default_to_locked_scene_interaction():
    """Existing composition layers should not opt into scene selection implicitly."""
    store = ImageSceneLayerStore()
    image_id = uuid.uuid4()
    store.ensure_image(image_id, _PLACEMENT)
    mask = _mask_instance(uuid.uuid4())
    assert store.add_layer(image_id, mask)

    base, stored_mask = store.layers_for_image(image_id)
    assert base.interaction.selectable is False
    assert base.interaction.movable is False
    assert stored_mask.interaction.selectable is False
    assert stored_mask.interaction.movable is False


def test_layer_store_replaces_policy_and_transform_as_instance_state():
    """Policy and transform updates should replace only the targeted instance."""
    store = ImageSceneLayerStore()
    image_id = uuid.uuid4()
    store.ensure_image(image_id, _PLACEMENT)
    mask = _mask_instance(uuid.uuid4())
    assert store.add_layer(image_id, mask)
    interaction = LayerInteractionPolicy(selectable=True, movable=True)
    moved = LayerPlacement(12.0, 8.0, 100.0, 80.0)

    assert store.update_interaction(image_id, mask.layer_id, interaction)
    transform = LayerTransform.from_placement(RasterBounds(0, 0, 100, 80), moved)
    assert store.update_transform(image_id, mask.layer_id, transform)

    updated = store.layer(image_id, mask.layer_id)
    assert updated is not None
    assert updated.interaction == interaction
    assert updated.transform == transform
    assert mask.interaction == LayerInteractionPolicy()
    assert mask.transform == LayerTransform()


def test_placement_history_is_scoped_to_each_scene():
    """Undo and redo branches should advance independently per scene."""
    history = LayerPlacementHistory()
    first_scene_id = uuid.uuid4()
    second_scene_id = uuid.uuid4()
    first_change = LayerPlacementChange(
        scene_id=first_scene_id,
        layer_id=uuid.uuid4(),
        before=_PLACEMENT,
        after=LayerPlacement(10.0, 0.0, 100.0, 80.0),
    )
    second_change = LayerPlacementChange(
        scene_id=second_scene_id,
        layer_id=uuid.uuid4(),
        before=_PLACEMENT,
        after=LayerPlacement(0.0, 10.0, 100.0, 80.0),
    )

    assert history.record(first_change)
    assert history.record(second_change)
    assert history.commit_undo(first_change)

    assert history.undo_candidate(first_scene_id) is None
    assert history.redo_candidate(first_scene_id) == first_change
    assert history.undo_candidate(second_scene_id) == second_change
    assert history.redo_candidate(second_scene_id) is None
