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
"""Injected stroke operations sharing one target-selection lifecycle."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from PySide6.QtGui import QColor

from .model import BrushPreset, BrushStrokeSegment
from .target_contracts import (
    PaintTargetContext,
    PaintTargetOwner,
    PaintTargetRegistry,
)
from .target_geometry import segment_with_target_tip_geometry


@runtime_checkable
class BrushStrokeOperation(Protocol):
    """Apply one brush behavior through the shared stroke lifecycle."""

    def supports(self, target: PaintTargetContext) -> bool:
        """Return whether the operation can edit ``target``."""
        ...

    def begin(self, target: PaintTargetContext) -> bool:
        """Begin one atomic target transaction."""
        ...

    def apply(
        self,
        target: PaintTargetContext,
        segment: BrushStrokeSegment,
        preset: BrushPreset,
        color: QColor,
    ) -> bool:
        """Apply one configured semantic stroke segment."""
        ...

    def commit(self, target: PaintTargetContext) -> bool:
        """Commit the active transaction."""
        ...

    def cancel(self, target: PaintTargetContext) -> bool:
        """Cancel the active transaction."""
        ...

    def preview_color(self, target: PaintTargetContext, fallback: QColor) -> QColor:
        """Return the operation's target-aware feedback color."""
        ...


class DirectBrushStrokeOperation:
    """Delegate ordinary paint and erase strokes to target-domain owners."""

    def __init__(self, targets: PaintTargetRegistry) -> None:
        """Bind the sole registry resolving direct-paint target ownership."""
        self._targets = targets
        self._active_owner: PaintTargetOwner | None = None

    def supports(self, target: PaintTargetContext) -> bool:
        """Return whether a direct-paint owner accepts ``target``."""
        return self._targets.owner_for(target) is not None

    def begin(self, target: PaintTargetContext) -> bool:
        """Capture the exact owner used for the complete transaction."""
        owner = self._targets.owner_for(target)
        self._active_owner = (
            owner if owner is not None and owner.begin(target) else None
        )
        return self._active_owner is not None

    def apply(
        self,
        target: PaintTargetContext,
        segment: BrushStrokeSegment,
        preset: BrushPreset,
        color: QColor,
    ) -> bool:
        """Apply through the owner captured at transaction start."""
        owner = self._active_owner
        return bool(
            owner is not None
            and owner.apply(
                target,
                segment_with_target_tip_geometry(segment, target),
                preset,
                color,
            )
        )

    def commit(self, target: PaintTargetContext) -> bool:
        """Commit through the captured owner and release it."""
        owner = self._active_owner
        self._active_owner = None
        return bool(owner is not None and owner.commit(target))

    def cancel(self, target: PaintTargetContext) -> bool:
        """Cancel through the captured owner and release it."""
        owner = self._active_owner
        self._active_owner = None
        return bool(owner is not None and owner.cancel(target))

    def preview_color(self, target: PaintTargetContext, fallback: QColor) -> QColor:
        """Return direct-paint feedback from the current target owner."""
        owner = self._targets.owner_for(target)
        return QColor(
            fallback if owner is None else owner.preview_color(target, fallback)
        )
