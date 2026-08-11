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
"""Run bounded fair work on QPane-owned reusable threads."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from threading import Condition, Lock, Thread

from .backend import (
    BackendSubmission,
    ExecutionBackendCapabilities,
    ExecutionJob,
)
from .default_policy import DefaultExecutionPolicy, urgency_rank
from .diagnostics import (
    DiagnosticsHub,
    DiagnosticsSubscription,
    ExecutionSnapshot,
)
from .model import (
    ExecutionLeaseRelease,
    ExecutionRejected,
    ExecutionRejectionReason,
    ExecutionRequirements,
    ExecutionResource,
    ExecutionUrgency,
)


@dataclass(slots=True)
class _PendingJob:
    """Retain one admitted job until a worker activates it."""

    job: ExecutionJob
    sequence: int
    queued_at: float


class _DefaultSubmission(BackendSubmission):
    """Cancel one pending job through its owning backend."""

    def __init__(self, backend: DefaultExecutionBackend, task_id: uuid.UUID) -> None:
        """Bind cancellation to one task identity."""

        self._backend = backend
        self._task_id = task_id

    def cancel(self, *, reason: str) -> bool:
        """Remove pending work when it has not started."""

        return self._backend._cancel_pending(self._task_id, reason=reason)


class DefaultExecutionBackend:
    """Provide nonblocking bounded admission and aging-aware fair scheduling."""

    def __init__(
        self,
        policy: DefaultExecutionPolicy | None = None,
        *,
        thread_name_prefix: str = "qpane-execution",
    ) -> None:
        """Start the configured reusable worker threads."""

        if not thread_name_prefix.strip():
            raise ValueError("thread_name_prefix must not be blank")
        self._policy = policy or DefaultExecutionPolicy()
        self._pending: list[_PendingJob] = []
        self._accepted_bytes: dict[uuid.UUID, int] = {}
        self._running: dict[uuid.UUID, ExecutionRequirements] = {}
        self._active_resources: dict[tuple[ExecutionResource, str | None], int] = {}
        self._active_exclusive: set[str] = set()
        self._sequence = 0
        self._rejected = 0
        self._completed = 0
        self._cancelled_before_start = 0
        self._closed = False
        self._diagnostics = DiagnosticsHub[ExecutionSnapshot](
            thread_name=f"{thread_name_prefix}-diagnostics"
        )
        self._condition = Condition(Lock())
        self._threads = tuple(
            Thread(
                target=self._worker_loop,
                name=f"{thread_name_prefix}-{index + 1}",
                daemon=True,
            )
            for index in range(self._policy.max_workers)
        )
        for thread in self._threads:
            thread.start()

    @property
    def capabilities(self) -> ExecutionBackendCapabilities:
        """Return supported ordinary thread-pool capabilities."""

        return ExecutionBackendCapabilities(
            resources=frozenset(
                {
                    ExecutionResource.BLOCKING_IO,
                    ExecutionResource.PYTHON_CPU,
                    ExecutionResource.NATIVE_CPU,
                    ExecutionResource.DEVICE,
                }
            ),
            exclusive_resources=True,
            adoption_held_leases=True,
        )

    def supports(self, requirements: ExecutionRequirements) -> bool:
        """Return whether this backend can honor the requirements."""

        return self.capabilities.supports(requirements)

    def submit(self, job: ExecutionJob) -> BackendSubmission:
        """Admit one job without blocking or reject it structurally."""

        estimate = job.requirements.estimated_retained_bytes or 0
        with self._condition:
            if self._closed:
                raise ExecutionRejected(
                    ExecutionRejectionReason.BACKEND_UNAVAILABLE,
                    "default execution backend is closed",
                )
            if len(self._accepted_bytes) >= self._policy.max_accepted:
                self._rejected += 1
                self._notify_locked()
                raise ExecutionRejected(
                    ExecutionRejectionReason.SATURATED,
                    "default execution accepted-task limit reached",
                    details=(("limit", "accepted"),),
                )
            retained = sum(self._accepted_bytes.values())
            if retained + estimate > self._policy.max_retained_bytes:
                self._rejected += 1
                self._notify_locked()
                raise ExecutionRejected(
                    ExecutionRejectionReason.SATURATED,
                    "default execution retained-byte limit reached",
                    details=(("limit", "retained_bytes"),),
                )
            self._sequence += 1
            self._pending.append(
                _PendingJob(
                    job=job,
                    sequence=self._sequence,
                    queued_at=time.monotonic(),
                )
            )
            self._accepted_bytes[job.task_id] = estimate
            job.add_settled_callback(
                lambda task_id=job.task_id: self._release_accepted(task_id)
            )
            self._condition.notify()
            self._notify_locked()
        return _DefaultSubmission(self, job.task_id)

    def execution_snapshot(self) -> ExecutionSnapshot:
        """Return the current bounded scheduler snapshot."""

        with self._condition:
            return self._snapshot_locked()

    def subscribe_diagnostics(
        self,
        callback: Callable[[ExecutionSnapshot], None],
    ) -> DiagnosticsSubscription:
        """Observe state changes without replacing other observers."""

        return self._diagnostics.subscribe(callback)

    def shutdown(self, *, wait: bool = False) -> None:
        """Cancel pending jobs and stop workers after running work returns."""

        with self._condition:
            if self._closed:
                pending: tuple[_PendingJob, ...] = ()
            else:
                self._closed = True
                pending = tuple(self._pending)
                self._pending.clear()
                self._condition.notify_all()
                self._notify_locked()
        for entry in pending:
            if entry.job.cancel_before_start(reason="backend_shutdown"):
                with self._condition:
                    self._cancelled_before_start += 1
                    self._notify_locked()
        if wait:
            for thread in self._threads:
                thread.join()
        self._diagnostics.close(wait=wait)

    def _worker_loop(self) -> None:
        """Activate eligible jobs until backend shutdown."""

        while True:
            with self._condition:
                entry = self._take_next_locked()
                while entry is None:
                    if self._closed and not self._pending:
                        return
                    self._condition.wait()
                    entry = self._take_next_locked()
                self._mark_running_locked(entry.job)
                self._notify_locked()
            try:
                entry.job.run()
            finally:
                self._finish_running(entry.job)

    def _take_next_locked(self) -> _PendingJob | None:
        """Remove the best eligible pending job."""

        if not self._pending:
            return None
        now = time.monotonic()
        eligible = [
            entry for entry in self._pending if self._is_eligible_locked(entry.job)
        ]
        if not eligible:
            return None
        selected = min(
            eligible,
            key=lambda entry: (
                urgency_rank(entry.job.requirements.urgency)
                - int((now - entry.queued_at) / self._policy.aging_interval_seconds),
                entry.sequence,
            ),
        )
        self._pending.remove(selected)
        return selected

    def _is_eligible_locked(self, job: ExecutionJob) -> bool:
        """Return whether resource and exclusivity limits allow activation."""

        requirements = job.requirements
        if (
            requirements.urgency is not ExecutionUrgency.INTERACTIVE
            and self._noninteractive_running_count()
            >= self._policy.noninteractive_worker_limit
        ):
            return False
        if (
            requirements.exclusive_key is not None
            and requirements.exclusive_key in self._active_exclusive
        ):
            return False
        key = (requirements.resource, requirements.resource_id)
        active = self._active_resources.get(key, 0)
        limit = min(
            self._policy.resource_limit(requirements.resource),
            requirements.maximum_concurrency or self._policy.max_workers,
        )
        return active < limit

    def _mark_running_locked(self, job: ExecutionJob) -> None:
        """Reserve worker-visible resource capacity."""

        requirements = job.requirements
        self._running[job.task_id] = requirements
        key = (requirements.resource, requirements.resource_id)
        self._active_resources[key] = self._active_resources.get(key, 0) + 1
        if requirements.exclusive_key is not None:
            self._active_exclusive.add(requirements.exclusive_key)
            if requirements.lease_release == ExecutionLeaseRelease.ADOPTION_FINISHED:
                job.add_settled_callback(
                    lambda exclusive_key=requirements.exclusive_key: (
                        self._release_exclusive(exclusive_key)
                    )
                )

    def _finish_running(self, job: ExecutionJob) -> None:
        """Release worker capacity after computation returns."""

        requirements = job.requirements
        with self._condition:
            self._running.pop(job.task_id, None)
            key = (requirements.resource, requirements.resource_id)
            remaining = self._active_resources.get(key, 0) - 1
            if remaining > 0:
                self._active_resources[key] = remaining
            else:
                self._active_resources.pop(key, None)
            if (
                requirements.exclusive_key is not None
                and requirements.lease_release == ExecutionLeaseRelease.WORK_FINISHED
            ):
                self._active_exclusive.discard(requirements.exclusive_key)
            self._condition.notify_all()
            self._notify_locked()

    def _noninteractive_running_count(self) -> int:
        """Return active jobs that may not consume reserved input capacity."""

        return sum(
            requirements.urgency is not ExecutionUrgency.INTERACTIVE
            for requirements in self._running.values()
        )

    def _cancel_pending(self, task_id: uuid.UUID, *, reason: str) -> bool:
        """Remove and terminalize one pending task."""

        with self._condition:
            entry = next(
                (item for item in self._pending if item.job.task_id == task_id),
                None,
            )
            if entry is None:
                return False
            self._pending.remove(entry)
            self._condition.notify_all()
        cancelled = entry.job.cancel_before_start(reason=reason)
        if cancelled:
            with self._condition:
                self._cancelled_before_start += 1
                self._notify_locked()
        return cancelled

    def _release_accepted(self, task_id: uuid.UUID) -> None:
        """Release admission accounting after runtime settlement."""

        with self._condition:
            if task_id not in self._accepted_bytes:
                return
            self._accepted_bytes.pop(task_id)
            self._completed += 1
            self._condition.notify_all()
            self._notify_locked()

    def _release_exclusive(self, exclusive_key: str) -> None:
        """Release one adoption-held exclusive lease."""

        with self._condition:
            self._active_exclusive.discard(exclusive_key)
            self._condition.notify_all()
            self._notify_locked()

    def _snapshot_locked(self) -> ExecutionSnapshot:
        """Build a snapshot while the condition lock is held."""

        return ExecutionSnapshot(
            accepted=len(self._accepted_bytes),
            pending=len(self._pending),
            running=len(self._running),
            retained_bytes=sum(self._accepted_bytes.values()),
            rejected=self._rejected,
            completed=self._completed,
            cancelled_before_start=self._cancelled_before_start,
        )

    def _notify_locked(self) -> None:
        """Publish snapshots synchronously to lightweight observers."""

        self._diagnostics.publish(self._snapshot_locked())


__all__ = ["DefaultExecutionBackend"]
