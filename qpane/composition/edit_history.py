#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Byte-budgeted chronological history for composition editing commands."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Protocol

from ..scene.source_references import LayerSourceReference
from .resource_lifetime import CompositionResourceLifetime, ResourceLeaseKind


class CompositionEditCommand(Protocol):
    """Values retained by the authoritative composition edit history."""

    @property
    def scope_id(self) -> uuid.UUID:
        """Return the composition or scene identity owning this command."""
        ...

    @property
    def retained_bytes(self) -> int:
        """Return the approximate memory retained exclusively for history."""
        ...


class CompositionEditHistory:
    """Own chronological undo and redo branches for each edit scope."""

    def __init__(
        self,
        *,
        command_limit: int = 100,
        byte_limit: int = 256 * 1024 * 1024,
        resource_lifetime: CompositionResourceLifetime | None = None,
        released: Callable[[CompositionEditCommand], None] | None = None,
    ) -> None:
        """Initialize bounded scope histories."""
        if command_limit <= 0:
            raise ValueError("edit history command limit must be positive")
        if byte_limit < 0:
            raise ValueError("edit history byte limit must be non-negative")
        self._command_limit = int(command_limit)
        self._byte_limit = int(byte_limit)
        self._resource_lifetime = resource_lifetime or CompositionResourceLifetime()
        self._released = released
        self._undo_by_scope: dict[uuid.UUID, list[CompositionEditCommand]] = {}
        self._redo_by_scope: dict[uuid.UUID, list[CompositionEditCommand]] = {}

    def record_applied(self, command: CompositionEditCommand) -> None:
        """Record one applied command and discard its scope's redo branch."""
        self._command_bytes(command)
        self._acquire_command(command)
        undo = self._undo_by_scope.setdefault(command.scope_id, [])
        undo.append(command)
        self._release_commands(self._redo_by_scope.pop(command.scope_id, ()))
        self._enforce_limits(command.scope_id)

    def undo_candidate(self, scope_id: uuid.UUID) -> CompositionEditCommand | None:
        """Return the latest applied command without advancing history."""
        commands = self._undo_by_scope.get(scope_id)
        return commands[-1] if commands else None

    def redo_candidate(self, scope_id: uuid.UUID) -> CompositionEditCommand | None:
        """Return the latest reverted command without advancing history."""
        commands = self._redo_by_scope.get(scope_id)
        return commands[-1] if commands else None

    def undo_candidate_where(
        self,
        scope_id: uuid.UUID,
        predicate: Callable[[CompositionEditCommand], bool],
    ) -> CompositionEditCommand | None:
        """Return the latest applied command accepted by ``predicate``."""
        return next(
            (
                command
                for command in reversed(self._undo_by_scope.get(scope_id, ()))
                if predicate(command)
            ),
            None,
        )

    def redo_candidate_where(
        self,
        scope_id: uuid.UUID,
        predicate: Callable[[CompositionEditCommand], bool],
    ) -> CompositionEditCommand | None:
        """Return the latest reverted command accepted by ``predicate``."""
        return next(
            (
                command
                for command in reversed(self._redo_by_scope.get(scope_id, ()))
                if predicate(command)
            ),
            None,
        )

    def commit_undo(self, command: CompositionEditCommand) -> bool:
        """Move one successfully reverted command to its redo branch."""
        undo = self._undo_by_scope.get(command.scope_id)
        if not undo or undo[-1] is not command:
            return False
        undo.pop()
        self._redo_by_scope.setdefault(command.scope_id, []).append(command)
        return True

    def commit_redo(self, command: CompositionEditCommand) -> bool:
        """Move one successfully reapplied command to its undo branch."""
        redo = self._redo_by_scope.get(command.scope_id)
        if not redo or redo[-1] is not command:
            return False
        redo.pop()
        self._undo_by_scope.setdefault(command.scope_id, []).append(command)
        return True

    def commit_selective_undo(self, command: CompositionEditCommand) -> bool:
        """Move one applied command to redo without creating a second history."""
        undo = self._undo_by_scope.get(command.scope_id)
        index = (
            None
            if undo is None
            else next(
                (
                    position
                    for position, candidate in enumerate(undo)
                    if candidate is command
                ),
                None,
            )
        )
        if undo is None or index is None:
            return False
        undo.pop(index)
        self._redo_by_scope.setdefault(command.scope_id, []).append(command)
        return True

    def commit_selective_redo(self, command: CompositionEditCommand) -> bool:
        """Move one reverted command back to the applied branch."""
        redo = self._redo_by_scope.get(command.scope_id)
        index = (
            None
            if redo is None
            else next(
                (
                    position
                    for position, candidate in enumerate(redo)
                    if candidate is command
                ),
                None,
            )
        )
        if redo is None or index is None:
            return False
        redo.pop(index)
        self._undo_by_scope.setdefault(command.scope_id, []).append(command)
        return True

    def clear_scope(self, scope_id: uuid.UUID) -> None:
        """Discard all edit history owned by one removed scope."""
        self._release_commands(self._undo_by_scope.pop(scope_id, ()))
        self._release_commands(self._redo_by_scope.pop(scope_id, ()))

    def clear(self) -> None:
        """Discard every edit history branch."""
        for commands in self._undo_by_scope.values():
            self._release_commands(commands)
        for commands in self._redo_by_scope.values():
            self._release_commands(commands)
        self._undo_by_scope.clear()
        self._redo_by_scope.clear()

    def undo_commands(self, scope_id: uuid.UUID) -> tuple[CompositionEditCommand, ...]:
        """Return the applied branch in chronological order for diagnostics."""
        return tuple(self._undo_by_scope.get(scope_id, ()))

    def redo_commands(self, scope_id: uuid.UUID) -> tuple[CompositionEditCommand, ...]:
        """Return the reverted branch in replay order for diagnostics."""
        return tuple(self._redo_by_scope.get(scope_id, ()))

    def discard_where(
        self,
        predicate: Callable[[CompositionEditCommand], bool],
    ) -> None:
        """Discard commands matching a source-lifecycle predicate."""
        for branches in (self._undo_by_scope, self._redo_by_scope):
            for scope_id, commands in tuple(branches.items()):
                retained = []
                discarded = []
                for command in commands:
                    (discarded if predicate(command) else retained).append(command)
                self._release_commands(discarded)
                if retained:
                    branches[scope_id] = retained
                else:
                    branches.pop(scope_id, None)

    def retained_bytes(self, scope_id: uuid.UUID) -> int:
        """Return bytes retained across one scope's undo and redo branches."""
        return sum(
            self._command_bytes(command)
            for command in (
                *self._undo_by_scope.get(scope_id, ()),
                *self._redo_by_scope.get(scope_id, ()),
            )
        )

    def _enforce_limits(self, scope_id: uuid.UUID) -> None:
        """Evict oldest applied commands until count and byte budgets hold."""
        undo = self._undo_by_scope.get(scope_id, [])
        while len(undo) > self._command_limit:
            self._release_command(undo.pop(0))
        while undo and self.retained_bytes(scope_id) > self._byte_limit:
            self._release_command(undo.pop(0))

    def _acquire_command(self, command: CompositionEditCommand) -> None:
        """Acquire history leases retained by one command."""
        for source in self._command_resources(command):
            self._resource_lifetime.acquire(source, ResourceLeaseKind.HISTORY)

    def _release_commands(
        self,
        commands: tuple[CompositionEditCommand, ...] | list[CompositionEditCommand],
    ) -> None:
        """Release a sequence of commands removed from chronology."""
        for command in commands:
            self._release_command(command)

    def _release_command(self, command: CompositionEditCommand) -> None:
        """Release one evicted command's resources and publish its callback."""
        for source in self._command_resources(command):
            self._resource_lifetime.release(source, ResourceLeaseKind.HISTORY)
        if self._released is not None:
            self._released(command)

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
