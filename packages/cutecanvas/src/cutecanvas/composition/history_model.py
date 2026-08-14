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

"""Typed identities and observable events for composition edit chronology."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class CompositionEditCommand(Protocol):
    """Describe a replayable value accepted by composition history."""

    @property
    def scope_id(self) -> uuid.UUID:
        """Return the composition identity owning this command."""
        ...

    @property
    def retained_bytes(self) -> int:
        """Return the conservative bytes retained by this command."""
        ...


class HistoryDurability(str, Enum):
    """Classify whether an edit changes durable document content."""

    DURABLE = "durable"
    TRANSIENT = "transient"


class HistoryTruncationReason(str, Enum):
    """Identify why replayable chronology was discarded."""

    COMMAND_LIMIT = "command-limit"
    BYTE_LIMIT = "byte-limit"
    REDO_BRANCH = "redo-branch"
    INVALIDATED = "invalidated"
    SCOPE_CLEARED = "scope-cleared"
    HISTORY_CLEARED = "history-cleared"


@dataclass(frozen=True, slots=True)
class HistoryCommandMetadata:
    """Expose stable identity and retention details for one command."""

    command_id: uuid.UUID
    scope_id: uuid.UUID
    edit_kind: str
    durability: HistoryDurability
    retained_bytes: int
    sequence_number: int


@dataclass(frozen=True, slots=True)
class CompositionHistoryEntry:
    """Bind one command to its stable chronological metadata."""

    metadata: HistoryCommandMetadata
    command: CompositionEditCommand
    retained_storage: tuple[HistoryRetainedStorage, ...]


@dataclass(frozen=True, slots=True)
class HistoryRetainedStorage:
    """Identify immutable storage shared by one or more history commands."""

    storage_id: int
    retained_bytes: int


@dataclass(frozen=True, slots=True)
class HistoryCommit:
    """Report one command accepted into chronological history."""

    metadata: HistoryCommandMetadata


@dataclass(frozen=True, slots=True)
class HistoryTruncation:
    """Report commands removed together for one explicit reason."""

    scope_id: uuid.UUID
    reason: HistoryTruncationReason
    evicted: tuple[HistoryCommandMetadata, ...]
    retained_bytes_before: int
    retained_bytes_after: int


__all__ = [
    "CompositionEditCommand",
    "CompositionHistoryEntry",
    "HistoryCommandMetadata",
    "HistoryCommit",
    "HistoryDurability",
    "HistoryRetainedStorage",
    "HistoryTruncation",
    "HistoryTruncationReason",
]
