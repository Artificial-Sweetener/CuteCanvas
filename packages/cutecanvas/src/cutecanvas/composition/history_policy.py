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

"""Injected retention policy for composition edit chronology."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .history_model import (
    CompositionHistoryEntry,
    HistoryDurability,
    HistoryTruncationReason,
)


@dataclass(frozen=True, slots=True)
class HistoryEviction:
    """Select one retained entry for policy-driven eviction."""

    entry: CompositionHistoryEntry
    reason: HistoryTruncationReason


class CompositionHistoryPolicy(Protocol):
    """Select evictions without mutating authoritative chronology."""

    def evictions(
        self,
        undo: tuple[CompositionHistoryEntry, ...],
        redo: tuple[CompositionHistoryEntry, ...],
        newest: CompositionHistoryEntry,
    ) -> tuple[HistoryEviction, ...]:
        """Return ordered evictions while preserving ``newest``."""
        ...


class SoftLimitHistoryPolicy:
    """Apply independent soft count and byte budgets by durability class."""

    def __init__(self, *, command_limit: int = 100, byte_limit: int = 256 << 20):
        """Initialize positive count and non-negative byte limits."""
        if command_limit < 0:
            raise ValueError("edit history command limit must be non-negative")
        if byte_limit < 0:
            raise ValueError("edit history byte limit must be non-negative")
        self._command_limit = int(command_limit)
        self._byte_limit = int(byte_limit)

    def evictions(
        self,
        undo: tuple[CompositionHistoryEntry, ...],
        redo: tuple[CompositionHistoryEntry, ...],
        newest: CompositionHistoryEntry,
    ) -> tuple[HistoryEviction, ...]:
        """Evict oldest entries while protecting each class's newest command."""
        selected: list[HistoryEviction] = []
        removed: set[object] = set()
        for durability in HistoryDurability:
            applied = [
                entry for entry in undo if entry.metadata.durability is durability
            ]
            protected = applied[-1] if applied else None
            while len(applied) > self._command_limit:
                candidate = next(
                    (entry for entry in applied if entry is not protected),
                    None,
                )
                if candidate is None:
                    break
                applied.remove(candidate)
                removed.add(candidate.metadata.command_id)
                selected.append(
                    HistoryEviction(candidate, HistoryTruncationReason.COMMAND_LIMIT)
                )
            retained = [
                entry
                for entry in (*undo, *redo)
                if entry.metadata.durability is durability
                and entry.metadata.command_id not in removed
            ]
            candidates = [entry for entry in retained if entry is not protected]
            while _retained_bytes(retained) > self._byte_limit and candidates:
                candidate = candidates.pop(0)
                retained.remove(candidate)
                removed.add(candidate.metadata.command_id)
                selected.append(
                    HistoryEviction(candidate, HistoryTruncationReason.BYTE_LIMIT)
                )
        return tuple(selected)


def _retained_bytes(entries: list[CompositionHistoryEntry]) -> int:
    """Return unique immutable storage retained by ``entries``."""
    storage: dict[int, int] = {}
    for entry in entries:
        for item in entry.retained_storage:
            storage[item.storage_id] = item.retained_bytes
    return sum(storage.values())


class ExternalHistoryPolicy:
    """Retain every command for an externally coordinated history owner."""

    def evictions(
        self,
        undo: tuple[CompositionHistoryEntry, ...],
        redo: tuple[CompositionHistoryEntry, ...],
        newest: CompositionHistoryEntry,
    ) -> tuple[HistoryEviction, ...]:
        """Return no private evictions."""
        del undo, redo, newest
        return ()


__all__ = [
    "CompositionHistoryPolicy",
    "ExternalHistoryPolicy",
    "HistoryEviction",
    "SoftLimitHistoryPolicy",
]
