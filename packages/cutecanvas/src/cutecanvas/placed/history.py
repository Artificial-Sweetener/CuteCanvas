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
"""Exact placed-asset provenance edits in composition chronology."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from ..resources import ProjectResourceReference
from .model import PlacedAssetSnapshot
from .store import PlacedAssetStore


@dataclass(frozen=True, slots=True)
class PlacedAssetEdit:
    """Retain one exact provenance/content transition."""

    scope_id: uuid.UUID
    asset_id: uuid.UUID
    before: PlacedAssetSnapshot
    after: PlacedAssetSnapshot

    @property
    def retained_bytes(self) -> int:
        """Return detached pixel memory retained by both states."""
        return _image_bytes(self.before) + _image_bytes(self.after) + 512

    @property
    def retained_resources(self) -> tuple[ProjectResourceReference, ...]:
        """Keep the edited placed source alive while chronology references it."""
        return (ProjectResourceReference(self.asset_id),)


class PlacedAssetEditOwner:
    """Replay placed provenance through its source owner."""

    def __init__(
        self,
        assets: PlacedAssetStore,
        changed: Callable[[uuid.UUID], None],
    ) -> None:
        """Bind source storage and composition publication."""
        self._assets = assets
        self._changed = changed

    def undo(self, command: object) -> bool:
        """Restore the exact previous placed source state."""
        return self._restore(command, use_after=False)

    def redo(self, command: object) -> bool:
        """Restore the exact resulting placed source state."""
        return self._restore(command, use_after=True)

    def _restore(self, command: object, *, use_after: bool) -> bool:
        """Apply one retained state and invalidate every sharing instance."""
        if not isinstance(command, PlacedAssetEdit):
            return False
        self._assets.restore(
            command.asset_id,
            command.after if use_after else command.before,
        )
        self._changed(command.scope_id)
        return True


def _image_bytes(snapshot: PlacedAssetSnapshot) -> int:
    """Estimate detached QImage allocation for history budgeting."""
    return 0 if snapshot.image is None else max(0, snapshot.image.sizeInBytes())
