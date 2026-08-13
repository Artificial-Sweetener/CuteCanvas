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
"""Chronological edit values for composition pixel selections."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from cutecanvas.composition.history_model import (
    HistoryDurability,
    HistoryRetainedStorage,
)
from cutecanvas.coverage import CoverageDocument, RasterCoverageItem


@dataclass(frozen=True, slots=True)
class PixelSelectionEdit:
    """Capture one applied pixel-selection transition."""

    scene_id: uuid.UUID
    before: CoverageDocument | None
    after: CoverageDocument | None

    @property
    def scope_id(self) -> uuid.UUID:
        """Return the scene identity owning this edit."""
        return self.scene_id

    @property
    def retained_bytes(self) -> int:
        """Return unique immutable coverage bytes referenced by this command."""
        return sum(item.retained_bytes for item in self.history_retained_storage)

    @property
    def history_durability(self) -> HistoryDurability:
        """Keep selection chronology outside the durable edit budget."""
        return HistoryDurability.TRANSIENT

    @property
    def history_retained_storage(self) -> tuple[HistoryRetainedStorage, ...]:
        """Identify shared immutable arrays across adjacent selection revisions."""
        storage: dict[int, HistoryRetainedStorage] = {}
        for document in (self.before, self.after):
            for item in _raster_items(document):
                pixels = item.coverage.pixels
                storage[id(pixels)] = HistoryRetainedStorage(id(pixels), pixels.nbytes)
        return tuple(storage.values())


def _raster_items(
    document: CoverageDocument | None,
) -> tuple[RasterCoverageItem, ...]:
    """Return raster items whose immutable arrays participate in sharing."""
    if document is None:
        return ()
    return tuple(
        item for item in document.items if isinstance(item, RasterCoverageItem)
    )
