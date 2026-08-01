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
"""Atomic history values for hybrid mask coverage authority."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from cutecanvas.coverage import CoverageDocument, CoverageStateSnapshot
from cutecanvas.coverage.snapshot_equality import coverage_state_snapshots_equal

from .mask_undo import MaskUndoSnippet


@dataclass(frozen=True, slots=True, eq=False)
class MaskCoverageState:
    """Retain sparse raster state and semantic items as one mask revision."""

    raster: CoverageStateSnapshot
    retained: CoverageDocument

    def has_same_content(self, other: MaskCoverageState) -> bool:
        """Return whether another state carries the same live hybrid revision."""
        return (
            self.retained.document_id == other.retained.document_id
            and self.retained.evaluation_token == other.retained.evaluation_token
            and coverage_state_snapshots_equal(self.raster, other.raster)
        )


@dataclass(slots=True)
class MaskCoverageCommand:
    """Swap complete hybrid mask revisions through one chronological command."""

    mask_id: uuid.UUID
    before: MaskCoverageState
    after: MaskCoverageState
    apply: Callable[[uuid.UUID, MaskCoverageState], None]
    notify: Callable[[uuid.UUID], None] | None = None
    description: str = "mask-coverage-change"

    def undo(self) -> None:
        """Restore the previous hybrid revision."""
        self.apply(self.mask_id, self.before)
        if self.notify is not None:
            self.notify(self.mask_id)

    def redo(self) -> None:
        """Restore the subsequent hybrid revision."""
        self.apply(self.mask_id, self.after)
        if self.notify is not None:
            self.notify(self.mask_id)

    def describe_delta(
        self,
        *,
        use_after: bool,
    ) -> Iterable[MaskUndoSnippet] | None:
        """Request full invalidation because retained geometry is tile-evaluated."""
        return None


@dataclass(slots=True)
class MaskRetainedCoverageCommand:
    """Swap retained mask authorship without replaying unchanged raster state."""

    mask_id: uuid.UUID
    before: CoverageDocument
    after: CoverageDocument
    apply: Callable[[uuid.UUID, CoverageDocument], None]
    notify: Callable[[uuid.UUID], None] | None = None
    description: str = "mask-retained-coverage-change"

    def undo(self) -> None:
        """Restore retained authorship before the edit."""
        self.apply(self.mask_id, self.before)
        if self.notify is not None:
            self.notify(self.mask_id)

    def redo(self) -> None:
        """Restore retained authorship after the edit."""
        self.apply(self.mask_id, self.after)
        if self.notify is not None:
            self.notify(self.mask_id)

    def describe_delta(
        self,
        *,
        use_after: bool,
    ) -> Iterable[MaskUndoSnippet] | None:
        """Request invalidation because retained geometry is tile-evaluated."""
        return None
