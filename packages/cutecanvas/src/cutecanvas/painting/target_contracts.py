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
"""Typed identities, capabilities, and registration for editable paint targets."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from PySide6.QtGui import QColor
from qpane.sdk.scene import LayerDescriptor, RasterBounds, SceneDescriptor

from ..types import PaintTargetKind
from .model import BrushPreset, BrushStrokeSegment

if TYPE_CHECKING:
    from cutecanvas.coverage import CoverageItem, CoverageSnapshot
    from cutecanvas.coverage.operations import CoverageCombineMode
    from cutecanvas.fill.sources import FloodFillPixelSource


@dataclass(frozen=True, slots=True)
class PaintTargetIdentity:
    """Identify one composition-local destination selected for painting."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID | None
    kind: PaintTargetKind = PaintTargetKind.LAYER

    def __post_init__(self) -> None:
        """Reject contradictory target identities."""
        kind = PaintTargetKind(self.kind)
        if kind is PaintTargetKind.LAYER and self.layer_id is None:
            raise ValueError("layer paint targets require a layer_id")
        if kind is not PaintTargetKind.LAYER and self.layer_id is not None:
            raise ValueError("scene paint targets must not include a layer_id")
        object.__setattr__(self, "kind", kind)


@dataclass(frozen=True, slots=True)
class PaintTargetContext:
    """Resolve one paint identity to its scene and optional layer snapshot."""

    identity: PaintTargetIdentity
    scene: SceneDescriptor
    layer: LayerDescriptor | None


@runtime_checkable
class PaintTargetOwner(Protocol):
    """Implement direct paint transactions for one typed destination domain."""

    def supports(self, target: PaintTargetContext) -> bool:
        """Return whether this owner exclusively handles ``target``."""
        ...

    def begin(self, target: PaintTargetContext) -> bool:
        """Begin one atomic paint history transaction."""
        ...

    def apply(
        self,
        target: PaintTargetContext,
        segment: BrushStrokeSegment,
        preset: BrushPreset,
        color: QColor,
    ) -> bool:
        """Apply one deterministic target-local segment to the transaction."""
        ...

    def commit(self, target: PaintTargetContext) -> bool:
        """Commit the active transaction as one history command."""
        ...

    def cancel(self, target: PaintTargetContext) -> bool:
        """Restore pixels captured before the active transaction."""
        ...

    def preview_color(self, target: PaintTargetContext, fallback: QColor) -> QColor:
        """Return the target-appropriate brush feedback color."""
        ...


@runtime_checkable
class PaintTargetInteractionPreparer(Protocol):
    """Prepare target-owned spatial authority before pointer coordinates resolve."""

    def prepare_interaction(self, target: PaintTargetContext) -> bool:
        """Make one current target ready for direct pointer-local painting."""
        ...


@runtime_checkable
class RetainedCoverageTargetOwner(Protocol):
    """Commit semantic coverage items to a compatible paint destination."""

    def commit_coverage_item(
        self,
        target: PaintTargetContext,
        item: CoverageItem,
    ) -> bool:
        """Commit one target-local retained coverage contribution."""
        ...


@dataclass(frozen=True, slots=True)
class FloodFillSource:
    """Carry immutable target-local sampling pixels and stale-work identity."""

    pixels: FloodFillPixelSource
    bounds: RasterBounds
    revision: object


@runtime_checkable
class FloodFillTargetOwner(Protocol):
    """Sample and atomically commit paint-bucket coverage for one target."""

    def flood_fill_source(self, target: PaintTargetContext) -> FloodFillSource | None:
        """Return detached target-local pixels and their content revision."""
        ...

    def commit_flood_fill(
        self,
        target: PaintTargetContext,
        coverage: CoverageSnapshot,
        mode: CoverageCombineMode,
        expected_revision: object,
        color: QColor,
    ) -> bool:
        """Commit only when sampled authority still has ``expected_revision``."""
        ...


@runtime_checkable
class CoverageFillTargetOwner(Protocol):
    """Apply bounded coverage to one paint destination atomically."""

    def commit_fill_coverage(
        self,
        target: PaintTargetContext,
        coverage: CoverageSnapshot,
        mode: CoverageCombineMode,
        color: QColor,
    ) -> bool:
        """Commit one target-local coverage fill as a single history step."""
        ...


class PaintTargetRegistry:
    """Route direct paint operations to one authoritative owner per target."""

    def __init__(self) -> None:
        """Initialize an empty ordered owner collection."""
        self._owners: list[PaintTargetOwner] = []
        self._idle_feedback: dict[object, Callable[[QColor], QColor | None]] = {}

    def register(self, owner: PaintTargetOwner) -> PaintTargetOwner:
        """Register one owner exactly once."""
        if owner not in self._owners:
            self._owners.append(owner)
        return owner

    def unregister(self, owner: PaintTargetOwner) -> None:
        """Remove one owner without disturbing other domains."""
        self._owners = [
            candidate for candidate in self._owners if candidate is not owner
        ]
        self._idle_feedback.pop(owner, None)

    def register_idle_feedback(
        self,
        owner: object,
        provider: Callable[[QColor], QColor | None],
    ) -> None:
        """Register optional brush feedback shown before a target exists."""
        self._idle_feedback[owner] = provider

    def idle_preview_color(self, fallback: QColor) -> QColor | None:
        """Return the first available passive brush-feedback color."""
        for provider in self._idle_feedback.values():
            color = provider(QColor(fallback))
            if isinstance(color, QColor) and color.isValid():
                return QColor(color)
        return None

    def owner_for(self, target: PaintTargetContext) -> PaintTargetOwner | None:
        """Return the sole owner that advertises ``target`` support."""
        matches = [owner for owner in self._owners if owner.supports(target)]
        if len(matches) > 1:
            raise RuntimeError("multiple paint target owners support one layer")
        return None if not matches else matches[0]
