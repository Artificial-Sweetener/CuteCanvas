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

"""Tests for composition-owned image scene layer instances."""

import uuid

from cutecanvas.composition.layers import (
    CompositionLayerInstance,
    CompositionLayerStore,
)
from cutecanvas.composition.resource_lifetime import CompositionResourceLifetime
from cutecanvas.resources import ProjectResourceReference
from PySide6.QtGui import QColor
from qpane.scene.affine import LayerTransform
from qpane.scene.model import (
    LayerInteractionPolicy,
    LayerPlacement,
)
from qpane.scene.raster import RasterBounds

_PLACEMENT = LayerPlacement(0.0, 0.0, 100.0, 80.0)


class _RecordingMaskLifecycleOwner:
    """Record final mask releases without owning test payloads."""

    source_type = ProjectResourceReference

    def __init__(self) -> None:
        """Initialize an empty release log."""
        self.released: list[ProjectResourceReference] = []

    def release_unreachable(self, source) -> None:
        """Record one unreachable typed mask source."""
        assert isinstance(source, ProjectResourceReference)
        self.released.append(source)


def _mask_instance(mask_id: uuid.UUID) -> CompositionLayerInstance:
    """Return a representative mask layer instance."""
    return CompositionLayerInstance(
        layer_id=uuid.uuid4(),
        source=ProjectResourceReference(mask_id),
        opacity=0.5,
        tint=QColor(255, 0, 0),
        role="mask",
    )


def _ensure_default(store: CompositionLayerStore, image_id: uuid.UUID) -> None:
    """Create one representative generated composition stack."""
    bounds = RasterBounds(0, 0, 100, 80)
    store.ensure_composition(
        image_id,
        (
            CompositionLayerInstance(
                layer_id=uuid.uuid5(image_id, "seed-layer"),
                source=ProjectResourceReference(image_id),
                transform=LayerTransform.from_placement(bounds, _PLACEMENT),
                role="base-image",
            ),
        ),
    )


def test_layers_reorder_across_source_kinds_and_preserve_instances():
    store = CompositionLayerStore(CompositionResourceLifetime())
    image_id = uuid.uuid4()
    _ensure_default(store, image_id)
    first = _mask_instance(uuid.uuid4())
    second = _mask_instance(uuid.uuid4())
    assert store.add_layer(image_id, first)
    assert store.add_layer(image_id, second)
    assert store.reorder_layer(image_id, second.layer_id, 0)
    layers = store.layers_for_composition(image_id)
    assert [layer.layer_id for layer in layers] == [
        second.layer_id,
        layers[1].layer_id,
        first.layer_id,
    ]
    assert layers[1].source == ProjectResourceReference(image_id)


def test_layer_removal_does_not_delete_other_instances_of_source():
    store = CompositionLayerStore(CompositionResourceLifetime())
    source_id = uuid.uuid4()
    first_image = uuid.uuid4()
    second_image = uuid.uuid4()
    _ensure_default(store, first_image)
    _ensure_default(store, second_image)
    first = _mask_instance(source_id)
    second = _mask_instance(source_id)
    store.add_layer(first_image, first)
    store.add_layer(second_image, second)
    assert store.remove_layer(first_image, first.layer_id)
    assert store.composition_ids_for_source(ProjectResourceReference(source_id)) == (
        second_image,
    )
    assert store.layer(second_image, second.layer_id) == second


def test_one_composition_can_place_the_same_source_more_than_once():
    """Shared source identity must not collapse independent layer instances."""
    store = CompositionLayerStore(CompositionResourceLifetime())
    image_id = uuid.uuid4()
    source_id = uuid.uuid4()
    _ensure_default(store, image_id)
    first = _mask_instance(source_id)
    second = _mask_instance(source_id)

    assert store.add_layer(image_id, first)
    assert store.add_layer(image_id, second)
    assert store.layer(image_id, first.layer_id) == first
    assert store.layer(image_id, second.layer_id) == second
    assert store.composition_ids_for_source(ProjectResourceReference(source_id)) == (
        image_id,
    )

    moved = LayerTransform(dx=19.0, dy=7.0)
    assert store.update_transform(image_id, second.layer_id, moved)
    assert store.layer(image_id, first.layer_id).transform == LayerTransform()
    assert store.layer(image_id, second.layer_id).transform == moved


def test_shared_source_releases_only_after_its_last_live_instance() -> None:
    """Removing one of several placements must keep their shared source alive."""
    lifetime = CompositionResourceLifetime()
    owner = _RecordingMaskLifecycleOwner()
    lifetime.register_owner(owner)
    store = CompositionLayerStore(lifetime)
    composition_id = uuid.uuid4()
    source = ProjectResourceReference(uuid.uuid4())
    _ensure_default(store, composition_id)
    first = _mask_instance(source.resource_id)
    second = _mask_instance(source.resource_id)
    assert store.add_layer(composition_id, first)
    assert store.add_layer(composition_id, second)

    assert store.remove_layer(composition_id, first.layer_id)
    assert owner.released == []
    assert store.remove_layer(composition_id, second.layer_id)
    assert owner.released == [source]


def test_presentation_updates_are_value_owned_by_layer_instance():
    store = CompositionLayerStore(CompositionResourceLifetime())
    image_id = uuid.uuid4()
    _ensure_default(store, image_id)
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
    store = CompositionLayerStore(CompositionResourceLifetime())
    image_id = uuid.uuid4()
    _ensure_default(store, image_id)
    mask = _mask_instance(uuid.uuid4())
    assert store.add_layer(image_id, mask)

    base, stored_mask = store.layers_for_composition(image_id)
    assert base.interaction.selectable is False
    assert base.interaction.movable is False
    assert stored_mask.interaction.selectable is False
    assert stored_mask.interaction.movable is False


def test_layer_store_replaces_policy_and_transform_as_instance_state():
    """Policy and transform updates should replace only the targeted instance."""
    store = CompositionLayerStore(CompositionResourceLifetime())
    image_id = uuid.uuid4()
    _ensure_default(store, image_id)
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
