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
"""Atomic lifecycle and source transitions for composition layer instances."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

from qpane.sdk.scene import LayerSourceReference

from .edit_controller import CompositionEditController
from .layers import (
    CompositionLayerInstance,
    CompositionLayerStore,
)
from .resource_lifetime import CompositionResourceLifetime, ResourceLeaseKind
from .resource_references import instance_resources


@dataclass(frozen=True, slots=True)
class CompositionLayerTransition:
    """Record one exact layer lifecycle or source-reference transition."""

    scope_id: uuid.UUID
    composition_id: uuid.UUID
    layer_id: uuid.UUID
    before: CompositionLayerInstance | None
    after: CompositionLayerInstance | None
    before_index: int
    after_index: int

    @property
    def retained_bytes(self) -> int:
        """Return bounded structural history overhead."""
        return 512

    @property
    def retained_resources(self) -> tuple[LayerSourceReference, ...]:
        """Retain every source needed by either chronology direction."""
        sources = tuple(
            source
            for instance in (self.before, self.after)
            if instance is not None
            for source in instance_resources(instance)
        )
        return tuple(dict.fromkeys(sources))


@dataclass(frozen=True, slots=True)
class CompositionLayerStackTransition:
    """Record one exact atomic transition of an ordered composition stack."""

    scope_id: uuid.UUID
    composition_id: uuid.UUID
    before: tuple[CompositionLayerInstance, ...]
    after: tuple[CompositionLayerInstance, ...]

    @property
    def retained_bytes(self) -> int:
        """Return bounded structural history overhead for both stack snapshots."""
        return 256 + 256 * (len(self.before) + len(self.after))

    @property
    def retained_resources(self) -> tuple[LayerSourceReference, ...]:
        """Retain all source and effect resources in either chronology direction."""
        return tuple(
            dict.fromkeys(
                source
                for instance in (*self.before, *self.after)
                for source in instance_resources(instance)
            )
        )


class CompositionLayerStackTransitionOwner:
    """Replay atomic ordered-stack transitions through the sole layer owner."""

    def __init__(self, layers: CompositionLayerStore) -> None:
        """Bind the authoritative layer-instance store."""
        self._layers = layers

    def undo(self, command: object) -> bool:
        """Restore the exact prior ordered stack."""
        return self._restore(command, use_after=False)

    def redo(self, command: object) -> bool:
        """Restore the exact resulting ordered stack."""
        return self._restore(command, use_after=True)

    def _restore(self, command: object, *, use_after: bool) -> bool:
        """Restore one validated stack direction."""
        if not isinstance(command, CompositionLayerStackTransition):
            return False
        layers = command.after if use_after else command.before
        return self._layers.replace_layers(command.composition_id, layers)


class CompositionLayerTransitionOwner:
    """Replay exact layer transitions through the composition layer owner."""

    def __init__(self, layers: CompositionLayerStore) -> None:
        """Bind the authoritative layer-instance store."""
        self._layers = layers

    def undo(self, command: object) -> bool:
        """Restore the transition's exact prior instance state."""
        if not isinstance(command, CompositionLayerTransition):
            return False
        return self._layers.restore_layer(
            command.composition_id,
            command.layer_id,
            command.before,
            index=command.before_index,
        )

    def redo(self, command: object) -> bool:
        """Restore the transition's exact resulting instance state."""
        if not isinstance(command, CompositionLayerTransition):
            return False
        return self._layers.restore_layer(
            command.composition_id,
            command.layer_id,
            command.after,
            index=command.after_index,
        )


