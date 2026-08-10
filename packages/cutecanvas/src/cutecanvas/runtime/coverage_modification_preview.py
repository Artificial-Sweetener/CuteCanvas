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
"""Own the shared lifecycle for replaceable coverage-modification previews."""

from __future__ import annotations

import logging
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass

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

from cutecanvas.coverage import (
    CoverageEdgeModificationRequest,
    CoverageFilterCancelledError,
    CoverageSnapshot,
    build_coverage_edge_modification,
)
from cutecanvas.coverage.spatial_constraint import coverage_change_respects_constraint
from cutecanvas.types import LayerEdgeOperation

from .coverage_modification_contracts import (
    CoverageModificationPreviewResult,
    CoverageModificationPreviewTarget,
)
from .latest_requests import DocumentLatestRequestRegistry

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _CoverageModificationSession:
    """Retain one captured target and its replaceable latest generation."""

    session_id: uuid.UUID
    target: CoverageModificationPreviewTarget
    generation: int = 0
    request_id: uuid.UUID | None = None
    handle: ExecutionHandle[CoverageSnapshot | None, object] | None = None
    operation: LayerEdgeOperation | None = None
    product: CoverageSnapshot | None = None
    product_ready: bool = False
    settle_requested: bool = False


class CoverageModificationPreviewCoordinator:
    """Coordinate latest-only computation, preview, cancellation, and settlement."""

    def __init__(
        self,
        *,
        owner_id: str,
        execution_scope: ExecutionScope,
        latest_requests: DocumentLatestRequestRegistry,
        completed: Callable[[CoverageModificationPreviewResult], None],
    ) -> None:
        """Bind execution and latest-request ownership for one consumer family."""

        self._owner_id = owner_id
        self._execution_scope = execution_scope.open_child(
            f"{execution_scope.owner_id}:{owner_id}"
        )
        self._latest_requests = latest_requests
        self._completed = completed
        self._sessions: dict[uuid.UUID, _CoverageModificationSession] = {}
        self._closed = False

    def begin(self, target: CoverageModificationPreviewTarget) -> uuid.UUID | None:
        """Capture one target in a new nonmodal preview session."""

        if self._closed or target.coverage.bounds is None:
            return None
        session_id = uuid.uuid4()
        self._sessions[session_id] = _CoverageModificationSession(session_id, target)
        return session_id

    def update(
        self,
        session_id: uuid.UUID,
        operation: LayerEdgeOperation,
        radius: float,
    ) -> uuid.UUID | None:
        """Replace the latest product using the session's immutable target base."""

        session = self._sessions.get(session_id)
        if session is None or self._closed:
            return None
        normalized_operation = LayerEdgeOperation(operation)
        normalized_radius = _validated_radius(normalized_operation, radius)
        if not session.target.is_current():
            self._fail(session, "coverage target changed during filtering")
            return None
        session.generation += 1
        session.operation = normalized_operation
        session.product = None
        session.product_ready = False
        request_id = uuid.uuid4()
        session.request_id = request_id
        key = self._request_key(session_id)
        if not self._latest_requests.claim(
            key,
            request_id,
            lambda _message: self._cancel_work(session, request_id),
        ):
            return None
        product_request = session.target.build_request(
            normalized_operation,
            normalized_radius,
        )
        execution_request = ExecutionRequest[CoverageSnapshot | None, object](
            operation=f"editor.{self._owner_id}.{normalized_operation.value}",
            requirements=ExecutionRequirements(
                resource=ExecutionResource.NATIVE_CPU,
                urgency=ExecutionUrgency.FOREGROUND,
            ),
            work=lambda context: self._build_product(
                product_request,
                lambda: context.cancellation.is_cancelled,
            ),
        )
        try:
            handle = self._execution_scope.submit(
                execution_request,
                adopt=lambda product: self._adopt(session_id, request_id, product),
            )
        except ExecutionRejected as exc:
            self._latest_requests.release(key, request_id)
            self._fail(session, str(exc))
            return request_id
        if (
            self._sessions.get(session_id) is session
            and session.request_id == request_id
        ):
            session.handle = handle
        handle.add_done_callback(
            lambda outcome: self._settle_work(session_id, request_id, handle, outcome)
        )
        return request_id

    def settle(self, session_id: uuid.UUID) -> bool:
        """Commit after the current latest product becomes available."""

        session = self._sessions.get(session_id)
        if session is None or session.request_id is None:
            return False
        session.settle_requested = True
        if session.product_ready:
            self._commit(session)
        return True

    def cancel(
        self,
        session_id: uuid.UUID,
        *,
        reason: str = "preview cancelled",
        publish_pending: bool = False,
    ) -> bool:
        """Discard one session and optionally report its unresolved request."""

        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        request_id = session.request_id
        operation = session.operation
        self._cancel_work(session, request_id)
        session.target.discard(session_id)
        if publish_pending and request_id is not None and operation is not None:
            self._publish(session, request_id, operation, False, reason)
        return True

    def cancel_all(
        self,
        reason: str,
        *,
        publish_pending: bool = False,
    ) -> None:
        """Discard every session for replacement or owner shutdown."""

        for session_id in tuple(self._sessions):
            self.cancel(
                session_id,
                reason=reason,
                publish_pending=publish_pending,
            )

    def shutdown(self, reason: str) -> None:
        """Cancel unresolved sessions and close the owned execution scope."""

        if self._closed:
            return
        self._closed = True
        self.cancel_all(reason)
        self._execution_scope.close(reason=reason.replace(" ", "_"))

    @staticmethod
    def _build_product(
        request: CoverageEdgeModificationRequest,
        cancelled: Callable[[], bool],
    ) -> CoverageSnapshot | None:
        """Build detached coverage while preserving cooperative cancellation."""

        try:
            return build_coverage_edge_modification(request, cancelled=cancelled)
        except CoverageFilterCancelledError:
            if cancelled():
                raise
            raise RuntimeError("coverage filtering stopped unexpectedly") from None

    def _adopt(
        self,
        session_id: uuid.UUID,
        request_id: uuid.UUID,
        product: CoverageSnapshot | None,
    ) -> None:
        """Present the current product or commit it after Apply was requested."""

        session = self._sessions.get(session_id)
        if session is None or session.request_id != request_id:
            return
        key = self._request_key(session_id)
        if not self._latest_requests.is_current(key, request_id):
            return
        self._latest_requests.release(key, request_id)
        if not session.target.is_current():
            self._fail(session, "coverage target changed during filtering")
            return
        if not coverage_change_respects_constraint(
            session.target.coverage,
            product,
            session.target.spatial_constraint,
        ):
            self._fail(session, "coverage product escaped spatial constraint")
            return
        if not session.target.present(
            session_id,
            session.generation,
            product,
        ):
            self._fail(session, "coverage target rejected preview product")
            return
        session.product = product
        session.product_ready = True
        session.handle = None
        if session.settle_requested:
            self._commit(session)

    def _commit(self, session: _CoverageModificationSession) -> None:
        """Commit the current product once and release transient presentation."""

        request_id = session.request_id
        operation = session.operation
        if request_id is None or operation is None:
            return
        if not session.target.is_current():
            self._fail(session, "coverage target changed during filtering")
            return
        changed = session.target.commit(session.product)
        session.target.release(session.session_id)
        self._finish(
            session,
            request_id,
            operation,
            changed,
            "" if changed else "coverage modification produced no change",
        )

    def _fail(self, session: _CoverageModificationSession, message: str) -> None:
        """Discard a failed session and publish its current request."""

        request_id = session.request_id
        operation = session.operation
        self._sessions.pop(session.session_id, None)
        self._cancel_work(session, request_id)
        session.target.discard(session.session_id)
        if request_id is not None and operation is not None:
            self._publish(session, request_id, operation, False, message)

    def _finish(
        self,
        session: _CoverageModificationSession,
        request_id: uuid.UUID,
        operation: LayerEdgeOperation,
        succeeded: bool,
        message: str,
    ) -> None:
        """Release a terminal session and publish exactly one result."""

        self._sessions.pop(session.session_id, None)
        self._latest_requests.release(self._request_key(session.session_id), request_id)
        self._publish(session, request_id, operation, succeeded, message)

    def _cancel_work(
        self,
        session: _CoverageModificationSession,
        request_id: uuid.UUID | None,
    ) -> None:
        """Cancel only one addressed generation while retaining its session."""

        if request_id is None:
            return
        if session.handle is not None:
            session.handle.cancel(reason="replaced coverage preview request")
            session.handle = None
        self._latest_requests.release(self._request_key(session.session_id), request_id)

    def _settle_work(
        self,
        session_id: uuid.UUID,
        request_id: uuid.UUID,
        handle: ExecutionHandle[CoverageSnapshot | None, object],
        outcome: ExecutionOutcome[CoverageSnapshot | None],
    ) -> None:
        """Publish a current execution failure that never reached adoption."""

        if outcome.state == ExecutionState.SUCCEEDED:
            return
        session = self._sessions.get(session_id)
        if (
            session is None
            or session.request_id != request_id
            or (session.handle is not None and session.handle is not handle)
        ):
            return
        if outcome.error is not None:
            logger.error(
                "Coverage modification failed (request=%s, target=%s): %s",
                request_id,
                session.target.diagnostic_context(),
                outcome.error,
                exc_info=(
                    type(outcome.error),
                    outcome.error,
                    outcome.error.__traceback__,
                ),
            )
        message = (
            outcome.cancellation_reason
            if outcome.state == ExecutionState.CANCELLED
            else str(outcome.error)
        )
        self._fail(session, message or "coverage modification did not complete")

    def _publish(
        self,
        session: _CoverageModificationSession,
        request_id: uuid.UUID,
        operation: LayerEdgeOperation,
        succeeded: bool,
        message: str,
    ) -> None:
        """Publish one source-neutral terminal result."""

        self._completed(
            CoverageModificationPreviewResult(
                request_id,
                session.session_id,
                operation,
                succeeded,
                message,
                session.target,
            )
        )

    def _request_key(self, session_id: uuid.UUID) -> tuple[str, uuid.UUID]:
        """Return one latest-request key per owner and preview session."""

        return (self._owner_id, session_id)


def _validated_radius(operation: LayerEdgeOperation, radius: float) -> float:
    """Normalize finite positive values and whole-pixel edge offsets."""

    normalized = float(radius)
    if not math.isfinite(normalized) or normalized <= 0.0:
        raise ValueError("coverage modification radius must be finite and positive")
    if operation is not LayerEdgeOperation.FEATHER and int(normalized) != normalized:
        raise ValueError("coverage expansion and contraction require whole pixels")
    return normalized


__all__ = [
    "CoverageModificationPreviewCoordinator",
]
