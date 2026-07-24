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
"""Atomic history ownership for resolved floating raster edits."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from qpane.sdk.scene import LayerSourceReference, LayerTransform

from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.scene.pixel_transitions import RasterPixelTransition

from ..composition.edit_controller import CompositionEditController
from ..composition.edit_history import CompositionEditCommand
from ..scene.layer_selection import SceneLayerSelection
from ..selection import PixelSelectionService
from .floating_layers import FloatingLayerPromotionRegistry, FloatingLayerTransition


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
    origin_session_id: uuid.UUID
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

    @property
    def retained_resources(self) -> tuple[LayerSourceReference, ...]:
        """Return source payloads kept reachable by this history command."""
        return () if self.promotion is None else self.promotion.resources


class PixelTransitionHistoryOwner(Protocol):
    """Replay one layer-bound pixel transition without view state."""

    def matches(
        self,
        item: LayerPixelTransition,
        *,
        use_after: bool,
    ) -> bool:
        """Return whether the resource equals one transition side."""
        ...

    def restore(
        self,
        item: LayerPixelTransition,
        *,
        use_after: bool,
    ) -> bool:
        """Restore one transition side."""
        ...


class FloatingPixelHistory:
    """Record and replay atomic floating-content resolutions."""

    def __init__(
        self,
        *,
        edits: CompositionEditController,
        transitions: PixelTransitionHistoryOwner,
        pixel_selection: PixelSelectionService,
        promotions: FloatingLayerPromotionRegistry,
    ) -> None:
        """Bind chronology and authoritative raster/selection owners."""
        self._edits = edits
        self._transitions = transitions
        self._pixel_selection = pixel_selection
        self._promotions = promotions
        self._replay_subscribers: dict[
            uuid.UUID,
            list[Callable[[FloatingPixelCommitEdit, bool], None]],
        ] = {}
        edits.register_handler(
            FloatingPixelCommitEdit,
            undo=lambda command: self._restore(command, use_after=False),
            redo=lambda command: self._restore(command, use_after=True),
        )

    def record(self, command: FloatingPixelCommitEdit) -> None:
        """Record an already-applied floating raster resolution."""
        self._edits.record_applied(command)

    def subscribe_replay(
        self,
        session_id: uuid.UUID,
        callback: Callable[[FloatingPixelCommitEdit, bool], None],
    ) -> Callable[[], None]:
        """Observe replay hints only for one originating view session."""
        subscribers = self._replay_subscribers.setdefault(session_id, [])
        if callback not in subscribers:
            subscribers.append(callback)

        def unsubscribe() -> None:
            """Detach this view session's replay observer idempotently."""
            current = self._replay_subscribers.get(session_id)
            if current is None:
                return
            if callback in current:
                current.remove(callback)
            if not current:
                self._replay_subscribers.pop(session_id, None)

        return unsubscribe

    def _restore(
        self,
        command: CompositionEditCommand,
        *,
        use_after: bool,
    ) -> bool:
        """Restore every participating raster and editor state transactionally."""
        if not isinstance(command, FloatingPixelCommitEdit):
            return False
        if any(
            not self._transitions.matches(item, use_after=not use_after)
            for item in _current_endpoints(
                command.transitions,
                use_after=use_after,
            )
        ):
            return False
        promotion = command.promotion
        promotion_owner = (
            None
            if promotion is None
            else self._promotions.owner_for_transition(promotion)
        )
        expected_after = not use_after
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
        applied: list[LayerPixelTransition] = []
        ordered = (
            command.transitions if use_after else tuple(reversed(command.transitions))
        )
        for item in ordered:
            if not self._transitions.restore(item, use_after=use_after):
                self._rollback(applied, use_after=not use_after)
                if promotion_changed:
                    promotion_owner.restore(promotion, use_after=True)
                return False
            applied.append(item)
        if use_after and promotion is not None:
            if not promotion_owner.restore(promotion, use_after=True):
                self._rollback(applied, use_after=False)
                return False
            promotion_changed = True
        selection = command.selection_after if use_after else command.selection_before
        if not self._pixel_selection.replace_with_raster(command.scene_id, selection):
            if promotion_changed:
                promotion_owner.restore(promotion, use_after=not use_after)
            self._rollback(applied, use_after=not use_after)
            return False
        for callback in tuple(
            self._replay_subscribers.get(command.origin_session_id, ())
        ):
            callback(command, use_after)
        return True

    def _rollback(
        self,
        applied: list[LayerPixelTransition],
        *,
        use_after: bool,
    ) -> None:
        """Restore already-applied raster transitions in reverse order."""
        for item in reversed(applied):
            self._transitions.restore(item, use_after=use_after)


def _current_endpoints(
    transitions: tuple[LayerPixelTransition, ...],
    *,
    use_after: bool,
) -> tuple[LayerPixelTransition, ...]:
    """Return the observable transition endpoint for each participating layer."""
    endpoints: dict[tuple[uuid.UUID, uuid.UUID], LayerPixelTransition] = {}
    ordered = transitions if use_after else tuple(reversed(transitions))
    for item in ordered:
        key = (item.scene_id, item.layer_id)
        if key not in endpoints:
            endpoints[key] = item
    return tuple(endpoints.values())