class CompositionLayerEditService:
    """Apply generic instance lifecycle edits with exact history retention."""

    def __init__(
        self,
        layers: CompositionLayerStore,
        edits: CompositionEditController,
        lifetime: CompositionResourceLifetime,
    ) -> None:
        """Bind the authoritative layer, chronology, and lifetime owners."""
        self._layers = layers
        self._edits = edits
        self._lifetime = lifetime

    def add(
        self,
        composition_id: uuid.UUID,
        instance: CompositionLayerInstance,
        *,
        index: int | None = None,
        history_scope_id: uuid.UUID | None = None,
    ) -> bool:
        """Add one instance as an undoable lifecycle transition."""
        if self._layers.layer(composition_id, instance.layer_id) is not None:
            return False
        target_index = (
            len(self._layers.layers_for_composition(composition_id))
            if index is None
            else int(index)
        )
        return self._apply(
            CompositionLayerTransition(
                scope_id=history_scope_id or composition_id,
                composition_id=composition_id,
                layer_id=instance.layer_id,
                before=None,
                after=instance,
                before_index=target_index,
                after_index=target_index,
            )
        )

    def remove(
        self,
        composition_id: uuid.UUID,
        layer_id: uuid.UUID,
        *,
        history_scope_id: uuid.UUID | None = None,
        respect_layer_policy: bool = True,
    ) -> bool:
        """Remove one instance as an undoable, optionally policy-gated transition."""
        layers = self._layers.layers_for_composition(composition_id)
        before_index = next(
            (index for index, layer in enumerate(layers) if layer.layer_id == layer_id),
            -1,
        )
        if before_index < 0:
            return False
        before = layers[before_index]
        if respect_layer_policy and not before.interaction.removable:
            return False
        return self._apply(
            CompositionLayerTransition(
                scope_id=history_scope_id or composition_id,
                composition_id=composition_id,
                layer_id=layer_id,
                before=before,
                after=None,
                before_index=before_index,
                after_index=before_index,
            )
        )

    def duplicate(
        self,
        composition_id: uuid.UUID,
        layer_id: uuid.UUID,
        duplicate_layer_id: uuid.UUID,
        *,
        history_scope_id: uuid.UUID | None = None,
    ) -> CompositionLayerInstance | None:
        """Create an undoable independent instance sharing one source."""
        original = self._layers.layer(composition_id, layer_id)
        if original is None:
            return None
        duplicate = replace(original, layer_id=duplicate_layer_id)
        return (
            duplicate
            if self.add(
                composition_id,
                duplicate,
                history_scope_id=history_scope_id,
            )
            else None
        )

    def replace_source(
        self,
        composition_id: uuid.UUID,
        layer_id: uuid.UUID,
        source: LayerSourceReference,
        *,
        history_scope_id: uuid.UUID | None = None,
    ) -> bool:
        """Atomically swap one instance source as an undoable transition."""
        layers = self._layers.layers_for_composition(composition_id)
        index = next(
            (index for index, layer in enumerate(layers) if layer.layer_id == layer_id),
            -1,
        )
        if index < 0:
            return False
        before = layers[index]
        after = replace(before, source=source)
        if before == after:
            return False
        return self._apply(
            CompositionLayerTransition(
                scope_id=history_scope_id or composition_id,
                composition_id=composition_id,
                layer_id=layer_id,
                before=before,
                after=after,
                before_index=index,
                after_index=index,
            )
        )

    def replace_instance(
        self,
        composition_id: uuid.UUID,
        replacement: CompositionLayerInstance,
        *,
        history_scope_id: uuid.UUID | None = None,
    ) -> bool:
        """Atomically replace one complete instance as a single history edit."""
        layers = self._layers.layers_for_composition(composition_id)
        index = next(
            (
                index
                for index, layer in enumerate(layers)
                if layer.layer_id == replacement.layer_id
            ),
            -1,
        )
        if index < 0 or layers[index] == replacement:
            return False
        return self._apply(
            CompositionLayerTransition(
                scope_id=history_scope_id or composition_id,
                composition_id=composition_id,
                layer_id=replacement.layer_id,
                before=layers[index],
                after=replacement,
                before_index=index,
                after_index=index,
            )
        )

    def replace_stack(
        self,
        composition_id: uuid.UUID,
        replacements: tuple[CompositionLayerInstance, ...],
        *,
        history_scope_id: uuid.UUID | None = None,
    ) -> bool:
        """Atomically replace an ordered stack as one chronological command."""
        before = self._layers.layers_for_composition(composition_id)
        after = tuple(replacements)
        if after == before:
            return False
        command = CompositionLayerStackTransition(
            history_scope_id or composition_id,
            composition_id,
            before,
            after,
        )
        sources = command.retained_resources
        for source in sources:
            self._lifetime.acquire(source, ResourceLeaseKind.SESSION)
        try:
            if not self._layers.replace_layers(composition_id, after):
                return False
            self._edits.record_applied(command)
            return True
        finally:
            for source in sources:
                self._lifetime.release(source, ResourceLeaseKind.SESSION)

    def _apply(self, command: CompositionLayerTransition) -> bool:
        """Protect both chronology directions while applying and recording."""
        sources = command.retained_resources
        for source in sources:
            self._lifetime.acquire(source, ResourceLeaseKind.SESSION)
        try:
            changed = self._layers.restore_layer(
                command.composition_id,
                command.layer_id,
                command.after,
                index=command.after_index,
            )
            if not changed:
                return False
            self._edits.record_applied(command)
            return True
        finally:
            for source in sources:
                self._lifetime.release(source, ResourceLeaseKind.SESSION)
