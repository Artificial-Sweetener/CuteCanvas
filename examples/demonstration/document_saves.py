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
"""Teach detached CuteCanvas document persistence on a host-owned runtime."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cutecanvas import (
    CompositionPersistenceFacade,
    DocumentPersistenceSnapshot,
)
from PySide6.QtCore import QObject

from qpane import (
    ExecutionRejected,
    ExecutionRequest,
    ExecutionRequirements,
    ExecutionResource,
    ExecutionRuntime,
    ExecutionTaskContext,
    ExecutionUrgency,
    QtOwnerDispatcher,
)


@dataclass(frozen=True, slots=True)
class DocumentSaveResult:
    """Report one terminal detached archive write."""

    path: Path
    error: str | None = None


class DocumentSaveCoordinator(QObject):
    """Own bounded background document writes for the public demonstration."""

    def __init__(
        self,
        execution_runtime: ExecutionRuntime,
        persistence: CompositionPersistenceFacade,
        parent: QObject | None = None,
    ) -> None:
        """Bind one receiver-safe scope and the public persistence facade."""
        super().__init__(parent)
        self._persistence = persistence
        self._execution_scope = execution_runtime.open_scope(
            owner_id=f"cutecanvas-demo:document-saves:{id(self)}",
            dispatcher=QtOwnerDispatcher(self),
        )
        self._active_paths: set[Path] = set()

    def submit(
        self,
        snapshot: DocumentPersistenceSnapshot,
        path: Path,
        *,
        finished: Callable[[DocumentSaveResult], None],
    ) -> bool:
        """Write one stable capture unless its destination is already active."""
        destination = Path(path)
        if destination in self._active_paths:
            return False
        self._active_paths.add(destination)

        def write(_context: ExecutionTaskContext) -> DocumentSaveResult:
            """Persist detached authority without consulting live Qt state."""
            try:
                self._persistence.write_document(snapshot, destination)
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                return DocumentSaveResult(destination, str(error))
            return DocumentSaveResult(destination)

        try:
            self._execution_scope.submit(
                ExecutionRequest[DocumentSaveResult, object](
                    operation="demo.document.save",
                    work=write,
                    requirements=ExecutionRequirements(
                        resource=ExecutionResource.BLOCKING_IO,
                        urgency=ExecutionUrgency.FOREGROUND,
                        resource_id=str(destination),
                    ),
                    tags=(("path", str(destination)),),
                ),
                adopt=lambda result: self._settle(result, finished),
            )
        except ExecutionRejected as error:
            self._active_paths.discard(destination)
            finished(DocumentSaveResult(destination, str(error)))
            return False
        return True

    def close(self) -> None:
        """Cancel unsettled writes before the demo runtime closes."""
        self._active_paths.clear()
        self._execution_scope.close(reason="demo_document_saves_closed")

    def _settle(
        self,
        result: DocumentSaveResult,
        finished: Callable[[DocumentSaveResult], None],
    ) -> None:
        """Release one destination and publish its terminal owner-thread result."""
        self._active_paths.discard(result.path)
        finished(result)


__all__ = ["DocumentSaveCoordinator", "DocumentSaveResult"]
