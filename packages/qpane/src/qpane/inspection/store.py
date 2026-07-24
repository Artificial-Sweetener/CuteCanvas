#    QPane - High-performance PySide6 image viewer
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
"""Authoritative linked and independent inspection-state ownership."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ..types import LinkedGroup
from .model import InspectionUpdate, InspectionViewState, InspectionZoomMode

InspectionObserver = Callable[[InspectionUpdate], None]


@dataclass(frozen=True, slots=True)
class _StoredState:
    """Remember the target that authored a normalized inspection state."""

    source_target_id: uuid.UUID
    state: InspectionViewState


@dataclass(frozen=True, slots=True)
class _Subscription:
    """Bind one observer token to a target identity."""

    target_id: uuid.UUID
    callback: InspectionObserver


class InspectionStateStore:
    """Own independent and deliberately linked normalized inspection states."""

    def __init__(self) -> None:
        """Initialize empty groups, states, observers, and generation."""
        self._groups: tuple[LinkedGroup, ...] = ()
        self._group_by_target: dict[uuid.UUID, uuid.UUID] = {}
        self._group_states: dict[uuid.UUID, _StoredState] = {}
        self._individual_states: dict[uuid.UUID, _StoredState] = {}
        self._subscriptions: dict[uuid.UUID, _Subscription] = {}
        self._generation = 0
        self._dispatching = False

    @property
    def generation(self) -> int:
        """Return the last published state generation."""
        return self._generation

    def groups(self) -> tuple[LinkedGroup, ...]:
        """Return immutable linked-target group records."""
        return self._groups

    def group_id_for(self, target_id: uuid.UUID) -> uuid.UUID | None:
        """Return the group containing ``target_id`` when linked."""
        return self._group_by_target.get(target_id)

    def state_for(self, target_id: uuid.UUID) -> InspectionViewState | None:
        """Return the current group or independent state for one target."""
        stored = self._stored_state_for(target_id)
        if stored is None:
            return None
        state = stored.state
        if (
            stored.source_target_id != target_id
            and state.zoom_mode is InspectionZoomMode.ONE_TO_ONE
        ):
            return InspectionViewState(state.region, InspectionZoomMode.CUSTOM)
        return state

    def replace_groups(self, groups: Iterable[LinkedGroup]) -> None:
        """Replace non-overlapping groups while preserving stable group state."""
        validated = self._validate_groups(groups)
        next_group_ids = {group.group_id for group in validated}
        self._group_states = {
            group_id: state
            for group_id, state in self._group_states.items()
            if group_id in next_group_ids
        }
        next_index: dict[uuid.UUID, uuid.UUID] = {}
        for group in validated:
            for target_id in group.members:
                next_index[target_id] = group.group_id
                self._individual_states.pop(target_id, None)
        self._groups = tuple(validated)
        self._group_by_target = next_index

    def update(
        self,
        target_id: uuid.UUID,
        state: InspectionViewState,
        *,
        source_subscription: uuid.UUID | None = None,
    ) -> int:
        """Store state and synchronously notify other views in its link group.

        Nested updates emitted while applying a notification are ignored. A
        receiving adapter can therefore update its viewport without recursively
        republishing the same generation.

        Args:
            target_id: Target whose viewport authored the state.
            state: Captured normalized state.
            source_subscription: Optional observer token that originated the
                update and must not receive its own notification.

        Returns:
            Monotonic generation assigned to the accepted update.
        """
        if not isinstance(target_id, uuid.UUID):
            raise TypeError("target_id must be a UUID")
        if not isinstance(state, InspectionViewState):
            raise TypeError("state must be an InspectionViewState")
        if self._dispatching:
            return self._generation
        stored = _StoredState(target_id, state)
        group_id = self.group_id_for(target_id)
        if group_id is None:
            self._individual_states[target_id] = stored
        else:
            self._group_states[group_id] = stored
        self._generation += 1
        generation = self._generation
        recipients = (
            {target_id} if group_id is None else set(self._group_members(group_id))
        )
        self._dispatching = True
        try:
            for token, subscription in tuple(self._subscriptions.items()):
                if token == source_subscription:
                    continue
                if subscription.target_id not in recipients:
                    continue
                projected_state = self.state_for(subscription.target_id)
                if projected_state is None:
                    continue
                subscription.callback(
                    InspectionUpdate(
                        generation=generation,
                        source_target_id=target_id,
                        target_id=subscription.target_id,
                        state=projected_state,
                    )
                )
        finally:
            self._dispatching = False
        return generation

    def subscribe(
        self,
        target_id: uuid.UUID,
        callback: InspectionObserver,
    ) -> uuid.UUID:
        """Observe accepted state updates affecting one target."""
        if not isinstance(target_id, uuid.UUID):
            raise TypeError("target_id must be a UUID")
        if not callable(callback):
            raise TypeError("callback must be callable")
        token = uuid.uuid4()
        self._subscriptions[token] = _Subscription(target_id, callback)
        return token

    def unsubscribe(self, token: uuid.UUID) -> bool:
        """Remove an observer token when present."""
        return self._subscriptions.pop(token, None) is not None

    def discard(self, target_id: uuid.UUID) -> None:
        """Remove one target from states, groups, and observer subscriptions."""
        self._individual_states.pop(target_id, None)
        filtered_groups: list[LinkedGroup] = []
        for group in self._groups:
            members = tuple(member for member in group.members if member != target_id)
            if len(members) >= 2:
                filtered_groups.append(LinkedGroup(group.group_id, members))
            else:
                self._group_states.pop(group.group_id, None)
        self.replace_groups(filtered_groups)
        self._subscriptions = {
            token: subscription
            for token, subscription in self._subscriptions.items()
            if subscription.target_id != target_id
        }

    def clear(self) -> None:
        """Clear groups and states while retaining live subscriptions."""
        self._groups = ()
        self._group_by_target.clear()
        self._group_states.clear()
        self._individual_states.clear()

    def _stored_state_for(self, target_id: uuid.UUID) -> _StoredState | None:
        """Return the stored group or individual state for one target."""
        group_id = self.group_id_for(target_id)
        if group_id is None:
            return self._individual_states.get(target_id)
        return self._group_states.get(group_id)

    def _group_members(self, group_id: uuid.UUID) -> tuple[uuid.UUID, ...]:
        """Return members belonging to one stable group."""
        return next(
            (group.members for group in self._groups if group.group_id == group_id),
            (),
        )

    @staticmethod
    def _validate_groups(groups: Iterable[LinkedGroup]) -> list[LinkedGroup]:
        """Validate stable identities, unique members, and non-overlap."""
        validated: list[LinkedGroup] = []
        group_ids: set[uuid.UUID] = set()
        assigned: set[uuid.UUID] = set()
        for group in groups:
            if not isinstance(group, LinkedGroup):
                raise TypeError("inspection groups must be LinkedGroup values")
            if not isinstance(group.group_id, uuid.UUID):
                raise TypeError("inspection group IDs must be UUID values")
            if group.group_id in group_ids:
                raise ValueError("inspection group IDs must be unique")
            members = tuple(dict.fromkeys(group.members))
            if any(not isinstance(member, uuid.UUID) for member in members):
                raise TypeError("inspection group members must be UUID values")
            if len(members) < 2:
                raise ValueError("inspection groups require at least two targets")
            if assigned.intersection(members):
                raise ValueError("inspection targets cannot belong to multiple groups")
            group_ids.add(group.group_id)
            assigned.update(members)
            validated.append(LinkedGroup(group.group_id, members))
        return validated
