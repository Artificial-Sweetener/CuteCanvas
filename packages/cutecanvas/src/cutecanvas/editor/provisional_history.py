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
"""Bound immutable semantic checkpoints for one unresolved edit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

_Value = TypeVar("_Value")


@dataclass(frozen=True, slots=True)
class ProvisionalCheckpoint(Generic[_Value]):
    """Pair one immutable semantic value with its user-facing action label."""

    value: _Value
    label: str | None


@dataclass(frozen=True, slots=True)
class ProvisionalHistorySnapshot:
    """Report cursor state without exposing retained checkpoint values."""

    can_undo: bool
    can_redo: bool
    undo_label: str | None
    redo_label: str | None
    undo_depth: int
    redo_depth: int


class BoundedProvisionalHistory(Generic[_Value]):
    """Own a permanent base plus a bounded sequence of intermediate values."""

    def __init__(self, base: _Value, *, checkpoint_limit: int) -> None:
        """Create history rooted at ``base`` with a positive bounded capacity."""
        if (
            not isinstance(checkpoint_limit, int)
            or isinstance(checkpoint_limit, bool)
            or not 1 <= checkpoint_limit <= 4096
        ):
            raise ValueError("checkpoint_limit must be between 1 and 4096")
        self._checkpoint_limit = checkpoint_limit
        self._checkpoints = [ProvisionalCheckpoint(base, None)]
        self._cursor = 0

    @property
    def base(self) -> _Value:
        """Return the immutable session starting value."""
        return self._checkpoints[0].value

    @property
    def current(self) -> _Value:
        """Return the value selected by the current history cursor."""
        return self._checkpoints[self._cursor].value

    @property
    def snapshot(self) -> ProvisionalHistorySnapshot:
        """Return detached availability, labels, and retained depths."""
        can_undo = self._cursor > 0
        can_redo = self._cursor + 1 < len(self._checkpoints)
        return ProvisionalHistorySnapshot(
            can_undo,
            can_redo,
            self._checkpoints[self._cursor].label if can_undo else None,
            self._checkpoints[self._cursor + 1].label if can_redo else None,
            self._cursor,
            len(self._checkpoints) - self._cursor - 1,
        )

    def push(self, value: _Value, label: str) -> bool:
        """Append a distinct settled value and discard its abandoned redo branch."""
        normalized_label = label.strip()
        if not normalized_label:
            raise ValueError("checkpoint label must not be empty")
        if value == self.current:
            return False
        del self._checkpoints[self._cursor + 1 :]
        self._checkpoints.append(ProvisionalCheckpoint(value, normalized_label))
        self._cursor = len(self._checkpoints) - 1
        if len(self._checkpoints) - 1 > self._checkpoint_limit:
            del self._checkpoints[1]
            self._cursor -= 1
        return True

    def undo(self) -> _Value | None:
        """Select the previous retained value without crossing the session base."""
        if self._cursor == 0:
            return None
        self._cursor -= 1
        return self.current

    def redo(self) -> _Value | None:
        """Select the next retained value when no new branch replaced it."""
        if self._cursor + 1 >= len(self._checkpoints):
            return None
        self._cursor += 1
        return self.current


__all__ = [
    "BoundedProvisionalHistory",
    "ProvisionalCheckpoint",
    "ProvisionalHistorySnapshot",
]
