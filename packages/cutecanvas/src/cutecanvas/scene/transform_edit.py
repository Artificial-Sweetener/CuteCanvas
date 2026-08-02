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
"""History values for atomic scene-layer affine transform edits."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from qpane.sdk.scene import LayerTransform

from ..composition.layers import CompositionLayerStore


@dataclass(frozen=True, slots=True)
class LayerTransformTransition:
    """Capture one layer's exact transform transition."""

    layer_id: uuid.UUID
    before: LayerTransform
    after: LayerTransform


@dataclass(frozen=True, slots=True)
class LayerTransformEdit:
    """Capture one atomic set of scene-layer transform transitions."""

    scene_id: uuid.UUID
    transitions: tuple[LayerTransformTransition, ...]

    def __post_init__(self) -> None:
        """Require a non-empty set of unique layer transitions."""
        if not self.transitions:
            raise ValueError("transform edits require at least one transition")
        layer_ids = {transition.layer_id for transition in self.transitions}
        if len(layer_ids) != len(self.transitions):
            raise ValueError("transform edit layer identities must be unique")

    @property
    def scope_id(self) -> uuid.UUID:
        """Return the scene identity owning this edit."""
        return self.scene_id

    @property
    def retained_bytes(self) -> int:
        """Return the fixed value-storage cost used for history budgeting."""
        return 32 + 64 * len(self.transitions)


class LayerTransformHistoryOwner:
    """Replay affine edits directly through the durable layer-instance store."""

    def __init__(self, layers: CompositionLayerStore) -> None:
        """Bind the document-owned layer store."""
        self._layers = layers

    def undo(self, command: object) -> bool:
        """Restore one transform edit's previous value."""
        return self._apply(command, use_after=False)

    def redo(self, command: object) -> bool:
        """Restore one transform edit's subsequent value."""
        return self._apply(command, use_after=True)

    def _apply(self, command: object, *, use_after: bool) -> bool:
        """Apply one validated history value without recording a new command."""
        if not isinstance(command, LayerTransformEdit):
            return False
        return self._layers.update_transforms(
            command.scene_id,
            tuple(
                (
                    transition.layer_id,
                    transition.after if use_after else transition.before,
                )
                for transition in command.transitions
            ),
        )
