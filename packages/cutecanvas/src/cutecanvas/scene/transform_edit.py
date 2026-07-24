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
"""History value for one durable scene-layer affine transform edit."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from qpane.sdk.scene import LayerTransform

from ..composition.layers import CompositionLayerStore


@dataclass(frozen=True, slots=True)
class LayerTransformEdit:
    """Capture one exact applied scene-layer transform transition."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    before: LayerTransform
    after: LayerTransform

    @property
    def scope_id(self) -> uuid.UUID:
        """Return the scene identity owning this edit."""
        return self.scene_id

    @property
    def retained_bytes(self) -> int:
        """Return the fixed value-storage cost used for history budgeting."""
        return 96


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
        return self._layers.update_transform(
            command.scene_id,
            command.layer_id,
            command.after if use_after else command.before,
        )
