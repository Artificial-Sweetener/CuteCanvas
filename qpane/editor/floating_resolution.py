#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Durable, atomic resolution of floating raster edit sessions."""

from __future__ import annotations

import uuid
from typing import TypeAlias

from ..coverage import CoverageSnapshot
from ..scene.layer_selection import SceneLayerSelection, SceneLayerSelectionController
from ..scene.model import LayerDescriptor
from ..scene.pixel_owners import LayerPixelMutationOwner
from ..scene.pixel_transitions import RasterPixelTransition
from ..scene.raster import LayerTransform
from ..selection import LayerCoverageProjector, PixelSelectionService
from .floating_history import (
    FloatingPixelCommitEdit,
    FloatingPixelHistory,
    LayerPixelTransition,
)
from .floating_layers import (
    FloatingLayerPromotionOwner,
    FloatingLayerPromotionRegistry,
    FloatingLayerTransition,
)
from .floating_session import FloatingPixelSession
from .fragment_projection import RasterFragmentProjector
from .pixel_move_target import SelectedPixelMoveTargetResolver
from .selection_projection import (
    LayerSelectionProjectionCache,
    translated_coverage_within,
)

_AppliedTransition: TypeAlias = tuple[
    LayerDescriptor,
    LayerPixelMutationOwner,
    RasterPixelTransition,
]


