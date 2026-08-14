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

"""Authoritative chronological storage for composition editing commands."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable

from qpane.sdk.scene import LayerSourceReference

from .history_model import (
    CompositionEditCommand,
    CompositionHistoryEntry,
    HistoryCommandMetadata,
    HistoryCommit,
    HistoryDurability,
    HistoryRetainedStorage,
    HistoryTruncation,
    HistoryTruncationReason,
)
from .history_policy import CompositionHistoryPolicy, SoftLimitHistoryPolicy
from .resource_lifetime import CompositionResourceLifetime, ResourceLeaseKind


class CompositionEditHistory:
    """Own chronological undo and redo branches for each edit scope."""

    def __init__(
        self,
        *,
        command_limit: int = 100,
        byte_limit: int = 256 * 1024 * 1024,
        policy: CompositionHistoryPolicy | None = None,
        resource_lifetime: CompositionResourceLifetime | None = None,
        committed: Callable[[HistoryCommit], None] | None = None,
        truncated: Callable[[HistoryTruncation], None] | None = None,
        released: Callable[[CompositionEditCommand], None] | None = None,
    ) -> None:
        """Initialize policy-owned scope histories and observers."""
        self._policy = policy or SoftLimitHistoryPolicy(
            command_limit=command_limit,
            byte_limit=byte_limit,
        )
        self._resource_lifetime = resource_lifetime or CompositionResourceLifetime()
        self._committed = committed
        self._truncated = truncated
        self._released = released
        self._undo_by_scope: dict[uuid.UUID, list[CompositionHistoryEntry]] = {}
        self._redo_by_scope: dict[uuid.UUID, list[CompositionHistoryEntry]] = {}
        self._entries_by_id: dict[uuid.UUID, CompositionHistoryEntry] = {}
        self._next_sequence_number = 1

    def record_applied(self, command: CompositionEditCommand) -> HistoryCommit:
        """Record one applied command and return its stable public identity."""
        entry = self._entry_for_new_command(command)
        self._acquire_command(command)
        self._entries_by_id[entry.metadata.command_id] = entry
        undo = self._undo_by_scope.setdefault(entry.metadata.scope_id, [])
        undo.append(entry)
        redo = self._redo_by_scope.pop(entry.metadata.scope_id, ())
        self._truncate_entries(redo, HistoryTruncationReason.REDO_BRANCH)
        self._enforce_policy(entry)
        commit = HistoryCommit(entry.metadata)
        if self._committed is not None:
            self._committed(commit)
        return commit

    def undo_candidate(self, scope_id: uuid.UUID) -> CompositionEditCommand | None:
        """Return the latest applied command without advancing history."""
        entry = self.undo_entry(scope_id)
        return None if entry is None else entry.command

    def redo_candidate(self, scope_id: uuid.UUID) -> CompositionEditCommand | None:
        """Return the latest reverted command without advancing history."""
        entry = self.redo_entry(scope_id)
        return None if entry is None else entry.command

    def undo_entry(self, scope_id: uuid.UUID) -> CompositionHistoryEntry | None:
        """Return the latest applied entry with stable identity metadata."""
        entries = self._undo_by_scope.get(scope_id)
        return entries[-1] if entries else None

    def redo_entry(self, scope_id: uuid.UUID) -> CompositionHistoryEntry | None:
        """Return the latest reverted entry with stable identity metadata."""
        entries = self._redo_by_scope.get(scope_id)
        return entries[-1] if entries else None

    def entry(self, command_id: uuid.UUID) -> CompositionHistoryEntry | None:
        """Return a retained entry by stable command identity."""
        return self._entries_by_id.get(command_id)

    def commit_undo(self, command: CompositionEditCommand) -> bool:
        """Move one successfully reverted command to its redo branch."""
        entry = self.undo_entry(command.scope_id)
        return bool(
            entry is not None
            and entry.command is command
            and self.commit_undo_identity(command.scope_id, entry.metadata.command_id)
        )

    def commit_redo(self, command: CompositionEditCommand) -> bool:
        """Move one successfully reapplied command to its undo branch."""
        entry = self.redo_entry(command.scope_id)
        return bool(
            entry is not None
            and entry.command is command
            and self.commit_redo_identity(command.scope_id, entry.metadata.command_id)
        )

    def commit_undo_identity(self, scope_id: uuid.UUID, command_id: uuid.UUID) -> bool:
        """Advance undo only when ``command_id`` is the current candidate."""
        undo = self._undo_by_scope.get(scope_id)
        if not undo or undo[-1].metadata.command_id != command_id:
            return False
        entry = undo.pop()
        self._redo_by_scope.setdefault(scope_id, []).append(entry)
        return True

    def commit_redo_identity(self, scope_id: uuid.UUID, command_id: uuid.UUID) -> bool:
        """Advance redo only when ``command_id`` is the current candidate."""
        redo = self._redo_by_scope.get(scope_id)
        if not redo or redo[-1].metadata.command_id != command_id:
            return False
        entry = redo.pop()
        self._undo_by_scope.setdefault(scope_id, []).append(entry)
        return True

    def clear_scope(self, scope_id: uuid.UUID) -> None:
        """Discard all edit history owned by one removed scope."""
        entries = (
            *self._undo_by_scope.pop(scope_id, ()),
            *self._redo_by_scope.pop(scope_id, ()),
        )
        self._truncate_entries(entries, HistoryTruncationReason.SCOPE_CLEARED)

    def clear(self) -> None:
        """Discard every edit history branch."""
        for scope_id in tuple({*self._undo_by_scope, *self._redo_by_scope}):
            entries = (
                *self._undo_by_scope.pop(scope_id, ()),
                *self._redo_by_scope.pop(scope_id, ()),
            )
            self._truncate_entries(entries, HistoryTruncationReason.HISTORY_CLEARED)

    def undo_commands(self, scope_id: uuid.UUID) -> tuple[CompositionEditCommand, ...]:
        """Return the applied branch in chronological order for diagnostics."""
        return tuple(entry.command for entry in self._undo_by_scope.get(scope_id, ()))

    def redo_commands(self, scope_id: uuid.UUID) -> tuple[CompositionEditCommand, ...]:
        """Return the reverted branch in replay order for diagnostics."""
        return tuple(entry.command for entry in self._redo_by_scope.get(scope_id, ()))

    def undo_entries(self, scope_id: uuid.UUID) -> tuple[CompositionHistoryEntry, ...]:
        """Return applied entries with their stable command identities."""
        return tuple(self._undo_by_scope.get(scope_id, ()))

    def redo_entries(self, scope_id: uuid.UUID) -> tuple[CompositionHistoryEntry, ...]:
        """Return reverted entries with their stable command identities."""
        return tuple(self._redo_by_scope.get(scope_id, ()))

    def discard_where(
        self,
        predicate: Callable[[CompositionEditCommand], bool],
    ) -> None:
        """Discard commands matching a source-lifecycle predicate."""
        for scope_id in tuple({*self._undo_by_scope, *self._redo_by_scope}):
            discarded: list[CompositionHistoryEntry] = []
            for branches in (self._undo_by_scope, self._redo_by_scope):
                entries = branches.get(scope_id, [])
                retained = [entry for entry in entries if not predicate(entry.command)]
                discarded.extend(entry for entry in entries if predicate(entry.command))
                if retained:
                    branches[scope_id] = retained
                else:
                    branches.pop(scope_id, None)
            self._truncate_entries(discarded, HistoryTruncationReason.INVALIDATED)

    def retained_bytes(self, scope_id: uuid.UUID) -> int:
        """Return bytes retained across one scope's undo and redo branches."""
        return self._entries_retained_bytes(
            (
                *self._undo_by_scope.get(scope_id, ()),
                *self._redo_by_scope.get(scope_id, ()),
            )
        )

    def _enforce_policy(self, newest: CompositionHistoryEntry) -> None:
        """Apply injected policy while keeping the newest entry protected."""
        scope_id = newest.metadata.scope_id
        evictions = self._policy.evictions(
            tuple(self._undo_by_scope.get(scope_id, ())),
            tuple(self._redo_by_scope.get(scope_id, ())),
            newest,
        )
        reasons: dict[HistoryTruncationReason, list[CompositionHistoryEntry]] = {}
        for eviction in evictions:
            reasons.setdefault(eviction.reason, []).append(eviction.entry)
        for reason, entries in reasons.items():
            self._remove_from_branches(scope_id, entries)
            self._truncate_entries(entries, reason)

    def _remove_from_branches(
        self,
        scope_id: uuid.UUID,
        entries: Iterable[CompositionHistoryEntry],
    ) -> None:
        """Remove selected identities from both branches without releasing them."""
        command_ids = {entry.metadata.command_id for entry in entries}
        for branches in (self._undo_by_scope, self._redo_by_scope):
            current = branches.get(scope_id, [])
            retained = [
                entry
                for entry in current
                if entry.metadata.command_id not in command_ids
            ]
            if retained:
                branches[scope_id] = retained
            else:
                branches.pop(scope_id, None)

    def _truncate_entries(
        self,
        entries: Iterable[CompositionHistoryEntry],
        reason: HistoryTruncationReason,
    ) -> None:
        """Release entries and publish one exact typed truncation event."""
        removed = tuple(entries)
        if not removed:
            return
        scope_id = removed[0].metadata.scope_id
        remaining = (
            *self._undo_by_scope.get(scope_id, ()),
            *self._redo_by_scope.get(scope_id, ()),
        )
        before = self._entries_retained_bytes((*remaining, *removed))
        for entry in removed:
            self._entries_by_id.pop(entry.metadata.command_id, None)
            self._release_command(entry.command)
        event = HistoryTruncation(
            scope_id=scope_id,
            reason=reason,
            evicted=tuple(entry.metadata for entry in removed),
            retained_bytes_before=before,
            retained_bytes_after=self.retained_bytes(scope_id),
        )
        if self._truncated is not None:
            self._truncated(event)

    def _acquire_command(self, command: CompositionEditCommand) -> None:
        """Acquire history leases retained by one command."""
        for source in self._command_resources(command):
            self._resource_lifetime.acquire(source, ResourceLeaseKind.HISTORY)

    def _release_command(self, command: CompositionEditCommand) -> None:
        """Release one discarded command's resource leases exactly once."""
        for source in self._command_resources(command):
            self._resource_lifetime.release(source, ResourceLeaseKind.HISTORY)
        if self._released is not None:
            self._released(command)

    def _entry_for_new_command(
        self,
        command: CompositionEditCommand,
    ) -> CompositionHistoryEntry:
        """Validate a command and attach stable history-owned metadata."""
        scope_id = command.scope_id
        if not isinstance(scope_id, uuid.UUID):
            raise TypeError("edit command scope_id must be a UUID")
        retained_storage = self._command_storage(command)
        retained_bytes = sum(item.retained_bytes for item in retained_storage)
        durability = getattr(command, "history_durability", HistoryDurability.DURABLE)
        if not isinstance(durability, HistoryDurability):
            raise TypeError("edit command history_durability must be HistoryDurability")
        edit_kind = getattr(command, "history_kind", type(command).__name__)
        if not isinstance(edit_kind, str) or not edit_kind.strip():
            raise TypeError("edit command history_kind must be a non-empty string")
        sequence_number = self._next_sequence_number
        self._next_sequence_number += 1
        return CompositionHistoryEntry(
            HistoryCommandMetadata(
                command_id=uuid.uuid4(),
                scope_id=scope_id,
                edit_kind=edit_kind,
                durability=durability,
                retained_bytes=retained_bytes,
                sequence_number=sequence_number,
            ),
            command,
            retained_storage,
        )

    @staticmethod
    def _entries_retained_bytes(
        entries: Iterable[CompositionHistoryEntry],
    ) -> int:
        """Return unique immutable storage retained by chronological entries."""
        storage: dict[int, int] = {}
        for entry in entries:
            for item in entry.retained_storage:
                storage[item.storage_id] = item.retained_bytes
        return sum(storage.values())

    @classmethod
    def _command_storage(
        cls,
        command: CompositionEditCommand,
    ) -> tuple[HistoryRetainedStorage, ...]:
        """Return validated shared storage or one command-owned allocation."""
        declared = getattr(command, "history_retained_storage", None)
        if declared is None:
            retained_bytes = cls._command_bytes(command)
            return (HistoryRetainedStorage(id(command), retained_bytes),)
        storage = tuple(declared)
        if not all(isinstance(item, HistoryRetainedStorage) for item in storage):
            raise TypeError(
                "history_retained_storage must contain HistoryRetainedStorage values"
            )
        unique: dict[int, HistoryRetainedStorage] = {}
        for item in storage:
            if item.retained_bytes < 0:
                raise ValueError("history retained storage bytes must be non-negative")
            previous = unique.get(item.storage_id)
            if previous is not None and previous.retained_bytes != item.retained_bytes:
                raise ValueError("shared history storage size must remain stable")
            unique[item.storage_id] = item
        return tuple(unique.values())

    @staticmethod
    def _command_resources(
        command: CompositionEditCommand,
    ) -> tuple[LayerSourceReference, ...]:
        """Return validated source references retained by one command."""
        resources = tuple(getattr(command, "retained_resources", ()))
        if not all(isinstance(source, LayerSourceReference) for source in resources):
            raise TypeError("history retained_resources must contain source references")
        return resources

    @staticmethod
    def _command_bytes(command: CompositionEditCommand) -> int:
        """Validate and return one command's retained byte estimate."""
        retained_bytes = int(command.retained_bytes)
        if retained_bytes < 0:
            raise ValueError("edit command retained_bytes must be non-negative")
        return retained_bytes


__all__ = ["CompositionEditCommand", "CompositionEditHistory"]
