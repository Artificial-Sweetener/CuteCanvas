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

from pathlib import Path

from ..persistence import CompositionPersistenceService
from .handles import CompositionHandle, EditorHandleHost


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
