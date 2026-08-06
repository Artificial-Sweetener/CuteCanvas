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
"""Focused public composition persistence over the archive service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..persistence import (
    CompositionArchiveSnapshot,
    CompositionPersistenceService,
)
from .composition_handles import CompositionHandle
from .handles import EditorHandleHost


@dataclass(frozen=True, slots=True)
class DocumentPersistenceSnapshot:
    """Carry detached document authority prepared for background persistence."""

    composition_ids: tuple[uuid.UUID, ...]
    _archive: CompositionArchiveSnapshot = field(repr=False)


class CompositionPersistenceFacade:
    """Save and load complete editable compositions through typed handles."""

    def __init__(
        self,
        host: EditorHandleHost,
        service: CompositionPersistenceService,
    ) -> None:
        """Bind handle resolution and the sole archive workflow owner."""
        self._host = host
        self._service = service

    def save(self, composition: CompositionHandle, path: str | Path) -> None:
        """Atomically save a composition and every referenced resource."""
        self._service.save(composition.id, Path(path))

    def load(
        self,
        path: str | Path,
        *,
        open_composition: bool = True,
    ) -> CompositionHandle:
        """Validate and transactionally restore one composition archive."""
        composition = CompositionHandle(self._host, self._service.load(Path(path)))
        if open_composition:
            composition.open()
        return composition

    def save_document(self, path: str | Path) -> tuple[CompositionHandle, ...]:
        """Atomically save every independent composition in the document."""
        snapshot = self.capture_document()
        self.write_document(snapshot, path)
        return tuple(
            CompositionHandle(self._host, composition_id)
            for composition_id in snapshot.composition_ids
        )

    def capture_document(self) -> DocumentPersistenceSnapshot:
        """Capture detached document authority without filesystem access."""
        archive = self._service.capture_document()
        return DocumentPersistenceSnapshot(archive.root_document_ids, archive)

    def write_document(
        self,
        snapshot: DocumentPersistenceSnapshot,
        path: str | Path,
    ) -> None:
        """Atomically write a detached document snapshot to ``path``."""
        if not isinstance(snapshot, DocumentPersistenceSnapshot):
            raise TypeError("snapshot must be a DocumentPersistenceSnapshot")
        self._service.write_document(snapshot._archive, Path(path))

    def load_document(
        self,
        path: str | Path,
        *,
        open_first: bool = True,
    ) -> tuple[CompositionHandle, ...]:
        """Transactionally restore all roots from one document archive."""
        compositions = tuple(
            CompositionHandle(self._host, composition_id)
            for composition_id in self._service.load_document(Path(path))
        )
        if open_first and compositions:
            compositions[0].open()
        return compositions
