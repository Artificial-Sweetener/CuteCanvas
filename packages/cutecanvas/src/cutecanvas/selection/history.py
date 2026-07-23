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
        """Return detached coverage bytes retained by this command."""
        return _document_bytes(self.before) + _document_bytes(self.after)


def _document_bytes(document: CoverageDocument | None) -> int:
    """Return detached raster storage retained by one authored document."""
    if document is None:
        return 0
    return sum(
        int(item.coverage.pixels.nbytes)
        for item in document.items
        if isinstance(item, RasterCoverageItem)
    )
