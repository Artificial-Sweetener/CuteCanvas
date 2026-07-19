#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Atomic history ownership for resolved floating raster edits."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TypeAlias

from ..composition.edit_controller import CompositionEditController
from ..composition.edit_history import CompositionEditCommand
from ..coverage import CoverageSnapshot
from ..scene.layer_selection import (
    SceneLayerSelection,
    SceneLayerSelectionController,
)
from ..scene.model import LayerDescriptor
from ..scene.pixel_owners import LayerPixelMutationOwner
from ..scene.pixel_transitions import RasterPixelTransition
from ..scene.raster import LayerTransform
from ..selection import PixelSelectionService
from .floating_layers import FloatingLayerPromotionRegistry, FloatingLayerTransition
from .pixel_move_target import SelectedPixelMoveTargetResolver
from .selection_projection import LayerSelectionProjectionCache


@dataclass(frozen=True, slots=True)
class LayerPixelTransition:
    """Bind one exact raster transition to its scene layer identity."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    raster: RasterPixelTransition


@dataclass(frozen=True, slots=True)
class FloatingPixelCommitEdit:
    """Retain one atomic multi-layer floating-pixel resolution."""

    scene_id: uuid.UUID
    transitions: tuple[LayerPixelTransition, ...]
    selection_before: CoverageSnapshot
    selection_after: CoverageSnapshot
    selected_before: SceneLayerSelection
    selected_after: SceneLayerSelection
    local_before: CoverageSnapshot
    local_after: CoverageSnapshot
    source_transform: LayerTransform | None
    target_transform: LayerTransform | None
    promotion: FloatingLayerTransition | None = None

    @property
    def scope_id(self) -> uuid.UUID:
        """Return the scene owning this editor transaction."""
        return self.scene_id

    @property
    def retained_bytes(self) -> int:
        """Return raster and selection bytes retained for history."""
        return int(
            sum(item.raster.retained_bytes for item in self.transitions)
            + self.selection_before.pixels.nbytes
            + self.selection_after.pixels.nbytes
            + self.local_before.pixels.nbytes
            + self.local_after.pixels.nbytes
            + (0 if self.promotion is None else self.promotion.retained_bytes)
        )


_ResolvedTransition: TypeAlias = tuple[
    LayerPixelTransition,
    LayerDescriptor,
    LayerPixelMutationOwner,
]


class FloatingPixelHistory:
    """Record and replay atomic floating-content resolutions."""

    def __init__(
        self,
        *,
        edits: CompositionEditController,
        targets: SelectedPixelMoveTargetResolver,
        pixel_selection: PixelSelectionService,
        layer_selection: SceneLayerSelectionController,
        selection_projections: LayerSelectionProjectionCache,
        promotions: FloatingLayerPromotionRegistry,
    ) -> None:
        """Bind chronology and authoritative raster/selection owners."""
        self._edits = edits
        self._targets = targets
        self._pixel_selection = pixel_selection
        self._layer_selection = layer_selection
        self._selection_projections = selection_projections
        self._promotions = promotions
        edits.register_handler(
            FloatingPixelCommitEdit,
            undo=lambda command: self._restore(command, use_after=False),
            redo=lambda command: self._restore(command, use_after=True),
        )

    def record(self, command: FloatingPixelCommitEdit) -> None:
        """Record an already-applied floating raster resolution."""
        self._edits.record_applied(command)

    def _restore(
        self,
        command: CompositionEditCommand,
        *,
        use_after: bool,
    ) -> bool:
        """Restore every participating raster and editor state transactionally."""
        if not isinstance(command, FloatingPixelCommitEdit):
            return False
        resolved: list[_ResolvedTransition] = []
        expected_after = not use_after
        for item in command.transitions:
            target = self._targets.resolve_layer(item.scene_id, item.layer_id)
            if target is None:
                return False
            _scene, layer, owner = target
            if not owner.transition_matches(
                layer,
                item.raster,
                use_after=expected_after,
            ):
                return False
            resolved.append((item, layer, owner))
        promotion = command.promotion
        promotion_owner = (
            None
            if promotion is None
            else self._promotions.owner_for_transition(promotion)
        )
        if promotion is not None and (
            promotion_owner is None
            or not promotion_owner.matches(promotion, use_after=expected_after)
        ):
            return False
        promotion_changed = False
        if not use_after and promotion is not None:
            if not promotion_owner.restore(promotion, use_after=False):
                return False
            promotion_changed = True
        applied: list[_ResolvedTransition] = []
        ordered = resolved if use_after else list(reversed(resolved))
        for item, layer, owner in ordered:
            if not owner.restore_transition(layer, item.raster, use_after=use_after):
                self._rollback(applied, use_after=not use_after)
                if promotion_changed:
                    promotion_owner.restore(promotion, use_after=True)
                return False
            applied.append((item, layer, owner))
        if use_after and promotion is not None:
            if not promotion_owner.restore(promotion, use_after=True):
                self._rollback(applied, use_after=False)
                return False
            promotion_changed = True
        selection = command.selection_after if use_after else command.selection_before
        if not self._pixel_selection.restore(command.scene_id, selection):
            if promotion_changed:
                promotion_owner.restore(promotion, use_after=not use_after)
            self._rollback(applied, use_after=not use_after)
            return False
        selected = command.selected_after if use_after else command.selected_before
        self._layer_selection.select(selected.scene_id, selected.layer_id)
        self._remember_projection(command, use_after=use_after)
        return True

    @staticmethod
    def _rollback(
        applied: list[_ResolvedTransition],
        *,
        use_after: bool,
    ) -> None:
        """Restore already-applied raster transitions in reverse order."""
        for item, layer, owner in reversed(applied):
            owner.restore_transition(layer, item.raster, use_after=use_after)

    def _remember_projection(
        self,
        command: FloatingPixelCommitEdit,
        *,
        use_after: bool,
    ) -> None:
        """Associate replayed selection with its selected layer coordinate space."""
        transform = command.target_transform if use_after else command.source_transform
        if transform is None:
            return
        state = self._pixel_selection.state(command.scene_id)
        selected = command.selected_after if use_after else command.selected_before
        local = command.local_after if use_after else command.local_before
        self._selection_projections.remember(
            scene_id=command.scene_id,
            layer_id=selected.layer_id,
            selection_revision=state.revision,
            transform=transform,
            coverage=local,
        )
