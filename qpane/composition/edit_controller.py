#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Dispatch chronological composition edits to their authoritative domains."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from .edit_history import CompositionEditCommand, CompositionEditHistory


@dataclass(frozen=True, slots=True)
class CompositionEditExecution:
    """Describe one attempted chronological undo or redo."""

    command: CompositionEditCommand | None
    changed: bool


@runtime_checkable
class CompositionEditCompletionAware(Protocol):
    """Optional command hook invoked after history chronology is committed."""

    def edit_completed(self, direction: Literal["undo", "redo"]) -> None:
        """Publish domain presentation after a completed history transition."""
        ...


class CompositionEditController:
    """Own command-handler registration and chronological history execution."""

    def __init__(
        self,
        history: CompositionEditHistory,
        changed: Callable[[uuid.UUID], None] | None = None,
    ) -> None:
        """Bind the sole history store and optional scope-change observer."""
        self._history = history
        self._changed = changed
        self._handlers: dict[
            type[object],
            tuple[
                Callable[[CompositionEditCommand], bool],
                Callable[[CompositionEditCommand], bool],
            ],
        ] = {}

    def register_handler(
        self,
        command_type: type[object],
        *,
        undo: Callable[[CompositionEditCommand], bool],
        redo: Callable[[CompositionEditCommand], bool],
    ) -> None:
        """Register the one authoritative handler for ``command_type``."""
        handler = (undo, redo)
        existing = self._handlers.get(command_type)
        if existing == handler:
            return
        if existing is not None:
            raise ValueError(f"edit handler already registered for {command_type!r}")
        self._handlers[command_type] = handler

    def record_applied(self, command: CompositionEditCommand) -> None:
        """Append an already-applied command to the chronological history."""
        self._history.record_applied(command)
        self._notify_changed(command.scope_id)

    def can_undo(self, scope_id: uuid.UUID) -> bool:
        """Return whether the next undo command has an installed handler."""
        return self._handler_for(self._history.undo_candidate(scope_id)) is not None

    def can_redo(self, scope_id: uuid.UUID) -> bool:
        """Return whether the next redo command has an installed handler."""
        return self._handler_for(self._history.redo_candidate(scope_id)) is not None

    def undo(self, scope_id: uuid.UUID) -> CompositionEditExecution:
        """Undo the latest command when its domain accepts the operation."""
        command = self._history.undo_candidate(scope_id)
        handler = self._handler_for(command)
        if command is None or handler is None or not handler[0](command):
            return CompositionEditExecution(command=command, changed=False)
        self._history.commit_undo(command)
        self._publish_completion(command, "undo")
        self._notify_changed(command.scope_id)
        return CompositionEditExecution(command=command, changed=True)

    def redo(self, scope_id: uuid.UUID) -> CompositionEditExecution:
        """Redo the latest reverted command when its domain accepts it."""
        command = self._history.redo_candidate(scope_id)
        handler = self._handler_for(command)
        if command is None or handler is None or not handler[1](command):
            return CompositionEditExecution(command=command, changed=False)
        self._history.commit_redo(command)
        self._publish_completion(command, "redo")
        self._notify_changed(command.scope_id)
        return CompositionEditExecution(command=command, changed=True)

    def undo_where(
        self,
        scope_id: uuid.UUID,
        predicate: Callable[[CompositionEditCommand], bool],
    ) -> CompositionEditExecution:
        """Undo the latest matching command for a legacy domain facade."""
        command = self._history.undo_candidate_where(scope_id, predicate)
        handler = self._handler_for(command)
        if command is None or handler is None or not handler[0](command):
            return CompositionEditExecution(command=command, changed=False)
        self._history.commit_selective_undo(command)
        self._publish_completion(command, "undo")
        self._notify_changed(command.scope_id)
        return CompositionEditExecution(command=command, changed=True)

    def redo_where(
        self,
        scope_id: uuid.UUID,
        predicate: Callable[[CompositionEditCommand], bool],
    ) -> CompositionEditExecution:
        """Redo the latest matching command for a legacy domain facade."""
        command = self._history.redo_candidate_where(scope_id, predicate)
        handler = self._handler_for(command)
        if command is None or handler is None or not handler[1](command):
            return CompositionEditExecution(command=command, changed=False)
        self._history.commit_selective_redo(command)
        self._publish_completion(command, "redo")
        self._notify_changed(command.scope_id)
        return CompositionEditExecution(command=command, changed=True)

    def undo_commands(self, scope_id: uuid.UUID) -> tuple[CompositionEditCommand, ...]:
        """Return the applied branch for state presentation."""
        return self._history.undo_commands(scope_id)

    def redo_commands(self, scope_id: uuid.UUID) -> tuple[CompositionEditCommand, ...]:
        """Return the reverted branch for state presentation."""
        return self._history.redo_commands(scope_id)

    def discard_where(
        self,
        predicate: Callable[[CompositionEditCommand], bool],
    ) -> None:
        """Discard commands invalidated by source lifecycle changes."""
        self._history.discard_where(predicate)

    def _notify_changed(self, scope_id: uuid.UUID) -> None:
        """Notify presentation that one scope's history availability changed."""
        if self._changed is not None:
            self._changed(scope_id)

    def _handler_for(
        self,
        command: CompositionEditCommand | None,
    ) -> (
        tuple[
            Callable[[CompositionEditCommand], bool],
            Callable[[CompositionEditCommand], bool],
        ]
        | None
    ):
        """Return the exact registered handler for ``command``."""
        return None if command is None else self._handlers.get(type(command))

    @staticmethod
    def _publish_completion(
        command: CompositionEditCommand,
        direction: Literal["undo", "redo"],
    ) -> None:
        """Invoke an optional command-owned post-chronology notification."""
        if isinstance(command, CompositionEditCompletionAware):
            command.edit_completed(direction)
