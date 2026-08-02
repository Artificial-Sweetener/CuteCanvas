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

"""Composition-owned layer instances and their ordered document stacks."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace

from PySide6.QtGui import QColor
from qpane.sdk.scene import (
    LayerClip,
    LayerEffectReference,
    LayerInteractionPolicy,
    LayerSourceReference,
    LayerTransform,
)

from .geometry_policy import LayerGeometryPolicy
from .resource_lifetime import CompositionResourceLifetime, ResourceLeaseKind


@dataclass(frozen=True, slots=True)
class CompositionLayerInstance:
    """Store one reusable source's presentation inside an image scene."""

    layer_id: uuid.UUID
    source: LayerSourceReference
    transform: LayerTransform = field(default_factory=LayerTransform)
    visible: bool = True
    opacity: float = 1.0
    tint: QColor | None = None
    hit_test: bool = True
    interaction: LayerInteractionPolicy = field(default_factory=LayerInteractionPolicy)
    role: str = "content"
    label: str | None = None
    clip: LayerClip | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)
    effects: tuple[LayerEffectReference, ...] = ()
    geometry: LayerGeometryPolicy = field(default_factory=LayerGeometryPolicy)

    def __post_init__(self) -> None:
        """Validate presentation and detach mutable color state."""
        if not 0.0 <= self.opacity <= 1.0:
            raise ValueError("layer opacity must be between 0.0 and 1.0")
        if not isinstance(self.source, LayerSourceReference):
            raise TypeError("layer source must satisfy LayerSourceReference")
        if self.tint is not None:
            object.__setattr__(self, "tint", QColor(self.tint))
        object.__setattr__(self, "metadata", dict(self.metadata))
        effects = tuple(self.effects)
        if not all(isinstance(effect, LayerEffectReference) for effect in effects):
            raise TypeError("layer effects must satisfy LayerEffectReference")
        object.__setattr__(self, "effects", effects)


