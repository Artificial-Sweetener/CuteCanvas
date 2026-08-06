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
"""Asynchronous execution and terminal results for canvas resampling."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QSize
from qpane.sdk.execution import (
    ExecutionHandle,
    ExecutionOutcome,
    ExecutionRejected,
    ExecutionRequest,
    ExecutionRequirements,
    ExecutionResource,
    ExecutionScope,
    ExecutionState,
    ExecutionUrgency,
)

from ..document.canvas_resampling import (
    CanvasResampleProduct,
    CanvasResamplingMode,
    CanvasResamplingOwner,
)
from .latest_requests import DocumentLatestRequestRegistry


class CanvasResamplingStatus(str, Enum):
    """Describe the terminal state of one canvas resampling request."""

    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    STALE = "stale"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CanvasResamplingResult:
    """Publish one normalized terminal canvas resampling result."""

    request_id: uuid.UUID
    composition_id: uuid.UUID
    target_size: QSize
    mode: CanvasResamplingMode
    status: CanvasResamplingStatus
    message: str = ""
    changed: bool = False

    def __post_init__(self) -> None:
        """Detach the mutable Qt size value."""
        object.__setattr__(self, "target_size", QSize(self.target_size))

    @property
    def succeeded(self) -> bool:
        """Return whether the request reached a successful terminal state."""
        return self.status is CanvasResamplingStatus.COMPLETED


@dataclass(slots=True)
class _PendingCanvasResampling:
    """Retain request metadata until exactly one terminal publication."""

    request_id: uuid.UUID
    composition_id: uuid.UUID
    target_size: QSize
    mode: CanvasResamplingMode
    handle: ExecutionHandle[CanvasResampleProduct, object] | None = None


class CanvasResamplingService:
    """Own replaceable document-scoped canvas resampling execution."""

    def __init__(
        self,
        owner: CanvasResamplingOwner,
        *,
        execution_scope: ExecutionScope,
        latest_requests: DocumentLatestRequestRegistry,
        changed: Callable[[uuid.UUID], None],
        completed: Callable[[CanvasResamplingResult], None],
    ) -> None:
        """Bind computation, freshness, publication, and document owners."""
        self._owner = owner
        self._scope = execution_scope.open_child(
            f"{execution_scope.owner_id}:canvas-resampling"
        )
        self._latest = latest_requests
        self._changed = changed
        self._completed = completed
        self._pending: dict[uuid.UUID, _PendingCanvasResampling] = {}
        self._closed = False

    def request(
        self,
        composition_id: uuid.UUID,
        size: QSize,
        *,
        mode: CanvasResamplingMode,
    ) -> uuid.UUID:
        """Capture current state and begin bounded worker-side resampling."""
        if self._closed:
            raise RuntimeError("canvas resampling service is closed")
        plan = self._owner.capture(composition_id, size, mode=mode)
        request_id = uuid.uuid4()
        pending = _PendingCanvasResampling(
            request_id,
            composition_id,
            QSize(plan.target_size),
            plan.mode,
        )
        self._pending[request_id] = pending
        key = self._request_key(composition_id)
        if not self._latest.claim(
            key,
            request_id,
            lambda reason: self._cancel(request_id, reason),
        ):
            self._pending.pop(request_id, None)
            raise RuntimeError("document runtime is closed")
        if plan.target_bounds == plan.before.bounds:
            self._pending.pop(request_id, None)
            self._latest.release(key, request_id)
            self._publish(
                pending,
                CanvasResamplingStatus.COMPLETED,
                "canvas already has the requested dimensions",
            )
            return request_id
        request = ExecutionRequest[CanvasResampleProduct, object](
            operation="editor.canvas.resample",
            requirements=ExecutionRequirements(
                resource=ExecutionResource.NATIVE_CPU,
                urgency=ExecutionUrgency.FOREGROUND,
                estimated_retained_bytes=plan.estimated_retained_bytes,
            ),
            work=lambda context: self._owner.build(plan, context.cancellation),
        )
        try:
            handle = self._scope.submit(
                request,
                adopt=lambda product: self._adopt(request_id, product),
            )
        except ExecutionRejected as exc:
            self._pending.pop(request_id, None)
            self._latest.release(key, request_id)
            self._publish(pending, CanvasResamplingStatus.REJECTED, str(exc))
            return request_id
        if self._pending.get(request_id) is pending:
            pending.handle = handle
        handle.add_done_callback(
            lambda outcome: self._settle(request_id, handle, outcome)
        )
        return request_id

    def cancel(self, request_id: uuid.UUID) -> bool:
        """Cancel a current request by public identity."""
        pending = self._pending.get(request_id)
        if pending is None:
            return False
        return self._latest.cancel_request(
            self._request_key(pending.composition_id),
            request_id,
            reason="cancelled by host",
        )

    def close(self) -> None:
        """Cancel pending work and suppress later adoption."""
        if self._closed:
            return
        self._closed = True
        for request_id in tuple(self._pending):
            self._cancel(request_id, "canvas resampling service closed")
        self._scope.close(reason="canvas_resampling_service_closed")

    def _adopt(self, request_id: uuid.UUID, product: CanvasResampleProduct) -> None:
        """Adopt one current revision-guarded product atomically."""
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        key = self._request_key(pending.composition_id)
        if not self._latest.is_current(key, request_id):
            self._publish(
                pending,
                CanvasResamplingStatus.STALE,
                "replaced by a newer canvas resampling request",
            )
            return
        self._latest.release(key, request_id)
        if not self._owner.commit(product):
            self._publish(
                pending,
                CanvasResamplingStatus.STALE,
                "canvas content changed while resampling was prepared",
            )
            return
        self._changed(pending.composition_id)
        self._publish(
            pending,
            CanvasResamplingStatus.COMPLETED,
            "",
            changed=True,
        )

    def _cancel(self, request_id: uuid.UUID, reason: str) -> None:
        """Cancel and publish one pending request exactly once."""
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        if pending.handle is not None:
            pending.handle.cancel(reason=reason)
        self._latest.release(self._request_key(pending.composition_id), request_id)
        self._publish(pending, CanvasResamplingStatus.CANCELLED, reason)

    def _settle(
        self,
        request_id: uuid.UUID,
        handle: ExecutionHandle[CanvasResampleProduct, object],
        outcome: ExecutionOutcome[CanvasResampleProduct],
    ) -> None:
        """Publish failed or externally cancelled execution outcomes."""
        if outcome.state is ExecutionState.SUCCEEDED:
            return
        pending = self._pending.get(request_id)
        if pending is None or (
            pending.handle is not None and pending.handle is not handle
        ):
            return
        self._pending.pop(request_id, None)
        self._latest.release(self._request_key(pending.composition_id), request_id)
        cancelled = outcome.state is ExecutionState.CANCELLED
        message = outcome.cancellation_reason if cancelled else str(outcome.error)
        self._publish(
            pending,
            (
                CanvasResamplingStatus.CANCELLED
                if cancelled
                else CanvasResamplingStatus.FAILED
            ),
            message or "canvas resampling did not complete",
        )

    def _publish(
        self,
        pending: _PendingCanvasResampling,
        status: CanvasResamplingStatus,
        message: str,
        *,
        changed: bool = False,
    ) -> None:
        """Emit one detached terminal result."""
        self._completed(
            CanvasResamplingResult(
                pending.request_id,
                pending.composition_id,
                pending.target_size,
                pending.mode,
                status,
                message,
                changed,
            )
        )

    @staticmethod
    def _request_key(composition_id: uuid.UUID) -> tuple[str, uuid.UUID]:
        """Return the document-global replacement key for one composition."""
        return ("canvas-resampling", composition_id)


__all__ = [
    "CanvasResamplingResult",
    "CanvasResamplingService",
    "CanvasResamplingStatus",
]
