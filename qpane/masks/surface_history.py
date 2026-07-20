#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Undo commands for structural mask-surface transitions."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ..coverage import CoverageStateSnapshot
from .mask_undo import MaskUndoSnippet


@dataclass(slots=True)
class MaskSurfaceCommand:
    """Swap complete raster structure and pixels for undoable reframes."""

    mask_id: uuid.UUID
    before: CoverageStateSnapshot
    after: CoverageStateSnapshot
    apply: Callable[[uuid.UUID, CoverageStateSnapshot], None]
    notify: Callable[[uuid.UUID], None] | None = None
    description: str = "mask-surface-change"

    def undo(self) -> None:
        """Restore the surface state captured before the operation."""
        self.apply(self.mask_id, self.before)
        if self.notify is not None:
            self.notify(self.mask_id)

    def redo(self) -> None:
        """Restore the surface state captured after the operation."""
        self.apply(self.mask_id, self.after)
        if self.notify is not None:
            self.notify(self.mask_id)

    def describe_delta(self, *, use_after: bool) -> Iterable[MaskUndoSnippet] | None:
        """Require full invalidation because storage coordinates may change."""
        return None
