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
"""Tests for exact generic composition-layer lifecycle edits."""

from __future__ import annotations

import uuid

from cutecanvas.composition.edit_controller import CompositionEditController
from cutecanvas.composition.edit_history import CompositionEditHistory
from cutecanvas.composition.layer_edits import (
    CompositionLayerEditService,
    CompositionLayerTransition,
    CompositionLayerTransitionOwner,
)
from cutecanvas.composition.layers import (
    CompositionLayerInstance,
    CompositionLayerStore,
)
from cutecanvas.composition.resource_lifetime import CompositionResourceLifetime
from cutecanvas.masks.source_reference import MaskAssetReference
from qpane.catalog.source_reference import CatalogImageReference
from qpane.scene.identity import base_image_layer_id


class _RecordingLifecycleOwner:
    """Record final releases for generic transition assertions."""

    source_type = MaskAssetReference

    def __init__(self) -> None:
        """Initialize an empty release log."""
        self.released: list[MaskAssetReference] = []

    def release_unreachable(self, source) -> None:
        """Record one final source release."""
        assert isinstance(source, MaskAssetReference)
        self.released.append(source)


def _edit_graph():
    """Return composition owners with one base layer and transition routing."""
    lifetime = CompositionResourceLifetime()
    history = CompositionEditHistory(resource_lifetime=lifetime)
    controller = CompositionEditController(history)
    layers = CompositionLayerStore(lifetime)
    transition_owner = CompositionLayerTransitionOwner(layers)
    controller.register_handler(
        CompositionLayerTransition,
        undo=transition_owner.undo,
        redo=transition_owner.redo,
    )
    edits = CompositionLayerEditService(layers, controller, lifetime)
    scope_id = uuid.uuid4()
    image_id = uuid.uuid4()
    layers.ensure_composition(
        scope_id,
        (
            CompositionLayerInstance(
                layer_id=base_image_layer_id(image_id),
                source=CatalogImageReference(image_id),
                role="base-image",
            ),
        ),
    )
    return lifetime, history, controller, layers, edits, scope_id


def test_layer_lifecycle_add_duplicate_remove_replays_exact_order() -> None:
    """Generic lifecycle edits must preserve source sharing and exact stack order."""
    _lifetime, _history, controller, layers, edits, scope_id = _edit_graph()
    source = MaskAssetReference(uuid.uuid4())
    first = CompositionLayerInstance(uuid.uuid4(), source, label="First")

    assert edits.add(scope_id, first)
    duplicate = edits.duplicate(scope_id, first.layer_id, uuid.uuid4())
    assert duplicate is not None
    assert edits.remove(scope_id, first.layer_id)
    assert [layer.layer_id for layer in layers.layers_for_composition(scope_id)] == [
        base_image_layer_id(layers.layers_for_composition(scope_id)[0].source.image_id),
        duplicate.layer_id,
    ]

    assert controller.undo(scope_id).changed
    assert [layer.layer_id for layer in layers.layers_for_composition(scope_id)][
        1:
    ] == [
        first.layer_id,
        duplicate.layer_id,
    ]
    assert controller.undo(scope_id).changed
    assert [layer.layer_id for layer in layers.layers_for_composition(scope_id)][
        1:
    ] == [first.layer_id]
    assert controller.redo(scope_id).changed
    assert [layer.layer_id for layer in layers.layers_for_composition(scope_id)][
        1:
    ] == [
        first.layer_id,
        duplicate.layer_id,
    ]


def test_source_swap_retains_outgoing_payload_until_history_is_discarded() -> None:
    """A source must not become unreachable between mutation and history retention."""
    lifetime, history, controller, layers, edits, scope_id = _edit_graph()
    owner = _RecordingLifecycleOwner()
    lifetime.register_owner(owner)
    before_source = MaskAssetReference(uuid.uuid4())
    after_source = MaskAssetReference(uuid.uuid4())
    layer = CompositionLayerInstance(uuid.uuid4(), before_source)
    assert edits.add(scope_id, layer)
    history.clear_scope(scope_id)

    assert edits.replace_source(scope_id, layer.layer_id, after_source)
    assert owner.released == []
    assert layers.layer(scope_id, layer.layer_id).source == after_source

    assert controller.undo(scope_id).changed
    assert layers.layer(scope_id, layer.layer_id).source == before_source
    assert controller.redo(scope_id).changed
    assert layers.layer(scope_id, layer.layer_id).source == after_source

    history.clear_scope(scope_id)
    assert owner.released == [before_source]
