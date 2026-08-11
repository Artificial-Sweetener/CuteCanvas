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
from ..persistence.codec import CompositionArchiveCodec
from .composition_handles import CompositionHandle
from .handles import EditorHandleHost


@dataclass(frozen=True, slots=True)
class DocumentPersistenceSnapshot:
    """Carry detached document authority prepared for background persistence."""

    composition_ids: tuple[uuid.UUID, ...]
    _archive: CompositionArchiveSnapshot = field(repr=False)


@dataclass(frozen=True, slots=True)
class PreparedDocumentRestore:
    """Carry a validated document archive prepared outside the GUI thread."""

    composition_ids: tuple[uuid.UUID, ...]
    _archive: CompositionArchiveSnapshot = field(repr=False)


def prepare_document_restore(path: str | Path) -> PreparedDocumentRestore:
    """Decode and validate a document archive without mutating a live editor."""

    archive = CompositionArchiveCodec().read(Path(path))
    return PreparedDocumentRestore(archive.root_document_ids, archive)


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
        return self.restore_document(
            prepare_document_restore(path),
            open_first=open_first,
        )

    def restore_document(
        self,
        prepared: PreparedDocumentRestore,
        *,
        open_first: bool = True,
    ) -> tuple[CompositionHandle, ...]:
        """Install one prepared document archive into the live editor."""

        if not isinstance(prepared, PreparedDocumentRestore):
            raise TypeError("prepared must be a PreparedDocumentRestore")
        compositions = tuple(
            CompositionHandle(self._host, composition_id)
            for composition_id in self._service.restore_document(prepared._archive)
        )
        if open_first and compositions:
            compositions[0].open()
        return compositions