class CompositionLayerStore:
    """Own ordered layer instances for every stored composition."""

    def __init__(
        self,
        lifetime: CompositionResourceLifetime,
        changed: Callable[[uuid.UUID], None] | None = None,
        validate_stack: (
            Callable[[uuid.UUID, tuple[CompositionLayerInstance, ...]], None] | None
        ) = None,
    ) -> None:
        """Initialize empty stacks backed by the shared resource lifetime owner."""
        self._lifetime = lifetime
        self._changed = changed
        self._validate_stack = validate_stack
        self._layers_by_composition: dict[uuid.UUID, list[CompositionLayerInstance]] = (
            {}
        )
        self._instances_by_source: dict[
            tuple[str, uuid.UUID],
            set[tuple[uuid.UUID, uuid.UUID]],
        ] = {}
        self._instance_revisions: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
        self._revision = 0

    @property
    def revision(self) -> int:
        """Return the revision of ordered layer-instance state."""
        return self._revision

    def ensure_composition(
        self,
        composition_id: uuid.UUID,
        initial_layers: tuple[CompositionLayerInstance, ...],
    ) -> None:
        """Ensure a composition begins with a validated initial layer stack."""
        if composition_id in self._layers_by_composition:
            return
        if len({layer.layer_id for layer in initial_layers}) != len(initial_layers):
            raise ValueError("composition layer IDs must be unique")
        self._validate(composition_id, initial_layers)
        self._layers_by_composition[composition_id] = list(initial_layers)
        for instance in initial_layers:
            self._index_instance(composition_id, instance)
        self._revision += 1
        self._publish_changed(composition_id)

    def remove_composition(
        self, composition_id: uuid.UUID
    ) -> tuple[CompositionLayerInstance, ...]:
        """Remove a composition stack and return its former layer instances."""
        removed = tuple(self._layers_by_composition.pop(composition_id, ()))
        if not removed:
            return ()
        for instance in removed:
            self._unindex_instance(composition_id, instance)
        self._revision += 1
        self._publish_changed(composition_id)
        return removed

    def replace_layers(
        self,
        composition_id: uuid.UUID,
        instances: tuple[CompositionLayerInstance, ...],
    ) -> bool:
        """Replace one composition's complete validated ordered layer stack."""
        if len({instance.layer_id for instance in instances}) != len(instances):
            raise ValueError("composition layer IDs must be unique")
        previous = self._layers_by_composition.get(composition_id, [])
        if tuple(previous) == instances:
            return False
        self._validate(composition_id, instances)
        for instance in instances:
            for source in instance_resources(instance):
                self._lifetime.acquire(source, ResourceLeaseKind.SESSION)
        for instance in previous:
            self._unindex_instance(composition_id, instance)
        self._layers_by_composition[composition_id] = list(instances)
        for instance in instances:
            self._index_instance(composition_id, instance)
        for instance in instances:
            for source in instance_resources(instance):
                self._lifetime.release(source, ResourceLeaseKind.SESSION)
        self._revision += 1
        self._publish_changed(composition_id)
        return True

    def clear(self) -> None:
        """Remove every image scene layer stack."""
        if not self._layers_by_composition:
            return
        for composition_id in tuple(self._layers_by_composition):
            self.remove_composition(composition_id)
        self._revision += 1

    def layers_for_composition(
        self, composition_id: uuid.UUID
    ) -> tuple[CompositionLayerInstance, ...]:
        """Return an immutable ordered snapshot for one composition."""
        return tuple(self._layers_by_composition.get(composition_id, ()))

    def layer(
        self, composition_id: uuid.UUID, layer_id: uuid.UUID
    ) -> CompositionLayerInstance | None:
        """Return one layer instance from a composition."""
        return next(
            (
                instance
                for instance in self._layers_by_composition.get(composition_id, ())
                if instance.layer_id == layer_id
            ),
            None,
        )

    def layer_for_source(
        self,
        composition_id: uuid.UUID,
        source: LayerSourceReference,
    ) -> CompositionLayerInstance | None:
        """Return the first composition instance for one source."""
        return next(
            (
                instance
                for instance in self._layers_by_composition.get(composition_id, ())
                if instance.source == source
            ),
            None,
        )

    def composition_ids_for_source(
        self,
        source: LayerSourceReference,
    ) -> tuple[uuid.UUID, ...]:
        """Return compositions containing one or more instances of a source."""
        return tuple(
            sorted(
                {
                    composition_id
                    for composition_id, _layer_id in self._instances_by_source.get(
                        _source_key(source), ()
                    )
                },
                key=str,
            )
        )

    def instance_revision(self, composition_id: uuid.UUID, layer_id: uuid.UUID) -> int:
        """Return the presentation revision for one layer instance."""
        return self._instance_revisions.get((composition_id, layer_id), 0)

    def add_layer(
        self, composition_id: uuid.UUID, instance: CompositionLayerInstance
    ) -> bool:
        """Append a layer instance to an existing image scene."""
        if composition_id not in self._layers_by_composition:
            return False
        layers = self._layers_by_composition[composition_id]
        if any(candidate.layer_id == instance.layer_id for candidate in layers):
            return False
        self._validate(composition_id, (*layers, instance))
        layers.append(instance)
        self._index_instance(composition_id, instance)
        self._revision += 1
        self._publish_changed(composition_id)
        return True

    def restore_layer(
        self,
        composition_id: uuid.UUID,
        layer_id: uuid.UUID,
        instance: CompositionLayerInstance | None,
        *,
        index: int,
    ) -> bool:
        """Atomically restore, replace, or remove one layer instance."""
        layers = self._layers_by_composition.get(composition_id)
        if layers is None:
            return False
        current_index = next(
            (
                position
                for position, candidate in enumerate(layers)
                if candidate.layer_id == layer_id
            ),
            None,
        )
        current = None if current_index is None else layers[current_index]
        if instance is not None and instance.layer_id != layer_id:
            raise ValueError("restored layer identity must match layer_id")
        if current == instance and (
            instance is None or current_index == min(max(0, index), len(layers) - 1)
        ):
            return False
        candidate = list(layers)
        if current_index is not None:
            candidate.pop(current_index)
        if instance is not None:
            insertion_index = min(max(0, int(index)), len(candidate))
            candidate.insert(insertion_index, instance)
        self._validate(composition_id, tuple(candidate))
        if instance is not None:
            for source in instance_resources(instance):
                self._lifetime.acquire(source, ResourceLeaseKind.SESSION)
        try:
            if current is not None and current_index is not None:
                layers.pop(current_index)
                self._unindex_instance(composition_id, current)
            if instance is not None:
                insertion_index = min(max(0, int(index)), len(layers))
                layers.insert(insertion_index, instance)
                self._index_instance(composition_id, instance)
        finally:
            if instance is not None:
                for source in instance_resources(instance):
                    self._lifetime.release(source, ResourceLeaseKind.SESSION)
        self._revision += 1
        self._publish_changed(composition_id)
        return True

    def duplicate_layer(
        self,
        composition_id: uuid.UUID,
        layer_id: uuid.UUID,
        duplicate_layer_id: uuid.UUID,
        *,
        transform: LayerTransform | None = None,
    ) -> CompositionLayerInstance | None:
        """Append an independent instance sharing one existing source."""
        if self.layer(composition_id, duplicate_layer_id) is not None:
            return None
        original = self.layer(composition_id, layer_id)
        if original is None:
            return None
        duplicate = replace(
            original,
            layer_id=duplicate_layer_id,
            transform=original.transform if transform is None else transform,
        )
        return duplicate if self.add_layer(composition_id, duplicate) else None

    def remove_layer(self, composition_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Remove one layer instance from a composition."""
        layers = self._layers_by_composition.get(composition_id)
        if not layers:
            return False
        instance = next(
            (candidate for candidate in layers if candidate.layer_id == layer_id), None
        )
        if instance is None:
            return False
        self._validate(
            composition_id,
            tuple(candidate for candidate in layers if candidate is not instance),
        )
        layers.remove(instance)
        self._unindex_instance(composition_id, instance)
        self._revision += 1
        self._publish_changed(composition_id)
        return True

    def reorder_layer(
        self, composition_id: uuid.UUID, layer_id: uuid.UUID, target_index: int
    ) -> bool:
        """Move a layer to an exact cross-kind z-order index."""
        layers = self._layers_by_composition.get(composition_id)
        if not layers or target_index < 0 or target_index >= len(layers):
            return False
        current_index = next(
            (
                index
                for index, instance in enumerate(layers)
                if instance.layer_id == layer_id
            ),
            None,
        )
        if current_index is None or current_index == target_index:
            return False
        instance = layers.pop(current_index)
        layers.insert(target_index, instance)
        self._revision += 1
        self._publish_changed(composition_id)
        return True

    def update_presentation(
        self,
        composition_id: uuid.UUID,
        layer_id: uuid.UUID,
        *,
        opacity: float | None = None,
        tint: QColor | None = None,
    ) -> bool:
        """Replace presentation values for one layer instance."""
        layers = self._layers_by_composition.get(composition_id)
        if not layers:
            return False
        index = next(
            (
                position
                for position, instance in enumerate(layers)
                if instance.layer_id == layer_id
            ),
            None,
        )
        if index is None:
            return False
        current = layers[index]
        replacement = replace(
            current,
            opacity=current.opacity if opacity is None else opacity,
            tint=current.tint if tint is None else QColor(tint),
        )
        if replacement == current:
            return False
        layers[index] = replacement
        self._advance_instance_revision(composition_id, layer_id)
        self._revision += 1
        self._publish_changed(composition_id)
        return True

    def update_interaction(
        self,
        composition_id: uuid.UUID,
        layer_id: uuid.UUID,
        interaction: LayerInteractionPolicy,
    ) -> bool:
        """Replace direct-interaction permissions for one layer instance."""
        return self._replace_layer(
            composition_id,
            layer_id,
            lambda current: replace(current, interaction=interaction),
        )

    def update_transform(
        self,
        composition_id: uuid.UUID,
        layer_id: uuid.UUID,
        transform: LayerTransform,
    ) -> bool:
        """Replace authoritative layer-to-scene transform for one instance."""
        return self._replace_layer(
            composition_id,
            layer_id,
            lambda current: replace(current, transform=transform),
        )

    def update_transforms(
        self,
        composition_id: uuid.UUID,
        transforms: tuple[tuple[uuid.UUID, LayerTransform], ...],
    ) -> bool:
        """Replace multiple instance transforms as one validated publication."""
        layers = self._layers_by_composition.get(composition_id)
        if not layers or not transforms:
            return False
        requested = dict(transforms)
        if len(requested) != len(transforms):
            raise ValueError("layer transform identities must be unique")
        known_ids = {layer.layer_id for layer in layers}
        if not requested.keys() <= known_ids:
            return False
        candidate = [
            (
                replace(layer, transform=requested[layer.layer_id])
                if layer.layer_id in requested
                else layer
            )
            for layer in layers
        ]
        changed_ids = tuple(
            current.layer_id
            for current, replacement in zip(layers, candidate, strict=True)
            if current != replacement
        )
        if not changed_ids:
            return False
        self._validate(composition_id, tuple(candidate))
        layers[:] = candidate
        for layer_id in changed_ids:
            self._advance_instance_revision(composition_id, layer_id)
        self._revision += 1
        self._publish_changed(composition_id)
        return True

    def update_label(
        self,
        composition_id: uuid.UUID,
        layer_id: uuid.UUID,
        label: str | None,
    ) -> bool:
        """Replace composition-owned display metadata for one instance."""
        layers = self._layers_by_composition.get(composition_id)
        if not layers:
            return False
        index = next(
            (
                position
                for position, instance in enumerate(layers)
                if instance.layer_id == layer_id
            ),
            None,
        )
        if index is None:
            return False
        normalized = label.strip() if isinstance(label, str) else None
        normalized = normalized or None
        replacement = replace(layers[index], label=normalized)
        if replacement == layers[index]:
            return False
        layers[index] = replacement
        self._advance_instance_revision(composition_id, layer_id)
        self._revision += 1
        self._publish_changed(composition_id)
        return True

    def _replace_layer(
        self,
        composition_id: uuid.UUID,
        layer_id: uuid.UUID,
        replacement_factory: Callable[
            [CompositionLayerInstance], CompositionLayerInstance
        ],
    ) -> bool:
        """Replace one immutable layer instance through ``replacement_factory``."""
        layers = self._layers_by_composition.get(composition_id)
        if not layers:
            return False
        index = next(
            (
                position
                for position, instance in enumerate(layers)
                if instance.layer_id == layer_id
            ),
            None,
        )
        if index is None:
            return False
        replacement = replacement_factory(layers[index])
        if replacement == layers[index]:
            return False
        candidate = list(layers)
        candidate[index] = replacement
        self._validate(composition_id, tuple(candidate))
        layers[index] = replacement
        self._advance_instance_revision(composition_id, layer_id)
        self._revision += 1
        self._publish_changed(composition_id)
        return True

    def _publish_changed(self, composition_id: uuid.UUID) -> None:
        """Publish one coherent composition-stack mutation."""
        if self._changed is not None:
            self._changed(composition_id)

    def _validate(
        self,
        composition_id: uuid.UUID,
        layers: tuple[CompositionLayerInstance, ...],
    ) -> None:
        """Validate a complete candidate stack before mutating owned state."""
        if self._validate_stack is not None:
            self._validate_stack(composition_id, layers)

    def _index_instance(
        self, composition_id: uuid.UUID, instance: CompositionLayerInstance
    ) -> None:
        """Record one source-to-composition-instance relationship."""
        key = _source_key(instance.source)
        instance_key = (composition_id, instance.layer_id)
        self._instances_by_source.setdefault(key, set()).add(instance_key)
        self._instance_revisions.setdefault(instance_key, 0)
        for source in instance_resources(instance):
            self._lifetime.acquire(source, ResourceLeaseKind.LIVE)

    def _unindex_instance(
        self, composition_id: uuid.UUID, instance: CompositionLayerInstance
    ) -> None:
        """Remove one source-to-composition-instance relationship."""
        key = _source_key(instance.source)
        instance_keys = self._instances_by_source.get(key)
        instance_key = (composition_id, instance.layer_id)
        if instance_keys is not None:
            instance_keys.discard(instance_key)
        self._instance_revisions.pop(instance_key, None)
        if instance_keys is not None and not instance_keys:
            self._instances_by_source.pop(key, None)
        for source in instance_resources(instance):
            self._lifetime.release(source, ResourceLeaseKind.LIVE)

    def _advance_instance_revision(
        self, composition_id: uuid.UUID, layer_id: uuid.UUID
    ) -> None:
        """Advance one layer instance's presentation revision."""
        key = (composition_id, layer_id)
        self._instance_revisions[key] = self._instance_revisions.get(key, 0) + 1


def _source_key(source: LayerSourceReference) -> tuple[str, uuid.UUID]:
    """Return the stable index key for one typed source reference."""
    return source.kind, source.resource_id


def instance_resources(
    instance: CompositionLayerInstance,
) -> tuple[LayerSourceReference, ...]:
    """Return unique main and effect sources retained by one instance."""
    sources = [instance.source]
    for effect in instance.effects:
        sources.extend(effect.retained_sources)
    return tuple(dict.fromkeys(sources))
