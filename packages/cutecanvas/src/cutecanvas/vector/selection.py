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
"""Vector object selection authority independent of layer and pixel selection."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VectorObjectSelection:
    """Retain one composition-local ordered object selection."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    object_ids: tuple[uuid.UUID, ...]


class VectorObjectSelectionController:
    """Own stable vector object selection without raster coverage."""

    def __init__(self, changed: Callable[[], None]) -> None:
        """Bind the presentation callback and initialize no selection."""
        self._selection: VectorObjectSelection | None = None
        self._changed = changed

    @property
    def selection(self) -> VectorObjectSelection | None:
        """Return the immutable current selection."""
        return self._selection

    def set(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_ids: tuple[uuid.UUID, ...],
    ) -> bool:
        """Replace selection with stable unique object IDs."""
        unique = tuple(dict.fromkeys(object_ids))
        selection = (
            None if not unique else VectorObjectSelection(scene_id, layer_id, unique)
        )
        if selection == self._selection:
            return False
        self._selection = selection
        self._changed()
        return True

    def clear(self) -> bool:
        """Clear vector object selection."""
        if self._selection is None:
            return False
        self._selection = None
        self._changed()
        return True
