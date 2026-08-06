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
"""Reserve stable sampled support for transient edits on empty hybrid layers."""

from __future__ import annotations

import math
import uuid

from ..scene.raster import RasterBounds

_SUPPORT_BLOCK_SPAN = 64
_FILTER_BLEED = 1


class TransientHybridSupport:
    """Own one stable, bounded support envelope for the active edit burst."""

    def __init__(self) -> None:
        """Create an inactive support reservation."""
        self._scene_id: uuid.UUID | None = None
        self._layer_id: uuid.UUID | None = None
        self._bounds: RasterBounds | None = None

    def resolve(
        self,
        target: tuple[uuid.UUID, uuid.UUID, RasterBounds] | None,
        active_scene_id: uuid.UUID,
    ) -> dict[uuid.UUID, RasterBounds]:
        """Return stable support bounds for a target in the active scene."""
        if target is None or target[0] != active_scene_id:
            self.clear()
            return {}
        scene_id, layer_id, requested = target
        if scene_id != self._scene_id or layer_id != self._layer_id:
            self._scene_id = scene_id
            self._layer_id = layer_id
            self._bounds = None
        bounds = self._bounds
        if bounds is None or not bounds.contains(requested):
            reservation = _reserved_bounds(requested)
            self._bounds = reservation if bounds is None else bounds.united(reservation)
        resolved = self._bounds
        if resolved is None:
            raise RuntimeError("active transient support must have reserved bounds")
        return {layer_id: resolved}

    def clear(self) -> None:
        """Release support geometry when no transient edit is active."""
        self._scene_id = None
        self._layer_id = None
        self._bounds = None


def _reserved_bounds(bounds: RasterBounds) -> RasterBounds:
    """Align bounds plus filter bleed to stable allocation blocks."""
    left = math.floor((bounds.x - _FILTER_BLEED) / _SUPPORT_BLOCK_SPAN)
    top = math.floor((bounds.y - _FILTER_BLEED) / _SUPPORT_BLOCK_SPAN)
    right = math.ceil((bounds.right + _FILTER_BLEED) / _SUPPORT_BLOCK_SPAN)
    bottom = math.ceil((bounds.bottom + _FILTER_BLEED) / _SUPPORT_BLOCK_SPAN)
    return RasterBounds(
        left * _SUPPORT_BLOCK_SPAN,
        top * _SUPPORT_BLOCK_SPAN,
        max(1, (right - left) * _SUPPORT_BLOCK_SPAN),
        max(1, (bottom - top) * _SUPPORT_BLOCK_SPAN),
    )


__all__ = ["TransientHybridSupport"]
