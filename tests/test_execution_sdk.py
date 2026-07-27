#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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
"""Characterize QPane's public host-neutral execution lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, Lock, get_ident

import pytest
from qpane.sdk.execution import (
    BackendSubmission,
    CompletionDispatcher,
    DefaultExecutionPolicy,
    ExecutionBackendCapabilities,
    ExecutionFailurePhase,
    ExecutionJob,
    ExecutionLeaseRelease,
    ExecutionRejected,
    ExecutionRejectionReason,
    ExecutionRequest,
    ExecutionRequirements,
    ExecutionResource,
    ExecutionRuntime,
    ExecutionSnapshot,
    ExecutionState,
    ExecutionUrgency,
    create_default_execution_runtime,
)


class _Submission(BackendSubmission):
    """Cancel one backend-owned pending job."""

    def __init__(self, cancel: Callable[[str], bool] | None = None) -> None:
        """Store an optional pending-cancellation callback."""

        self._cancel = cancel

    def cancel(self, *, reason: str) -> bool:
        """Delegate cancellation when configured."""

        if self._cancel is None:
            return False
        return self._cancel(reason)


class _InlineBackend:
    """Activate jobs immediately without importing QPane internals."""

    capabilities = ExecutionBackendCapabilities(
        resources=frozenset(ExecutionResource),
        stable_affinity=True,
        exclusive_resources=True,
        adoption_held_leases=True,
    )

    def supports(self, requirements: ExecutionRequirements) -> bool:
        """Return whether public capabilities accept the requirements."""

        return self.capabilities.supports(requirements)

    def submit(self, job: ExecutionJob) -> BackendSubmission:
        """Run one public job directly."""

        job.run()
        return _Submission()


class _QueuedBackend:
    """Retain accepted jobs until a test activates or removes them."""

    capabilities = ExecutionBackendCapabilities(
        resources=frozenset(ExecutionResource),
        stable_affinity=True,
        exclusive_resources=True,
        adoption_held_leases=True,
    )

    def __init__(self) -> None:
        """Create an empty pending registry."""

        self.jobs: list[ExecutionJob] = []
        self._lock = Lock()

    def supports(self, requirements: ExecutionRequirements) -> bool:
        """Return whether public capabilities accept the requirements."""

        return self.capabilities.supports(requirements)

    def submit(self, job: ExecutionJob) -> BackendSubmission:
        """Retain one public job."""

        with self._lock:
            self.jobs.append(job)

        def cancel(reason: str) -> bool:
            """Remove and account for pending work."""

            with self._lock:
                if job not in self.jobs:
                    return False
                self.jobs.remove(job)
            return job.cancel_before_start(reason=reason)

        return _Submission(cancel)

    def run_next(self) -> None:
        """Activate the oldest pending job."""

        with self._lock:
            job = self.jobs.pop(0)
        job.run()

    def abandon_all(self) -> None:
        """Account for backend shutdown of accepted pending jobs."""

        with self._lock:
            jobs = tuple(self.jobs)
            self.jobs.clear()
        for job in jobs:
            job.cancel_before_start(reason="backend_shutdown")


class _RejectingBackend(_InlineBackend):
    """Reject every request before acceptance."""

    def submit(self, job: ExecutionJob) -> BackendSubmission:
        """Reject without activating the public job."""

        _ = job
        raise ExecutionRejected(
            ExecutionRejectionReason.SATURATED,
            "test backend is saturated",
        )


class _BoundedQueuedBackend(_QueuedBackend):
    """Retain one accepted job and reject work until it settles."""

    def __init__(self) -> None:
        """Create one-slot backend admission."""

        super().__init__()
        self._accepted = 0

    def submit(self, job: ExecutionJob) -> BackendSubmission:
        """Accept one task or report temporary saturation."""

        with self._lock:
            if self._accepted:
                raise ExecutionRejected(
                    ExecutionRejectionReason.SATURATED,
                    "test backend is saturated",
                )
            self._accepted += 1
        job.add_settled_callback(self._release_accepted)
        return super().submit(job)

    def _release_accepted(self) -> None:
        """Release the single accepted slot after task settlement."""

        with self._lock:
            self._accepted -= 1


class _ManualDispatcher(CompletionDispatcher):
    """Retain owner callbacks for deterministic delivery races."""

    def __init__(self) -> None:
        """Create an empty packet list."""

        self.packets: list[tuple[Callable[[], None], Callable[[], None]]] = []

    def dispatch(
        self,
        callback: Callable[[], None],
        *,
        discarded: Callable[[], None],
        reason: str,
    ) -> None:
        """Retain one callback packet."""

        _ = reason
        self.packets.append((callback, discarded))

    def deliver_next(self) -> None:
        """Deliver the oldest packet."""

        callback, _discarded = self.packets.pop(0)
        callback()

    def discard_all(self) -> None:
        """Discard every queued packet."""

        packets = tuple(self.packets)
        self.packets.clear()
        for _callback, discarded in packets:
            discarded()


def test_inline_backend_completes_and_adopts_once() -> None:
    """Run and adopt a typed value through public contracts only."""

    runtime = ExecutionRuntime(_InlineBackend())
    scope = runtime.open_scope(owner_id="inline")
    adopted: list[int] = []

    handle = scope.submit(
        ExecutionRequest(operation="answer", work=lambda _context: 42),
        adopt=adopted.append,
    )

    assert handle.state == ExecutionState.SUCCEEDED
    assert handle.outcome is not None
    assert handle.outcome.result == 42
    assert adopted == [42]
    assert scope.pending_count == 0


def test_rejection_creates_no_accepted_handle_or_work() -> None:
    """Keep backend rejection distinct from terminal task outcomes."""

    runtime = ExecutionRuntime(_RejectingBackend())
    scope = runtime.open_scope(owner_id="reject")
    ran = False

    def work(_context: object) -> None:
        """Record invalid activation."""

        nonlocal ran
        ran = True

    with pytest.raises(ExecutionRejected) as raised:
        scope.submit(ExecutionRequest(operation="rejected", work=work))

    assert raised.value.reason == ExecutionRejectionReason.SATURATED
    assert not ran
    assert scope.pending_count == 0


def test_pending_cancellation_settles_exactly_once() -> None:
    """Terminalize a job removed before backend activation."""

    backend = _QueuedBackend()
    runtime = ExecutionRuntime(backend)
    scope = runtime.open_scope(owner_id="cancel")
    outcomes = []
    handle = scope.submit(
        ExecutionRequest(operation="pending", work=lambda _context: 1)
    )
    handle.add_done_callback(outcomes.append)

    assert handle.cancel(reason="superseded")
    assert not handle.cancel(reason="again")
    assert handle.state == ExecutionState.CANCELLED
    assert handle.outcome is not None
    assert handle.outcome.cancellation_reason == "superseded"
    assert outcomes == [handle.outcome]
    assert not backend.jobs


def test_backend_abandonment_cannot_strand_an_accepted_handle() -> None:
    """Settle pending work removed by backend shutdown."""

    backend = _QueuedBackend()
    runtime = ExecutionRuntime(backend)
    scope = runtime.open_scope(owner_id="abandon")
    handle = scope.submit(
        ExecutionRequest(operation="abandoned", work=lambda _context: 1)
    )

    backend.abandon_all()

    assert handle.state == ExecutionState.CANCELLED
    assert handle.outcome is not None
    assert handle.outcome.cancellation_reason == "backend_shutdown"
    assert scope.pending_count == 0


def test_scope_close_cancels_only_its_own_work() -> None:
    """Keep sibling scopes independent on one runtime."""

    backend = _QueuedBackend()
    runtime = ExecutionRuntime(backend)
    first = runtime.open_scope(owner_id="first")
    second = runtime.open_scope(owner_id="second")
    first_handle = first.submit(
        ExecutionRequest(operation="first", work=lambda _context: 1)
    )
    second_handle = second.submit(
        ExecutionRequest(operation="second", work=lambda _context: 2)
    )

    first.close(reason="owner_closed")
    backend.run_next()

    assert first_handle.state == ExecutionState.CANCELLED
    assert second_handle.state == ExecutionState.SUCCEEDED


def test_finalization_scope_outlives_originating_owner() -> None:
    """Allow accepted finalization after the originating owner closes."""

    backend = _QueuedBackend()
    runtime = ExecutionRuntime(backend)
    owner = runtime.open_scope(owner_id="owner")
    finalization = owner.open_finalization_scope(owner_id="owner:finalization")

    owner.close(reason="owner_closed")
    handle = finalization.submit(
        ExecutionRequest(operation="finalize", work=lambda _context: 7)
    )
    backend.run_next()

    assert handle.state == ExecutionState.SUCCEEDED
    assert handle.outcome is not None
    assert handle.outcome.result == 7
    finalization.close(reason="finalization_complete")


def test_runtime_shutdown_closes_finalization_scope() -> None:
    """Keep detached finalization bounded by the shared runtime lifetime."""

    runtime = ExecutionRuntime(_QueuedBackend())
    owner = runtime.open_scope(owner_id="owner")
    finalization = owner.open_finalization_scope(owner_id="owner:finalization")

    runtime.shutdown()

    assert owner.is_closed
    assert finalization.is_closed


def test_finalization_scope_defers_temporary_backend_saturation() -> None:
    """Retain cleanup until an accepted task releases backend capacity."""

    backend = _BoundedQueuedBackend()
    runtime = ExecutionRuntime(backend)
    owner = runtime.open_scope(owner_id="owner")
    finalization = owner.open_finalization_scope(owner_id="owner:finalization")
    blocker = owner.submit(
        ExecutionRequest(operation="blocker", work=lambda _context: 1)
    )
    cleanup = finalization.submit(
        ExecutionRequest(operation="cleanup", work=lambda _context: 2)
    )

    assert cleanup.state == ExecutionState.PENDING
    assert [job.operation for job in backend.jobs] == ["blocker"]

    backend.run_next()

    assert blocker.state == ExecutionState.SUCCEEDED
    assert [job.operation for job in backend.jobs] == ["cleanup"]
    backend.run_next()
    assert cleanup.state == ExecutionState.SUCCEEDED


def test_closing_finalization_scope_cancels_deferred_work() -> None:
    """Terminalize cleanup retained only by the runtime admission queue."""

    backend = _BoundedQueuedBackend()
    runtime = ExecutionRuntime(backend)
    owner = runtime.open_scope(owner_id="owner")
    finalization = owner.open_finalization_scope(owner_id="owner:finalization")
    owner.submit(ExecutionRequest(operation="blocker", work=lambda _context: 1))
    cleanup = finalization.submit(
        ExecutionRequest(operation="cleanup", work=lambda _context: 2)
    )

    finalization.close(reason="owner_abandoned_finalization")

    assert cleanup.state == ExecutionState.CANCELLED
    assert cleanup.outcome is not None
    assert cleanup.outcome.cancellation_reason == "owner_abandoned_finalization"


def test_worker_and_adopter_failures_report_their_phase() -> None:
    """Distinguish computation failure from atomic adoption failure."""

    runtime = ExecutionRuntime(_InlineBackend())
    scope = runtime.open_scope(owner_id="failures")

    def fail_work(_context: object) -> int:
        """Raise from worker computation."""

        raise ValueError("work")

    worker_handle = scope.submit(
        ExecutionRequest(operation="work_failure", work=fail_work)
    )
    adopter_handle = scope.submit(
        ExecutionRequest(operation="adopt_failure", work=lambda _context: 1),
        adopt=lambda _result: (_ for _ in ()).throw(RuntimeError("adopt")),
    )

    assert worker_handle.outcome is not None
    assert worker_handle.outcome.failure_phase == ExecutionFailurePhase.WORK
    assert adopter_handle.outcome is not None
    assert adopter_handle.outcome.failure_phase == ExecutionFailurePhase.ADOPTION


def test_progress_is_coalesced_and_cannot_overtake_terminal_adoption() -> None:
    """Bound pending progress while preserving terminal ordering."""

    dispatcher = _ManualDispatcher()
    runtime = ExecutionRuntime(_InlineBackend())
    scope = runtime.open_scope(owner_id="progress", dispatcher=dispatcher)
    progress: list[int] = []
    adopted: list[int] = []

    def work(context) -> int:
        """Publish a progress storm before returning."""

        for value in range(100):
            context.report_progress(value)
        return 100

    handle = scope.submit(
        ExecutionRequest(operation="progress", work=work),
        progress=progress.append,
        adopt=adopted.append,
    )

    assert handle.state == ExecutionState.DELIVERING
    assert len(dispatcher.packets) == 2
    dispatcher.deliver_next()
    assert progress == [99]
    dispatcher.deliver_next()
    assert handle.state == ExecutionState.SUCCEEDED
    assert adopted == [100]


def test_discarded_adoption_settles_cancelled() -> None:
    """Acknowledge owner destruction instead of stranding delivery."""

    dispatcher = _ManualDispatcher()
    runtime = ExecutionRuntime(_InlineBackend())
    scope = runtime.open_scope(owner_id="discard", dispatcher=dispatcher)
    handle = scope.submit(
        ExecutionRequest(operation="discard", work=lambda _context: 1)
    )

    dispatcher.discard_all()

    assert handle.state == ExecutionState.CANCELLED
    assert handle.outcome is not None
    assert handle.outcome.cancellation_reason == "delivery_discarded"


def test_cancelling_queued_adoption_settles_without_owner_dispatch() -> None:
    """Release runtime and native leases even when owner delivery is not pumped."""

    dispatcher = _ManualDispatcher()
    runtime = ExecutionRuntime(_InlineBackend())
    scope = runtime.open_scope(owner_id="cancel-delivery", dispatcher=dispatcher)
    adopted: list[int] = []
    handle = scope.submit(
        ExecutionRequest(operation="cancel-delivery", work=lambda _context: 1),
        adopt=adopted.append,
    )

    assert handle.state == ExecutionState.DELIVERING
    assert handle.cancel(reason="owner_shutdown")
    assert handle.state == ExecutionState.CANCELLED
    assert scope.pending_count == 0
    dispatcher.deliver_next()
    assert adopted == []


def test_default_backend_rejects_without_blocking_when_saturated() -> None:
    """Enforce a finite accepted-task budget."""

    runtime = create_default_execution_runtime(
        DefaultExecutionPolicy(max_workers=1, max_accepted=1)
    )
    scope = runtime.open_scope(owner_id="bounded")
    started = Event()
    release = Event()

    def blocking_work(_context: object) -> int:
        """Occupy the only accepted slot until released."""

        started.set()
        release.wait(timeout=5)
        return 1

    first = scope.submit(ExecutionRequest(operation="blocking", work=blocking_work))
    assert started.wait(timeout=2)
    with pytest.raises(ExecutionRejected) as raised:
        scope.submit(ExecutionRequest(operation="overflow", work=lambda _context: 2))
    assert raised.value.reason == ExecutionRejectionReason.SATURATED
    release.set()
    _wait_terminal(first)
    runtime.shutdown(wait=True)


def test_runtime_diagnostics_subscription_aggregates_backend_changes() -> None:
    """Publish backend changes without exposing backend-specific observers."""

    runtime = create_default_execution_runtime(DefaultExecutionPolicy(max_workers=1))
    scope = runtime.open_scope(owner_id="diagnostics")
    changed = Event()
    observed: list[tuple[ExecutionSnapshot, ...]] = []
    subscription = runtime.subscribe_diagnostics(
        lambda snapshots: (observed.append(snapshots), changed.set())
    )

    handle = scope.submit(ExecutionRequest(operation="observed", work=lambda _ctx: 7))

    _wait_terminal(handle)
    assert changed.wait(timeout=2)
    assert observed
    assert any(snapshot.completed >= 1 for snapshot in observed[-1])
    subscription.close()
    runtime.shutdown(wait=True)


def test_affinity_backend_preserves_thread_identity_and_adoption_lease() -> None:
    """Serialize one native key until owner adoption settles."""

    runtime = create_default_execution_runtime(DefaultExecutionPolicy(max_workers=1))
    dispatcher = _ManualDispatcher()
    scope = runtime.open_scope(owner_id="affinity", dispatcher=dispatcher)
    requirements = ExecutionRequirements(
        resource=ExecutionResource.THREAD_AFFINE_NATIVE,
        urgency=ExecutionUrgency.FOREGROUND,
        affinity_key="device:0",
        exclusive_key="device:0",
        lease_release=ExecutionLeaseRelease.ADOPTION_FINISHED,
    )
    worker_threads: list[int] = []
    second_started = Event()
    first = scope.submit(
        ExecutionRequest(
            operation="native_first",
            requirements=requirements,
            work=lambda _context: worker_threads.append(get_ident()),
        )
    )
    second = scope.submit(
        ExecutionRequest(
            operation="native_second",
            requirements=requirements,
            work=lambda _context: (
                worker_threads.append(get_ident()),
                second_started.set(),
            ),
        )
    )

    _wait_state(first, ExecutionState.DELIVERING)
    assert not second_started.wait(timeout=0.05)
    dispatcher.deliver_next()
    assert second_started.wait(timeout=2)
    _wait_state(second, ExecutionState.DELIVERING)
    dispatcher.deliver_next()
    assert worker_threads[0] == worker_threads[1]
    runtime.shutdown(wait=True)


def _wait_state(handle, state: ExecutionState) -> None:
    """Wait boundedly for one task state."""

    from time import monotonic, sleep

    deadline = monotonic() + 2
    while handle.state != state and monotonic() < deadline:
        sleep(0.001)
    assert handle.state == state


def _wait_terminal(handle) -> None:
    """Wait boundedly for terminal settlement."""

    from time import monotonic, sleep

    deadline = monotonic() + 2
    while not handle.state.is_terminal and monotonic() < deadline:
        sleep(0.001)
    assert handle.state.is_terminal