class FloatingPixelResolutionOwner:
    """Apply one floating session to source, destination, or a new layer."""

    def __init__(
        self,
        *,
        targets: SelectedPixelMoveTargetResolver,
        history: FloatingPixelHistory,
        pixel_selection: PixelSelectionService,
        layer_selection: SceneLayerSelectionController,
        selection_projections: LayerSelectionProjectionCache,
        promotions: FloatingLayerPromotionRegistry,
    ) -> None:
        """Bind durable raster, selection, promotion, and history owners."""
        self._targets = targets
        self._history = history
        self._pixel_selection = pixel_selection
        self._layer_selection = layer_selection
        self._selection_projections = selection_projections
        self._promotions = promotions
        self._fragment_projector = RasterFragmentProjector()
        self._coverage_projector = LayerCoverageProjector()

    def anchor_to_source(self, session: FloatingPixelSession) -> bool:
        """Apply current displacement to the original editable layer."""
        delta_x, delta_y = session.delta
        if delta_x == 0 and delta_y == 0:
            return True
        resolved = self._targets.resolve_layer(session.scene_id, session.layer_id)
        if resolved is None:
            return False
        _scene, layer, owner = resolved
        transition = session.preview_transition
        if transition is None or not owner.transition_matches(
            layer, transition, use_after=False
        ):
            return False
        if not owner.restore_transition(layer, transition, use_after=True):
            return False
        local_after = translated_coverage_within(
            session.local_coverage,
            delta_x,
            delta_y,
            transition.after_surface_bounds,
        )
        return self._finalize(
            session=session,
            transitions=(
                LayerPixelTransition(session.scene_id, session.layer_id, transition),
            ),
            selection_after=session.movement_selection.translated(*session.scene_delta),
            selected_after=session.selected_layer,
            local_after=local_after,
            target_transform=layer.transform,
            rollback=((layer, owner, transition),),
        )

    def anchor_to(
        self,
        session: FloatingPixelSession,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> bool:
        """Apply the session to a compatible existing destination layer."""
        if scene_id != session.scene_id:
            return False
        if layer_id == session.layer_id:
            return self.anchor_to_source(session)
        source_resolved = self._targets.resolve_layer(
            session.scene_id,
            session.layer_id,
        )
        target_resolved = self._targets.resolve_layer(scene_id, layer_id)
        if source_resolved is None or target_resolved is None:
            return False
        _source_scene, source_layer, source_owner = source_resolved
        _target_scene, target_layer, target_owner = target_resolved
        if not self._compatible_transition(
            session,
            source_layer,
            source_owner,
            target_layer,
            target_owner,
        ):
            return False
        placed = self._fragment_projector.project(
            session.lift.fragment,
            source_transform=source_layer.transform,
            source_delta=session.delta,
            destination_transform=target_layer.transform,
        )
        if placed is None:
            return False
        applied_source = self._apply_source_cut(session, source_layer, source_owner)
        if session.cut_source and not applied_source:
            return False
        target_transition = target_owner.place_fragment(
            target_layer,
            placed,
            placed.bounds,
        )
        if target_transition is None:
            self._restore_source_cut(
                session,
                source_layer,
                source_owner,
                applied_source,
            )
            return False
        local_after = translated_coverage_within(
            placed.coverage,
            0,
            0,
            target_transition.after_surface_bounds,
        )
        selection_after = self._coverage_projector.project(
            local_after,
            target_layer.transform,
        )
        rollback: tuple[_AppliedTransition, ...] = (
            (target_layer, target_owner, target_transition),
        )
        transitions: tuple[LayerPixelTransition, ...] = ()
        if applied_source:
            transitions = (
                LayerPixelTransition(
                    session.scene_id,
                    session.layer_id,
                    session.lift.source_transition,
                ),
            )
            rollback += ((source_layer, source_owner, session.lift.source_transition),)
        transitions += (LayerPixelTransition(scene_id, layer_id, target_transition),)
        if selection_after is None:
            self._rollback_transitions(rollback)
            return False
        return self._finalize(
            session=session,
            transitions=transitions,
            selection_after=selection_after,
            selected_after=SceneLayerSelection(scene_id, layer_id),
            local_after=local_after,
            target_transform=target_layer.transform,
            rollback=rollback,
        )

    def promote(
        self,
        session: FloatingPixelSession,
        label: str | None,
    ) -> uuid.UUID | None:
        """Apply the session as a newly created compatible layer."""
        resolved = self._targets.resolve_layer(session.scene_id, session.layer_id)
        owner = self._promotions.owner_for_fragment(session.lift.fragment)
        if resolved is None or owner is None:
            return None
        scene, source_layer, source_owner = resolved
        if (
            source_layer.transform != session.layer.transform
            or not source_owner.transition_matches(
                source_layer,
                session.lift.source_transition,
                use_after=False,
            )
        ):
            return None
        applied_source = self._apply_source_cut(session, source_layer, source_owner)
        if session.cut_source and not applied_source:
            return None
        promotion = owner.promote(
            scene=scene,
            source_layer=source_layer,
            fragment=session.lift.fragment,
            delta=session.delta,
            label=label,
        )
        if promotion is None:
            self._restore_source_cut(
                session,
                source_layer,
                source_owner,
                applied_source,
            )
            return None
        selection_after = self._coverage_projector.project(
            session.lift.fragment.coverage,
            promotion.transform,
        )
        if selection_after is None:
            owner.restore(promotion, use_after=False)
            self._restore_source_cut(
                session,
                source_layer,
                source_owner,
                applied_source,
            )
            return None
        transitions = (
            (
                LayerPixelTransition(
                    session.scene_id,
                    session.layer_id,
                    session.lift.source_transition,
                ),
            )
            if applied_source
            else ()
        )
        rollback = (
            ((source_layer, source_owner, session.lift.source_transition),)
            if applied_source
            else ()
        )
        committed = self._finalize(
            session=session,
            transitions=transitions,
            selection_after=selection_after,
            selected_after=SceneLayerSelection(session.scene_id, promotion.layer_id),
            local_after=session.lift.fragment.coverage,
            target_transform=promotion.transform,
            rollback=rollback,
            promotion=promotion,
            promotion_owner=owner,
        )
        return promotion.layer_id if committed else None

    def _finalize(
        self,
        *,
        session: FloatingPixelSession,
        transitions: tuple[LayerPixelTransition, ...],
        selection_after: CoverageSnapshot,
        selected_after: SceneLayerSelection,
        local_after: CoverageSnapshot,
        target_transform: LayerTransform | None,
        rollback: tuple[_AppliedTransition, ...],
        promotion: FloatingLayerTransition | None = None,
        promotion_owner: FloatingLayerPromotionOwner | None = None,
    ) -> bool:
        """Commit selection state and record already-applied raster transitions."""
        if not self._pixel_selection.restore(session.scene_id, selection_after):
            if promotion is not None and promotion_owner is not None:
                promotion_owner.restore(promotion, use_after=False)
            self._rollback_transitions(rollback)
            return False
        self._layer_selection.select(selected_after.scene_id, selected_after.layer_id)
        selection_state = self._pixel_selection.state(session.scene_id)
        if target_transform is not None:
            self._selection_projections.remember(
                scene_id=session.scene_id,
                layer_id=selected_after.layer_id,
                selection_revision=selection_state.revision,
                transform=target_transform,
                coverage=local_after,
            )
        self._history.record(
            FloatingPixelCommitEdit(
                scene_id=session.scene_id,
                transitions=transitions,
                selection_before=session.selection,
                selection_after=selection_after,
                selected_before=session.selected_layer,
                selected_after=selected_after,
                local_before=session.local_coverage,
                local_after=local_after,
                source_transform=session.layer.transform,
                target_transform=target_transform,
                promotion=promotion,
            )
        )
        return True

    @staticmethod
    def _compatible_transition(
        session: FloatingPixelSession,
        source_layer: LayerDescriptor,
        source_owner: LayerPixelMutationOwner,
        target_layer: LayerDescriptor,
        target_owner: LayerPixelMutationOwner,
    ) -> bool:
        """Return whether current owners can atomically accept the fragment."""
        return bool(
            source_layer.transform == session.layer.transform
            and source_layer.transform is not None
            and target_layer.transform is not None
            and source_owner.transition_matches(
                source_layer,
                session.lift.source_transition,
                use_after=False,
            )
            and target_owner.accepts_fragment(target_layer, session.lift.fragment)
        )

    @staticmethod
    def _apply_source_cut(
        session: FloatingPixelSession,
        layer: LayerDescriptor,
        owner: LayerPixelMutationOwner,
    ) -> bool:
        """Apply the lifted source remainder when the session is a cut."""
        return bool(
            not session.cut_source
            or owner.restore_transition(
                layer,
                session.lift.source_transition,
                use_after=True,
            )
        )

    @staticmethod
    def _restore_source_cut(
        session: FloatingPixelSession,
        layer: LayerDescriptor,
        owner: LayerPixelMutationOwner,
        applied: bool,
    ) -> None:
        """Restore source before-state after a downstream resolution failure."""
        if session.cut_source and applied:
            owner.restore_transition(
                layer,
                session.lift.source_transition,
                use_after=False,
            )

    @staticmethod
    def _rollback_transitions(rollback: tuple[_AppliedTransition, ...]) -> None:
        """Restore before-state for already-applied transitions."""
        for layer, owner, transition in rollback:
            owner.restore_transition(layer, transition, use_after=False)
