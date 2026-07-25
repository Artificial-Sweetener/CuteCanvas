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
"""Run native-affine jobs on stable keyed worker threads."""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass
from threading import Condition, Event, Lock, Thread

from .backend import (
    BackendSubmission,
    ExecutionBackendCapabilities,
    ExecutionJob,
)
from .model import (
    ExecutionLeaseRelease,
    ExecutionRejected,
    ExecutionRejectionReason,
    ExecutionRequirements,
    ExecutionResource,
)


@dataclass(slots=True)
class _AffinityEntry:
    """Retain one pending affinity job."""

    job: ExecutionJob


class _AffinitySubmission(BackendSubmission):
    """Cancel one job through its affinity backend."""

    def __init__(self, backend: AffinityExecutionBackend, task_id: uuid.UUID) -> None:
        """Bind one accepted task."""

        self._backend = backend
        self._task_id = task_id

    def cancel(self, *, reason: str) -> bool:
        """Remove the task when still pending."""

        return self._backend._cancel_pending(self._task_id, reason=reason)


class _AffinityLane:
    """Own one stable worker thread and FIFO queue."""

    def __init__(
        self,
        backend: AffinityExecutionBackend,
        affinity_key: str,
    ) -> None:
        """Start the stable worker for one affinity identity."""

        self._backend = backend
        self._affinity_key = affinity_key
        self._pending: deque[_AffinityEntry] = deque()
        self._closed = False
        self._condition = Condition(Lock())
        self._thread = Thread(
            target=self._run,
            name=f"qpane-affinity-{affinity_key}",
            daemon=True,
        )
        self._thread.start()

    def submit(self, entry: _AffinityEntry) -> None:
        """Queue one accepted entry."""

        with self._condition:
            if self._closed:
                raise RuntimeError("affinity lane is closed")
            self._pending.append(entry)
            self._condition.notify()

    def cancel(self, task_id: uuid.UUID) -> _AffinityEntry | None:
        """Remove one pending entry."""

        with self._condition:
            entry = next(
                (item for item in self._pending if item.job.task_id == task_id),
                None,
            )
            if entry is not None:
                self._pending.remove(entry)
            return entry

    def shutdown(self, *, wait: bool) -> tuple[_AffinityEntry, ...]:
        """Close this lane and return work removed before activation."""

        with self._condition:
            if self._closed:
                pending: tuple[_AffinityEntry, ...] = ()
            else:
                self._closed = True
                pending = tuple(self._pending)
                self._pending.clear()
                self._condition.notify_all()
        if wait:
            self._thread.join()
        return pending

    def _run(self) -> None:
        """Run FIFO entries on this stable thread."""

        while True:
            with self._condition:
                while not self._pending and not self._closed:
                    self._condition.wait()
                if not self._pending:
                    return
                entry = self._pending.popleft()
            self._backend._run_entry(entry)


class AffinityExecutionBackend:
    """Provide stable thread identity and adoption-held exclusive leases."""

    def __init__(self, *, max_accepted: int = 32) -> None:
        """Create a lazy affinity lane registry."""

        if max_accepted <= 0:
            raise ValueError("max_accepted must be positive")
        self._max_accepted = max_accepted
        self._lanes: dict[str, _AffinityLane] = {}
        self._task_lanes: dict[uuid.UUID, _AffinityLane] = {}
        self._active_exclusive: set[str] = set()
        self._closed = False
        self._condition = Condition(Lock())

    @property
    def capabilities(self) -> ExecutionBackendCapabilities:
        """Return native-affinity capabilities."""

        return ExecutionBackendCapabilities(
            resources=frozenset({ExecutionResource.THREAD_AFFINE_NATIVE}),
            stable_affinity=True,
            exclusive_resources=True,
            adoption_held_leases=True,
        )

    def supports(self, requirements: ExecutionRequirements) -> bool:
        """Return whether this backend can honor the requirements."""

        return self.capabilities.supports(requirements)

    def submit(self, job: ExecutionJob) -> BackendSubmission:
        """Queue one job on its stable affinity lane."""

        affinity_key = job.requirements.affinity_key
        if affinity_key is None:
            raise ExecutionRejected(
                ExecutionRejectionReason.UNSUPPORTED_REQUIREMENTS,
                "affinity backend requires affinity_key",
            )
        with self._condition:
            if self._closed:
                raise ExecutionRejected(
                    ExecutionRejectionReason.BACKEND_UNAVAILABLE,
                    "affinity execution backend is closed",
                )
            if len(self._task_lanes) >= self._max_accepted:
                raise ExecutionRejected(
                    ExecutionRejectionReason.SATURATED,
                    "affinity execution accepted-task limit reached",
                )
            lane = self._lanes.get(affinity_key)
            if lane is None:
                lane = _AffinityLane(self, affinity_key)
                self._lanes[affinity_key] = lane
            self._task_lanes[job.task_id] = lane
            job.add_settled_callback(
                lambda task_id=job.task_id: self._release_task(task_id)
            )
        try:
            lane.submit(_AffinityEntry(job=job))
        except BaseException:
            with self._condition:
                self._task_lanes.pop(job.task_id, None)
            raise
        return _AffinitySubmission(self, job.task_id)

    def shutdown(self, *, wait: bool = False) -> None:
        """Cancel pending jobs and close every stable lane."""

        with self._condition:
            if self._closed:
                lanes: tuple[_AffinityLane, ...] = ()
            else:
                self._closed = True
                lanes = tuple(self._lanes.values())
                self._condition.notify_all()
        pending: list[_AffinityEntry] = []
        for lane in lanes:
            pending.extend(lane.shutdown(wait=False))
        for entry in pending:
            entry.job.cancel_before_start(reason="backend_shutdown")
        if wait:
            for lane in lanes:
                lane.shutdown(wait=True)

    def _run_entry(self, entry: _AffinityEntry) -> None:
        """Run one job while honoring cross-lane exclusivity."""

        job = entry.job
        exclusive_key = job.requirements.exclusive_key
        if exclusive_key is not None:
            self._acquire_exclusive(exclusive_key)
        settled = Event()
        if job.requirements.lease_release == ExecutionLeaseRelease.ADOPTION_FINISHED:
            job.add_settled_callback(settled.set)
        try:
            job.run()
            if (
                job.requirements.lease_release
                == ExecutionLeaseRelease.ADOPTION_FINISHED
            ):
                settled.wait()
        finally:
            if exclusive_key is not None:
                self._release_exclusive(exclusive_key)

    def _cancel_pending(self, task_id: uuid.UUID, *, reason: str) -> bool:
        """Remove pending work from its lane."""

        with self._condition:
            lane = self._task_lanes.get(task_id)
        if lane is None:
            return False
        entry = lane.cancel(task_id)
        if entry is None:
            return False
        return entry.job.cancel_before_start(reason=reason)

    def _release_task(self, task_id: uuid.UUID) -> None:
        """Release accepted-task accounting after settlement."""

        with self._condition:
            self._task_lanes.pop(task_id, None)
            self._condition.notify_all()

    def _acquire_exclusive(self, exclusive_key: str) -> None:
        """Wait on the affinity worker until a global lease is free."""

        with self._condition:
            while exclusive_key in self._active_exclusive:
                self._condition.wait()
            self._active_exclusive.add(exclusive_key)

    def _release_exclusive(self, exclusive_key: str) -> None:
        """Release a global native-resource lease."""

        with self._condition:
            self._active_exclusive.discard(exclusive_key)
            self._condition.notify_all()


__all__ = ["AffinityExecutionBackend"]
