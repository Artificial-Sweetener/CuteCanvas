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
"""Bind one editable document to ephemeral execution ownership."""

from __future__ import annotations

import uuid
from threading import Lock

from PySide6.QtCore import QObject, QSize, Signal

from qpane.sdk.execution import (
    DefaultExecutionPolicy,
    ExecutionLeaseRelease,
    ExecutionRequirements,
    ExecutionResource,
    ExecutionRuntime,
    ExecutionScope,
    QtOwnerDispatcher,
    create_default_execution_runtime,
    create_native_execution_runtime,
)

from ..document import CanvasDocument
from ..document.canvas_resampling import CanvasResamplingMode
from ..masks.live_preview_store import MaskLivePreviewStore
from .canvas_resampling import CanvasResamplingService
from .latest_requests import DocumentLatestRequestRegistry


class CanvasDocumentRuntime(QObject):
    """Own document-scoped work independently of any mounted canvas view."""

    canvasResamplingCompleted: Signal = Signal(object)
    """Emit one terminal whole-canvas resampling result."""

    def __init__(
        self,
        document: CanvasDocument,
        *,
        execution_runtime: ExecutionRuntime | None = None,
        execution_policy: DefaultExecutionPolicy | None = None,
    ) -> None:
        """Create an ephemeral runtime binding for ``document``.

        Args:
            document: Durable document whose operations use this binding.
            execution_runtime: Optional host-owned physical execution runtime.
            execution_policy: Policy for an internally created default runtime.

        Raises:
            ValueError: If policy is supplied with a host-owned runtime.
        """
        super().__init__()
        if execution_runtime is not None and execution_policy is not None:
            raise ValueError(
                "execution_policy cannot configure a host-owned execution_runtime"
            )
        self._document = document
        self._owns_execution_runtime = execution_runtime is None
        self._execution_runtime = (
            execution_runtime
            if execution_runtime is not None
            else create_default_execution_runtime(execution_policy)
        )
        self._scope = self._execution_runtime.open_scope(
            owner_id=f"cutecanvas-document:{document.document_id}",
            dispatcher=QtOwnerDispatcher(self),
        )
        self.__latest_requests = DocumentLatestRequestRegistry()
        self.__mask_live_previews = MaskLivePreviewStore()
        self.__canvas_resampling = CanvasResamplingService(
            document._canvas_resampling_owner,
            execution_scope=self._scope,
            latest_requests=self.__latest_requests,
            changed=document.events.layers_changed,
            completed=self.canvasResamplingCompleted.emit,
        )
        self._native_runtime: ExecutionRuntime | None = None
        self._native_scope: ExecutionScope | None = None
        self._native_lock = Lock()
        self._closed = False

    @property
    def document(self) -> CanvasDocument:
        """Return the durable document bound to this runtime."""
        return self._document

    @property
    def execution_runtime(self) -> ExecutionRuntime:
        """Return the host or standalone physical execution runtime."""
        return self._execution_runtime

    @property
    def execution_scope(self) -> ExecutionScope:
        """Return the document-lifetime scope used by mutation work."""
        return self._scope

    @property
    def _latest_request_registry(self) -> DocumentLatestRequestRegistry:
        """Return the package-owned document freshness registry."""
        return self.__latest_requests

    @property
    def _mask_live_preview_store(self) -> MaskLivePreviewStore:
        """Return document-scoped provisional mask presentation authority."""
        return self.__mask_live_previews

    def open_view_scope(self, owner: QObject) -> ExecutionScope:
        """Open a receiver-safe scope whose lifetime belongs to one view."""
        if self._closed:
            raise RuntimeError("canvas document runtime is closed")
        return self._execution_runtime.open_scope(
            owner_id=f"cutecanvas-view:{id(owner)}",
            dispatcher=QtOwnerDispatcher(owner),
        )

    def request_canvas_resampling(
        self,
        composition_id: uuid.UUID,
        size: QSize,
        *,
        mode: CanvasResamplingMode,
    ) -> uuid.UUID:
        """Begin replaceable whole-canvas resampling."""
        return self.__canvas_resampling.request(composition_id, size, mode=mode)

    def cancel_canvas_resampling(self, request_id: uuid.UUID) -> bool:
        """Cancel a pending whole-canvas resampling request."""
        return self.__canvas_resampling.cancel(request_id)

    def native_execution_scope(self) -> ExecutionScope:
        """Return document-owned execution for stable native-affinity requests."""
        requirements = ExecutionRequirements(
            resource=ExecutionResource.THREAD_AFFINE_NATIVE,
            affinity_key="cutecanvas-native-capability",
            exclusive_key="cutecanvas-native-capability",
            lease_release=ExecutionLeaseRelease.ADOPTION_FINISHED,
        )
        if self._execution_runtime.supports(requirements):
            return self._scope
        with self._native_lock:
            if self._closed:
                raise RuntimeError("canvas document runtime is closed")
            if self._native_scope is None:
                runtime = create_native_execution_runtime()
                self._native_runtime = runtime
                self._native_scope = runtime.open_scope(
                    owner_id=f"cutecanvas-document-native:{self._document.document_id}",
                    dispatcher=QtOwnerDispatcher(self),
                )
            return self._native_scope

    def close(self) -> None:
        """Cancel document work and release only internally owned execution."""
        if self._closed:
            return
        self._closed = True
        self.__canvas_resampling.close()
        self.__latest_requests.close()
        self.__mask_live_previews.clear()
        self._scope.close(reason="document_runtime_closed")
        with self._native_lock:
            native_scope = self._native_scope
            native_runtime = self._native_runtime
            self._native_scope = None
            self._native_runtime = None
        if native_scope is not None:
            native_scope.close(reason="document_runtime_closed")
        if native_runtime is not None:
            native_runtime.shutdown(wait=False)
        if self._owns_execution_runtime:
            self._execution_runtime.shutdown(wait=False)


__all__ = ["CanvasDocumentRuntime"]
