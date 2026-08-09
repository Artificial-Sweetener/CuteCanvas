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

"""History values for atomic scene-layer mapping edits."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from qpane.sdk.scene import (
    BilinearLayerTransform,
    LayerMapping,
    PiecewiseLayerTransform,
    ProjectiveLayerTransform,
)

from ..composition.layers import CompositionLayerStore


@dataclass(frozen=True, slots=True)
class LayerMappingTransition:
    """Capture one layer's exact mapping transition."""

    layer_id: uuid.UUID
    before: LayerMapping
    after: LayerMapping


@dataclass(frozen=True, slots=True)
class LayerMappingEdit:
    """Capture one atomic set of scene-layer mapping transitions."""

    scene_id: uuid.UUID
    transitions: tuple[LayerMappingTransition, ...]

    def __post_init__(self) -> None:
        """Require a non-empty set of unique layer transitions."""
        if not self.transitions:
            raise ValueError("mapping edits require at least one transition")
        layer_ids = {transition.layer_id for transition in self.transitions}
        if len(layer_ids) != len(self.transitions):
            raise ValueError("mapping edit layer identities must be unique")

    @property
    def scope_id(self) -> uuid.UUID:
        """Return the scene identity owning this edit."""
        return self.scene_id

    @property
    def retained_bytes(self) -> int:
        """Return the fixed value-storage cost used for history budgeting."""
        return 32 + sum(
            max(_mapping_bytes(transition.before), _mapping_bytes(transition.after))
            for transition in self.transitions
        )


class LayerMappingHistoryOwner:
    """Replay mapping edits through the durable layer-instance store."""

    def __init__(self, layers: CompositionLayerStore) -> None:
        """Bind the document-owned layer store."""
        self._layers = layers

    def undo(self, command: object) -> bool:
        """Restore one mapping edit's previous value."""
        return self._apply(command, use_after=False)

    def redo(self, command: object) -> bool:
        """Restore one mapping edit's subsequent value."""
        return self._apply(command, use_after=True)

    def _apply(self, command: object, *, use_after: bool) -> bool:
        """Apply one validated history value without recording another command."""
        if not isinstance(command, LayerMappingEdit):
            return False
        return self._layers.update_mappings(
            command.scene_id,
            tuple(
                (
                    transition.layer_id,
                    transition.after if use_after else transition.before,
                )
                for transition in command.transitions
            ),
        )


def _mapping_bytes(mapping: LayerMapping) -> int:
    """Return deterministic retained geometry storage for one immutable mapping."""
    if isinstance(mapping, (PiecewiseLayerTransform, BilinearLayerTransform)):
        return 64 + 32 * (len(mapping.source_boundary) + len(mapping.target_boundary))
    return 88 if isinstance(mapping, ProjectiveLayerTransform) else 64


__all__ = [
    "LayerMappingEdit",
    "LayerMappingHistoryOwner",
    "LayerMappingTransition",
]
