#    QPane - High-performance PySide6 image viewer
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
"""Own the accepted execution task state machine."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from threading import Lock
from typing import Generic, TypeVar, cast

from .backend import BackendSubmission, ExecutionJob
from .cancellation import CancellationToken
from .dispatch import CompletionDispatcher
from .model import (
    ExecutionFailurePhase,
    ExecutionOutcome,
    ExecutionRequest,
    ExecutionState,
    ExecutionTimings,
)
from .progress_channel import ProgressChannel
from .task_context import ExecutionTaskContext

logger = logging.getLogger(__name__)
TResult = TypeVar("TResult")
TProgress = TypeVar("TProgress")
DoneCallback = Callable[[ExecutionOutcome[TResult]], None]


class ExecutionHandle(Generic[TResult, TProgress]):
    """Control and observe one runtime-accepted task."""

    def __init__(
        self,
        *,
        request: ExecutionRequest[TResult, TProgress],
        dispatcher: CompletionDispatcher,
        adopt: Callable[[TResult], None] | None,
        progress: Callable[[TProgress], None] | None,
        released: Callable[[ExecutionHandle[TResult, TProgress]], None],
    ) -> None:
        """Create pending state before physical backend admission."""

        self._task_id = uuid.uuid4()
        self._request = request
        self._dispatcher = dispatcher
        self._adopt = adopt
        self._released = released
        self._token = CancellationToken()
        self._state = ExecutionState.PENDING
        self._outcome: ExecutionOutcome[TResult] | None = None
        self._submission: BackendSubmission | None = None
        self._job: ExecutionJob | None = None
        self._callbacks: list[DoneCallback[TResult]] = []
        self._adoption_started = False
        self._queued_at = time.monotonic()
        self._started_at: float | None = None
        self._work_finished_at: float | None = None
        self._progress_channel = ProgressChannel(
            dispatcher=dispatcher,
            observer=progress,
            operation=request.operation,
        )
        self._lock = Lock()

    @property
    def task_id(self) -> uuid.UUID:
        """Return immutable task identity."""

        return self._task_id

    @property
    def operation(self) -> str:
        """Return the diagnostic operation label."""

        return self._request.operation

    @property
    def state(self) -> ExecutionState:
        """Return the current lifecycle state."""

        with self._lock:
            return self._state

    @property
    def outcome(self) -> ExecutionOutcome[TResult] | None:
        """Return the terminal outcome when settled."""

        with self._lock:
            return self._outcome

    def cancel(self, *, reason: str) -> bool:
        """Request cancellation unless atomic adoption has begun."""

        if not reason.strip():
            raise ValueError("cancellation reason must not be blank")
        with self._lock:
            if self._state.is_terminal or self._adoption_started:
                return False
            first_request = self._token._cancel(reason)
            submission = self._submission
            awaiting_adoption = self._state == ExecutionState.DELIVERING
        self._progress_channel.close()
        if awaiting_adoption:
            self._settle_cancelled(reason)
        if submission is not None:
            try:
                submission.cancel(reason=reason)
            except Exception:
                logger.exception(
                    "Execution backend cancellation failed",
                    extra={
                        "task_id": str(self._task_id),
                        "operation": self.operation,
                    },
                )
        return first_request

    def add_done_callback(self, callback: DoneCallback[TResult]) -> None:
        """Observe settlement through the task's owner dispatcher."""

        with self._lock:
            outcome = self._outcome
            if outcome is None:
                self._callbacks.append(callback)
                return
        self._dispatch_observer(callback, outcome)

    def _bind_job(self, job: ExecutionJob) -> None:
        """Bind backend-visible job state before submission."""

        with self._lock:
            self._job = job

    def _bind_submission(self, submission: BackendSubmission) -> None:
        """Attach backend cancellation after successful admission."""

        with self._lock:
            self._submission = submission
            cancellation_reason = self._token.reason
        if cancellation_reason is not None:
            submission.cancel(reason=cancellation_reason)

    def _execute(self) -> None:
        """Run detached work and queue result adoption."""

        with self._lock:
            if self._state != ExecutionState.PENDING:
                return
            if self._token.is_cancelled:
                cancellation_reason = self._token.reason or "cancelled_before_start"
            else:
                cancellation_reason = None
                self._state = ExecutionState.RUNNING
                self._started_at = time.monotonic()
        if cancellation_reason is not None:
            self._settle_cancelled(cancellation_reason)
            return
        context = ExecutionTaskContext(
            cancellation=self._token,
            progress=self._progress_channel,
        )
        try:
            result = self._request.work(context)
        except BaseException as error:  # noqa: BLE001
            with self._lock:
                self._work_finished_at = time.monotonic()
                cancellation_reason = self._token.reason
            if cancellation_reason is not None:
                self._settle_cancelled(cancellation_reason)
            else:
                self._settle_failed(error, phase=ExecutionFailurePhase.WORK)
            return
        with self._lock:
            self._work_finished_at = time.monotonic()
            cancellation_reason = self._token.reason
            if cancellation_reason is None and self._state == ExecutionState.RUNNING:
                self._state = ExecutionState.DELIVERING
        if cancellation_reason is not None:
            self._settle_cancelled(cancellation_reason)
            return
        self._queue_adoption(result)

    def _cancel_before_start(self, reason: str) -> None:
        """Settle work a backend removed from its pending queue."""

        self._token._cancel(reason)
        self._progress_channel.close()
        self._settle_cancelled(reason)

    def _queue_adoption(self, result: TResult) -> None:
        """Deliver detached work to the owner context."""

        self._dispatcher.dispatch(
            lambda: self._adopt_result(result),
            discarded=lambda: self._settle_cancelled("delivery_discarded"),
            reason=f"{self.operation}:adopt",
        )

    def _adopt_result(self, result: TResult) -> None:
        """Apply one result atomically on the owner context."""

        with self._lock:
            if self._state != ExecutionState.DELIVERING:
                return
            cancellation_reason = self._token.reason
            if cancellation_reason is None:
                self._adoption_started = True
        if cancellation_reason is not None:
            self._settle_cancelled(cancellation_reason)
            return
        try:
            if self._adopt is not None:
                self._adopt(result)
        except BaseException as error:  # noqa: BLE001
            self._settle_failed(error, phase=ExecutionFailurePhase.ADOPTION)
            return
        self._settle_succeeded(result)

    def _settle_succeeded(self, result: TResult) -> None:
        """Publish one successful terminal outcome."""

        self._settle(
            state=ExecutionState.SUCCEEDED,
            result=result,
        )

    def _settle_failed(
        self,
        error: BaseException,
        *,
        phase: ExecutionFailurePhase,
    ) -> None:
        """Publish one failed terminal outcome."""

        self._settle(
            state=ExecutionState.FAILED,
            error=error,
            failure_phase=phase,
        )

    def _settle_cancelled(self, reason: str) -> None:
        """Publish one cancelled terminal outcome."""

        self._settle(
            state=ExecutionState.CANCELLED,
            cancellation_reason=reason,
        )

    def _settle(
        self,
        *,
        state: ExecutionState,
        result: TResult | None = None,
        error: BaseException | None = None,
        failure_phase: ExecutionFailurePhase | None = None,
        cancellation_reason: str | None = None,
    ) -> None:
        """Perform the single terminal transition and release ownership."""

        settled_at = time.monotonic()
        with self._lock:
            if self._state.is_terminal:
                return
            self._state = state
            timings = ExecutionTimings(
                queued_at=self._queued_at,
                started_at=self._started_at,
                work_finished_at=self._work_finished_at,
                settled_at=settled_at,
            )
            outcome = ExecutionOutcome(
                task_id=self._task_id,
                operation=self.operation,
                state=state,
                timings=timings,
                result=result,
                error=error,
                failure_phase=failure_phase,
                cancellation_reason=cancellation_reason,
            )
            self._outcome = outcome
            callbacks = tuple(self._callbacks)
            self._callbacks.clear()
            job = self._job
        self._progress_channel.close()
        if job is not None:
            job._mark_settled()
        self._released(self)
        for callback in callbacks:
            self._dispatch_observer(callback, outcome)

    def _dispatch_observer(
        self,
        callback: DoneCallback[TResult],
        outcome: ExecutionOutcome[TResult],
    ) -> None:
        """Deliver one contained terminal observer."""

        self._dispatcher.dispatch(
            lambda: self._invoke_observer(callback, outcome),
            discarded=lambda: None,
            reason=f"{self.operation}:observer",
        )

    def _invoke_observer(
        self,
        callback: DoneCallback[TResult],
        outcome: ExecutionOutcome[TResult],
    ) -> None:
        """Contain observer exceptions after outcome determination."""

        try:
            callback(outcome)
        except Exception:
            logger.exception(
                "Execution completion observer failed",
                extra={
                    "task_id": str(self._task_id),
                    "operation": self.operation,
                },
            )


def as_object_handle(
    handle: ExecutionHandle[TResult, TProgress],
) -> ExecutionHandle[object, object]:
    """Widen a handle for owner bookkeeping."""

    return cast(ExecutionHandle[object, object], handle)


__all__ = ["ExecutionHandle"]
