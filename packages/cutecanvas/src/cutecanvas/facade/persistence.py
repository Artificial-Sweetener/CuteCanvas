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
"""Focused public document persistence over the archive service."""

from __future__ import annotations

from pathlib import Path

from ..persistence import CompositionPersistenceService
from .handles import DocumentHandle, EditorHandleHost


class DocumentPersistenceFacade:
    """Save and load complete editable documents through typed handles."""

    def __init__(
        self,
        host: EditorHandleHost,
        service: CompositionPersistenceService,
    ) -> None:
        """Bind handle resolution and the sole archive workflow owner."""
        self._host = host
        self._service = service

    def save(self, document: DocumentHandle, path: str | Path) -> None:
        """Atomically save ``document`` and all referenced editor resources."""
        self._service.save(document.id, Path(path))

    def load(self, path: str | Path, *, open_document: bool = True) -> DocumentHandle:
        """Validate and transactionally restore one complete document archive."""
        document = DocumentHandle(self._host, self._service.load(Path(path)))
        if open_document:
            document.open()
        return document
