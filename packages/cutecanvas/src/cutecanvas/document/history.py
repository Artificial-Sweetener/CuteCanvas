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

"""Expose safe document-history inspection and identity-specific replay."""

from __future__ import annotations

import uuid

from ..composition.edit_controller import CompositionEditController
from ..composition.edit_history import CompositionEditHistory
from ..composition.history_model import HistoryCommandMetadata


class DocumentHistory:
    """Provide metadata-only chronology and validated replay for one document."""

    def __init__(
        self,
        history: CompositionEditHistory,
        controller: CompositionEditController,
    ) -> None:
        """Bind the authoritative store and replay dispatcher."""
        self._history = history
        self._controller = controller

    def undo_candidate(self, scope_id: uuid.UUID) -> HistoryCommandMetadata | None:
        """Return the current undo identity for one scope."""
        entry = self._history.undo_entry(scope_id)
        return None if entry is None else entry.metadata

    def redo_candidate(self, scope_id: uuid.UUID) -> HistoryCommandMetadata | None:
        """Return the current redo identity for one scope."""
        entry = self._history.redo_entry(scope_id)
        return None if entry is None else entry.metadata

    def undo_entries(self, scope_id: uuid.UUID) -> tuple[HistoryCommandMetadata, ...]:
        """Return applied metadata in chronological order."""
        return tuple(entry.metadata for entry in self._history.undo_entries(scope_id))

    def redo_entries(self, scope_id: uuid.UUID) -> tuple[HistoryCommandMetadata, ...]:
        """Return reverted metadata in replay order."""
        return tuple(entry.metadata for entry in self._history.redo_entries(scope_id))

    def undo(self, scope_id: uuid.UUID, command_id: uuid.UUID) -> bool:
        """Undo only if the supplied identity is the current candidate."""
        return self._controller.undo_identity(scope_id, command_id).changed

    def redo(self, scope_id: uuid.UUID, command_id: uuid.UUID) -> bool:
        """Redo only if the supplied identity is the current candidate."""
        return self._controller.redo_identity(scope_id, command_id).changed


__all__ = ["DocumentHistory"]
