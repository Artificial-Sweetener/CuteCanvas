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

"""Bind one editor widget lifetime to a document execution runtime."""

from __future__ import annotations

from threading import Lock

from PySide6.QtCore import QObject

from qpane.sdk.execution import ExecutionHandle, ExecutionRuntime, ExecutionScope

from .document_runtime import CanvasDocumentRuntime


class CanvasExecutionBinding:
    """Own one view scope and optionally its standalone document runtime."""

    def __init__(
        self,
        owner: QObject,
        *,
        document_runtime: CanvasDocumentRuntime,
        close_document_runtime: bool,
    ) -> None:
        """Create a receiver-safe view scope over ``document_runtime``."""
        self._document_runtime = document_runtime
        self._close_document_runtime = close_document_runtime
        self._scope = document_runtime.open_view_scope(owner)
        self._finalizers: set[ExecutionHandle[object, object]] = set()
        self._close_requested = False
        self._closed = False
        self._lock = Lock()

    @property
    def runtime(self) -> ExecutionRuntime:
        """Return the runtime shared by this canvas."""
        return self._document_runtime.execution_runtime

    @property
    def document_runtime(self) -> CanvasDocumentRuntime:
        """Return the document-lifetime execution binding."""
        return self._document_runtime

    @property
    def scope(self) -> ExecutionScope:
        """Return the root task scope for canvas-owned work."""
        return self._scope

    def defer_close_until(
        self,
        handle: ExecutionHandle[object, object],
    ) -> None:
        """Keep the canvas scope alive until one accepted finalizer settles."""
        with self._lock:
            if self._closed:
                return
            self._finalizers.add(handle)
        handle.add_done_callback(lambda _outcome: self._finalizer_settled(handle))

    def close(self) -> None:
        """Close after accepted finalizers drain without blocking the GUI."""
        with self._lock:
            if self._closed:
                return
            self._close_requested = True
            if self._finalizers:
                return
            self._closed = True
        self._finish_close()

    def _finalizer_settled(
        self,
        handle: ExecutionHandle[object, object],
    ) -> None:
        """Release one finalizer and finish a deferred close when ready."""
        with self._lock:
            self._finalizers.discard(handle)
            if self._closed or not self._close_requested or self._finalizers:
                return
            self._closed = True
        self._finish_close()

    def _finish_close(self) -> None:
        """Release the root scope and optional standalone runtime once."""
        self._scope.close(reason="cutecanvas_shutdown")
        if self._close_document_runtime:
            self._document_runtime.close()
