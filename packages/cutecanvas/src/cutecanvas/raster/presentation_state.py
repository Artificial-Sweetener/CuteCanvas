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
"""Transient presentation policy for editable raster transactions."""

from __future__ import annotations

import uuid


class EditableRasterPresentationState:
    """Track sources whose changing pixels must bypass derived products."""

    def __init__(self) -> None:
        """Initialize without any live editable-raster transaction."""
        self._live_sources: set[uuid.UUID] = set()

    def begin(self, raster_id: uuid.UUID) -> None:
        """Mark one source volatile for the duration of a live transaction."""
        self._live_sources.add(raster_id)

    def end(self, raster_id: uuid.UUID) -> None:
        """Return one source to normal revision-aware derived products."""
        self._live_sources.discard(raster_id)

    def is_live(self, raster_id: uuid.UUID) -> bool:
        """Return whether one source currently changes interactively."""
        return raster_id in self._live_sources
