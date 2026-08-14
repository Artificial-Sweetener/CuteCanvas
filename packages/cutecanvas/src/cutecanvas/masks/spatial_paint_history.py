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

"""Own atomic history for painting after finite mask deformation."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from PySide6.QtCore import QRect

from qpane.sdk.scene import LayerMapping

from ..composition.geometry_policy import LayerGeometryPolicy
from ..composition.layers import CompositionLayerStore
from ..raster.sparse_grid import SparseRasterSnapshot
from .coverage_history import MaskCoverageState
from .mask import MaskAssetStore
from .mask_controller import MaskController
from .mask_undo import MaskUndoCommand, MaskUndoSnippet
from .spatial_paint_layers import update_spatial_paint_geometry


@dataclass(frozen=True, slots=True)
class MaskInstanceMappingTransition:
    """Capture one mask instance mapping changed by spatial normalization."""

    composition_id: uuid.UUID
    layer_id: uuid.UUID
    before: LayerMapping
    after: LayerMapping
    before_geometry: LayerGeometryPolicy
    after_geometry: LayerGeometryPolicy


@dataclass(frozen=True, slots=True)
class MaskSpatialPaintTransition:
    """Capture the exact state surrounding one provisional normalization."""

    mask_id: uuid.UUID
    before: MaskCoverageState
    normalized: MaskCoverageState
    mappings: tuple[MaskInstanceMappingTransition, ...]


@dataclass(slots=True)
class MaskSpatialPaintCommand:
    """Replay normalization and its first raster edit as one history step."""

    transition: MaskSpatialPaintTransition
    paint: MaskUndoCommand
    apply_coverage: Callable[[uuid.UUID, MaskCoverageState], None]
    apply_mappings: Callable[
        [tuple[MaskInstanceMappingTransition, ...], bool],
        None,
    ]
    description: str = "mask-spatial-paint"

    def undo(self) -> None:
        """Restore finite geometry and the exact pre-paint mask revision."""
        self.paint.undo()
        self.apply_coverage(self.transition.mask_id, self.transition.before)
        self.apply_mappings(self.transition.mappings, False)

    def redo(self) -> None:
        """Reapply normalized geometry followed by the raster edit."""
        self.apply_mappings(self.transition.mappings, True)
        self.apply_coverage(self.transition.mask_id, self.transition.normalized)
        self.paint.redo()

    def describe_delta(
        self,
        *,
        use_after: bool,
    ) -> Iterable[MaskUndoSnippet] | None:
        """Request full presentation invalidation for the spatial transition."""
        del use_after
        return None


class MaskSpatialPaintHistory:
    """Merge provisional mapping normalization into the next mask command."""

    def __init__(
        self,
        *,
        assets: MaskAssetStore,
        layers: CompositionLayerStore,
        controller: MaskController,
    ) -> None:
        """Bind the mask, layer-instance, and publication authorities."""
        self._assets = assets
        self._layers = layers
        self._controller = controller
        self._pending: dict[uuid.UUID, MaskSpatialPaintTransition] = {}

    def capture(self, transition: MaskSpatialPaintTransition) -> None:
        """Retain one applied normalization until its stroke settles."""
        if transition.mask_id in self._pending:
            raise RuntimeError("mask already has a pending spatial paint transition")
        self._pending[transition.mask_id] = transition

    def decorate(
        self,
        mask_id: uuid.UUID,
        command: MaskUndoCommand,
        retained_bytes: int,
    ) -> tuple[MaskUndoCommand, int]:
        """Consume and merge a pending normalization into one paint command."""
        transition = self._pending.pop(mask_id, None)
        if transition is None:
            return command, retained_bytes
        return (
            MaskSpatialPaintCommand(
                transition,
                command,
                self._apply_coverage,
                self._apply_mappings,
            ),
            retained_bytes + _transition_bytes(transition),
        )

    def restore_if_pending(self, mask_id: uuid.UUID) -> bool:
        """Roll back normalization when a gesture commits no mask mutation."""
        transition = self._pending.pop(mask_id, None)
        if transition is None:
            return False
        self._apply_coverage(mask_id, transition.before)
        self._apply_mappings(transition.mappings, False)
        return True

    def _apply_coverage(
        self,
        mask_id: uuid.UUID,
        state: MaskCoverageState,
    ) -> None:
        """Restore hybrid coverage and publish a complete mask revision."""
        layer = self._assets.get_layer(mask_id)
        if layer is None:
            return
        layer.coverage.raster.replace_with_state_snapshot(state.raster)
        layer.coverage.restore_retained(state.retained)
        self._assets.touch(mask_id)
        self._controller.edits.advance_epoch(mask_id, reason="spatial_paint_history")
        self._controller.renders.invalidate(mask_id, reason="spatial_paint_history")
        self._controller.mask_updated.emit(mask_id, QRect())

    def _apply_mappings(
        self,
        transitions: tuple[MaskInstanceMappingTransition, ...],
        use_after: bool,
    ) -> None:
        """Restore every instance mapping affected by one source-space bake."""
        for transition in transitions:
            update_spatial_paint_geometry(
                self._layers,
                transition.composition_id,
                transition.layer_id,
                transition.after if use_after else transition.before,
                (
                    transition.after_geometry
                    if use_after
                    else transition.before_geometry
                ),
            )


def _transition_bytes(transition: MaskSpatialPaintTransition) -> int:
    """Estimate detached state retained by one normalization transition."""
    return (
        _coverage_state_bytes(transition.before)
        + _coverage_state_bytes(transition.normalized)
        + 160 * len(transition.mappings)
    )


def _coverage_state_bytes(state: MaskCoverageState) -> int:
    """Estimate one hybrid revision without evaluating semantic coverage."""
    raster = state.raster
    raster_bytes = (
        raster.retained_bytes
        if isinstance(raster, SparseRasterSnapshot)
        else raster.pixels.nbytes
    )
    segment_count = sum(
        len(getattr(item, "segments", ())) for item in state.retained.items
    )
    return raster_bytes + len(state.retained.items) * 512 + segment_count * 256


__all__ = [
    "MaskInstanceMappingTransition",
    "MaskSpatialPaintHistory",
    "MaskSpatialPaintTransition",
]
