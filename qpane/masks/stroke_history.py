#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Per-stroke history capture for pixel patches and structural growth."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .mask_undo import MaskPatch
from .surface import MaskSurfaceSnapshot


@dataclass(frozen=True, slots=True)
class MaskStrokeHistoryPayload:
    """Capture one completed stroke's patch or structural history data."""

    patches: tuple[MaskPatch, ...]
    already_applied: bool
    structural_before: MaskSurfaceSnapshot | None


@dataclass(slots=True)
class _MaskStrokeHistoryState:
    """Accumulate one mask's in-progress stroke history values."""

    patches: list[MaskPatch] = field(default_factory=list)
    already_applied: bool | None = None
    structural_before: MaskSurfaceSnapshot | None = None

    def reset(self) -> None:
        """Clear all history captured for the next stroke."""
        self.patches.clear()
        self.already_applied = None
        self.structural_before = None


class MaskStrokeHistorySession:
    """Own in-progress stroke history without owning surface persistence."""

    def __init__(self) -> None:
        """Initialize without active per-mask stroke state."""
        self._states: dict[uuid.UUID, _MaskStrokeHistoryState] = {}

    def begin(self, mask_id: uuid.UUID) -> None:
        """Reset history capture for a new stroke on ``mask_id``."""
        self._states.setdefault(mask_id, _MaskStrokeHistoryState()).reset()

    def add_patch(
        self,
        mask_id: uuid.UUID,
        patch: MaskPatch,
        *,
        already_applied: bool,
    ) -> None:
        """Append one patch while preserving consistent application semantics."""
        state = self._states.setdefault(mask_id, _MaskStrokeHistoryState())
        if (
            state.already_applied is not None
            and state.already_applied != already_applied
        ):
            raise ValueError("A stroke cannot mix applied and unapplied mask patches.")
        state.already_applied = already_applied
        state.patches.append(patch)

    def capture_structure(
        self,
        mask_id: uuid.UUID,
        before: MaskSurfaceSnapshot,
    ) -> None:
        """Retain only the first pre-growth surface snapshot for a stroke."""
        state = self._states.setdefault(mask_id, _MaskStrokeHistoryState())
        if state.structural_before is None:
            state.structural_before = before

    def consume(self, mask_id: uuid.UUID) -> MaskStrokeHistoryPayload:
        """Return and remove all history captured for ``mask_id``."""
        state = self._states.pop(mask_id, None)
        if state is None:
            return MaskStrokeHistoryPayload((), False, None)
        return MaskStrokeHistoryPayload(
            patches=tuple(state.patches),
            already_applied=bool(state.already_applied),
            structural_before=state.structural_before,
        )

    def discard(self, mask_id: uuid.UUID) -> None:
        """Forget an unfinished stroke's history capture."""
        self._states.pop(mask_id, None)
