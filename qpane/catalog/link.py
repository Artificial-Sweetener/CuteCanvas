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

"""Link management utilities for synchronized view states."""

import logging
import uuid
from collections.abc import Iterable

from ..rendering import NormalizedViewState
from ..types import LinkedGroup

logger = logging.getLogger(__name__)


class LinkManager:
    """Maintain shared NormalizedViewState for grouped and individual images."""

    def __init__(self) -> None:
        """Initialize a new LinkManager with empty state."""
        self.clear()

    def clear(self) -> None:
        """Reset all groups and view states to their default empty state."""
        self._groups: list[LinkedGroup] = []
        self._group_states: dict[uuid.UUID, NormalizedViewState] = {}
        self._individual_states: dict[uuid.UUID, NormalizedViewState] = {}
        self._group_index_by_image: dict[uuid.UUID, int] = {}

    def getGroupRecords(self) -> tuple[LinkedGroup, ...]:
        """Return link groups paired with their stable identifiers."""
        return tuple(self._groups)

    def getGroupIdForImage(self, image_id: uuid.UUID) -> uuid.UUID | None:
        """Return the group identifier for ``image_id`` when linked."""
        index = self._find_group_index_for_image(image_id)
        if index is None:
            return None
        if index >= len(self._groups):
            return None
        return self._groups[index].group_id

    def getViewState(self, image_id: uuid.UUID) -> NormalizedViewState | None:
        """Return the group state if present; otherwise the individual state."""
        group_idx = self._find_group_index_for_image(image_id)
        if group_idx is not None:
            group_id = self._groups[group_idx].group_id
            return self._group_states.get(group_id)
        return self._individual_states.get(image_id)

    def setGroups(self, groups: Iterable[LinkedGroup]) -> None:
        """Define linked view groups and preserve view state when possible."""
        validated = self._validate_groups(groups)
        if not validated:
            self._groups = []
            self._group_states.clear()
            self._group_index_by_image.clear()
            return
        previous_state_lookup = dict(self._group_states)
        previous_membership_lookup = {
            group.group_id: set(group.members) for group in self._groups
        }
        new_groups: list[LinkedGroup] = []
        new_group_states: dict[uuid.UUID, NormalizedViewState] = {}
        new_index_map: dict[uuid.UUID, int] = {}
        for index, group in enumerate(validated):
            members_set = set(group.members)
            previous_members = previous_membership_lookup.get(group.group_id)
            if previous_members is not None and group.group_id in previous_state_lookup:
                new_group_states[group.group_id] = previous_state_lookup[group.group_id]
            for image_id in members_set:
                new_index_map[image_id] = index
                self._individual_states.pop(image_id, None)
            new_groups.append(group)
        self._groups = new_groups
        self._group_states = new_group_states
        self._group_index_by_image = new_index_map

    def updateViewState(self, image_id: uuid.UUID, state: NormalizedViewState) -> None:
        """Store a normalized view state for ``image_id`` or its group."""
        group_idx = self._find_group_index_for_image(image_id)
        if group_idx is not None:
            group_id = self._groups[group_idx].group_id
            self._group_states[group_id] = state
        else:
            self._individual_states[image_id] = state

    def handleImageRemoved(self, removed_id: uuid.UUID) -> None:
        """Purge ``removed_id`` from all link structures and keep indices stable."""
        self._individual_states.pop(removed_id, None)
        self._group_index_by_image.pop(removed_id, None)
        new_groups: list[LinkedGroup] = []
        new_group_states: dict[uuid.UUID, NormalizedViewState] = {}
        new_index_map: dict[uuid.UUID, int] = {}
        for old_index, group in enumerate(list(self._groups)):
            filtered_members = tuple(
                member for member in group.members if member != removed_id
            )
            if len(filtered_members) < 2:
                continue
            new_index = len(new_groups)
            group_id = group.group_id
            new_groups.append(LinkedGroup(group_id=group_id, members=filtered_members))
            if group_id in self._group_states:
                new_group_states[group_id] = self._group_states[group_id]
            for member in filtered_members:
                new_index_map[member] = new_index
        self._groups = new_groups
        self._group_states = new_group_states
        self._group_index_by_image = new_index_map

    def _find_group_index_for_image(self, image_id: uuid.UUID) -> int | None:
        """Return the group index for ``image_id`` or ``None`` when ungrouped."""
        return self._group_index_by_image.get(image_id)

    def _validate_groups(self, groups: Iterable[LinkedGroup]) -> list[LinkedGroup]:
        """Return sanitized link groups, dropping invalid or overlapping entries."""
        validated: list[LinkedGroup] = []
        seen_group_ids: set[uuid.UUID] = set()
        assigned_members: set[uuid.UUID] = set()
        for group in groups:
            if not isinstance(group, LinkedGroup):
                logger.warning(
                    "Ignoring link group because it is not a LinkedGroup: %s", group
                )
                continue
            group_id = group.group_id
            if not isinstance(group_id, uuid.UUID):
                logger.warning("Ignoring link group with non-UUID id: %s", group_id)
                continue
            if group_id in seen_group_ids:
                logger.warning(
                    "Ignoring duplicate link group id %s in request", group_id
                )
                continue
            unique_members = tuple(dict.fromkeys(group.members))
            sanitized_members = tuple(
                member for member in unique_members if isinstance(member, uuid.UUID)
            )
            member_set = set(sanitized_members)
            if len(member_set) < 2:
                logger.warning(
                    "Ignoring link group %s because it needs at least two unique IDs",
                    group_id,
                )
                continue
            if member_set & assigned_members:
                logger.warning(
                    "Ignoring link group %s because members cannot belong to multiple groups",
                    group_id,
                )
                continue
            seen_group_ids.add(group_id)
            assigned_members.update(member_set)
            validated.append(LinkedGroup(group_id=group_id, members=sanitized_members))
        return validated
