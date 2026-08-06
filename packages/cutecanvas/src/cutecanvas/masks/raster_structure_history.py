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
"""Undo explicit mask raster-structure edits as complete asset transitions."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from cutecanvas.coverage.raster_structure import CoverageRasterStructureState

from .mask_undo import MaskUndoSnippet


@dataclass(slots=True)
class MaskRasterStructureCommand:
    """Swap authored extent and raster storage as one undoable mask edit."""

    mask_id: uuid.UUID
    before: CoverageRasterStructureState
    after: CoverageRasterStructureState
    apply: Callable[[uuid.UUID, CoverageRasterStructureState], None]
    notify: Callable[[uuid.UUID], None] | None = None
    description: str = "mask-raster-structure-change"

    def undo(self) -> None:
        """Restore the earlier authored raster structure."""
        self.apply(self.mask_id, self.before)
        if self.notify is not None:
            self.notify(self.mask_id)

    def redo(self) -> None:
        """Restore the later authored raster structure."""
        self.apply(self.mask_id, self.after)
        if self.notify is not None:
            self.notify(self.mask_id)

    def describe_delta(self, *, use_after: bool) -> Iterable[MaskUndoSnippet] | None:
        """Require full invalidation because authored geometry may change."""
        return None
