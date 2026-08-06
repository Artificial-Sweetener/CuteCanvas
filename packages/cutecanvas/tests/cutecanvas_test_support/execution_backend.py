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

"""Public-only controllable execution backends for lifecycle tests."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Mapping

from qpane.sdk.execution import (
    BackendSubmission,
    ExecutionBackendCapabilities,
    ExecutionJob,
    ExecutionRejected,
    ExecutionRejectionReason,
    ExecutionRequirements,
    ExecutionResource,
    ExecutionRuntime,
    ExecutionScope,
)


class _ControllableSubmission(BackendSubmission):
    """Cancel one pending job through its test backend."""

    def __init__(
        self,
        backend: ControllableExecutionBackend,
        job: ExecutionJob,
    ) -> None:
        """Bind the accepted job to its backend."""
        self._backend = backend
        self._job = job

    def cancel(self, *, reason: str) -> bool:
        """Remove pending work and terminalize it."""
        return self._backend.cancel(self._job, reason=reason)


class _SettledSubmission(BackendSubmission):
    """Represent work activated before backend submission returned."""

    def cancel(self, *, reason: str) -> bool:
        """Report that synchronously activated work is no longer pending."""
        return False


class InlineExecutionBackend:
    """Activate public jobs synchronously for focused orchestration tests."""

    @property
    def capabilities(self) -> ExecutionBackendCapabilities:
        """Honor every execution requirement without retaining work."""
        return ExecutionBackendCapabilities(
            resources=frozenset(ExecutionResource),
            stable_affinity=True,
            exclusive_resources=True,
            adoption_held_leases=True,
        )

    def supports(self, requirements: ExecutionRequirements) -> bool:
        """Return whether the complete test capability set supports a request."""
        return self.capabilities.supports(requirements)

    def submit(self, job: ExecutionJob) -> BackendSubmission:
        """Activate one job before returning a settled submission."""
        job.run()
        return _SettledSubmission()


class ControllableExecutionBackend:
    """Queue public jobs until a test activates them explicitly."""

    def __init__(self) -> None:
        """Create an empty ordinary-resource backend."""
        self._pending: deque[ExecutionJob] = deque()
        self.submitted: list[ExecutionJob] = []
        self.cancelled: list[ExecutionJob] = []

    @property
    def capabilities(self) -> ExecutionBackendCapabilities:
        """Support ordinary QPane work without affinity requirements."""
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
        """Return whether the declared requirements are supported."""
        return self.capabilities.supports(requirements)

    def submit(self, job: ExecutionJob) -> BackendSubmission:
        """Retain one accepted job for deterministic activation."""
        self._pending.append(job)
        self.submitted.append(job)
        return _ControllableSubmission(self, job)

    @property
    def pending_count(self) -> int:
        """Return jobs not yet activated."""
        return len(self._pending)

    def pending_jobs(self) -> tuple[ExecutionJob, ...]:
        """Return accepted jobs in deterministic activation order."""
        return tuple(self._pending)

    def run_next(self) -> ExecutionJob:
        """Activate and return the oldest pending job."""
        job = self._pending.popleft()
        job.run()
        return job

    def run_operation(self, operation: str) -> ExecutionJob:
        """Activate the oldest pending job for one semantic operation."""
        job = next(item for item in self._pending if item.operation == operation)
        return self.run_job(job)

    def run_job(self, job: ExecutionJob) -> ExecutionJob:
        """Activate one retained job and remove it from the pending queue."""
        self._pending.remove(job)
        job.run()
        return job

    def run_all(self) -> None:
        """Activate every currently pending job."""
        while self._pending:
            self.run_next()

    def cancel(self, job: ExecutionJob, *, reason: str) -> bool:
        """Remove and terminalize ``job`` if it remains pending."""
        try:
            self._pending.remove(job)
        except ValueError:
            return False
        self.cancelled.append(job)
        return job.cancel_before_start(reason=reason)


class RejectingExecutionBackend(ControllableExecutionBackend):
    """Reject a configured number of otherwise supported submissions."""

    def __init__(
        self,
        rejection_count: int = 0,
        *,
        rejection_counts: Mapping[str, int] | None = None,
    ) -> None:
        """Configure deterministic global or operation-specific saturation."""
        super().__init__()
        self._rejection_count = max(0, int(rejection_count))
        self.rejections: list[ExecutionJob] = []
        self._rejection_counts = Counter(
            {
                operation: max(0, int(count))
                for operation, count in (rejection_counts or {}).items()
            }
        )

    def submit(self, job: ExecutionJob) -> BackendSubmission:
        """Reject until the configured count is exhausted."""
        operation = job.operation
        if self._rejection_count or self._rejection_counts[operation]:
            if self._rejection_counts[operation]:
                self._rejection_counts[operation] -= 1
            else:
                self._rejection_count -= 1
            self.rejections.append(job)
            raise ExecutionRejected(
                ExecutionRejectionReason.SATURATED,
                "test backend is saturated",
            )
        return super().submit(job)


class ControllableAffinityExecutionBackend(ControllableExecutionBackend):
    """Queue stable-affinity jobs for deterministic native-session tests."""

    @property
    def capabilities(self) -> ExecutionBackendCapabilities:
        """Advertise every hard requirement used by native sessions."""
        return ExecutionBackendCapabilities(
            resources=frozenset({ExecutionResource.THREAD_AFFINE_NATIVE}),
            stable_affinity=True,
            exclusive_resources=True,
            adoption_held_leases=True,
        )


class RejectingAffinityExecutionBackend(ControllableAffinityExecutionBackend):
    """Reject configured native operations before retaining later attempts."""

    def __init__(self, rejection_counts: Mapping[str, int]) -> None:
        """Configure operation-specific rejection counts."""
        super().__init__()
        self._rejection_counts = Counter(
            {
                operation: max(0, int(count))
                for operation, count in rejection_counts.items()
            }
        )

    def submit(self, job: ExecutionJob) -> BackendSubmission:
        """Reject configured attempts and queue later work."""
        if self._rejection_counts[job.operation]:
            self._rejection_counts[job.operation] -= 1
            raise ExecutionRejected(
                ExecutionRejectionReason.SATURATED,
                "test affinity backend is saturated",
            )
        return super().submit(job)


class ControlledExecution:
    """Own one public runtime whose queues tests can activate deterministically."""

    def __init__(
        self,
        *,
        rejection_counts: Mapping[str, int] | None = None,
        affinity_rejection_counts: Mapping[str, int] | None = None,
    ) -> None:
        """Create ordinary and affinity backends plus a root test scope."""
        self.backend = RejectingExecutionBackend(rejection_counts=rejection_counts)
        self.affinity_backend = RejectingAffinityExecutionBackend(
            affinity_rejection_counts or {}
        )
        self.runtime = ExecutionRuntime(
            self.backend,
            capability_backends=(self.affinity_backend,),
        )
        self.scope: ExecutionScope = self.runtime.open_scope(
            owner_id=f"test-execution:{id(self)}"
        )

    @property
    def pending_count(self) -> int:
        """Return all ordinary and affinity jobs awaiting activation."""
        return self.backend.pending_count + self.affinity_backend.pending_count

    @property
    def cancelled(self) -> tuple[ExecutionJob, ...]:
        """Return every job cancelled before activation."""
        return tuple(self.backend.cancelled + self.affinity_backend.cancelled)

    @property
    def rejections(self) -> tuple[ExecutionJob, ...]:
        """Return ordinary jobs rejected before runtime acceptance."""
        return tuple(self.backend.rejections)

    def pending_jobs(self) -> tuple[ExecutionJob, ...]:
        """Return pending jobs in backend-local acceptance order."""
        return self.backend.pending_jobs() + self.affinity_backend.pending_jobs()

    def run_operation(self, operation: str) -> ExecutionJob:
        """Activate one pending operation, accepting a semantic prefix."""
        for backend in (self.backend, self.affinity_backend):
            for job in backend.pending_jobs():
                if job.operation == operation or job.operation.startswith(
                    f"{operation}."
                ):
                    return backend.run_job(job)
        raise LookupError(f"no pending execution operation matches {operation!r}")

    def run_next(self) -> ExecutionJob:
        """Activate the oldest ordinary job, then the oldest affinity job."""
        if self.backend.pending_count:
            return self.backend.run_next()
        if self.affinity_backend.pending_count:
            return self.affinity_backend.run_next()
        raise LookupError("no execution jobs are pending")

    def run_job(self, job: ExecutionJob) -> ExecutionJob:
        """Activate one retained job through its owning backend."""
        for backend in (self.backend, self.affinity_backend):
            if job in backend.pending_jobs():
                return backend.run_job(job)
        raise LookupError("execution job is not pending")

    def run_all(self) -> None:
        """Activate all currently pending jobs, including follow-up work."""
        while self.pending_count:
            self.run_next()

    def close(self) -> None:
        """Cancel pending test work and close the test runtime."""
        self.runtime.shutdown(wait=False)


class TestExecution:
    """Provide either immediate or manually controlled public execution."""

    __test__ = False

    def __init__(self, *, auto_finish: bool = True) -> None:
        """Create one runtime and root scope for the selected timing model."""
        self.auto_finish = bool(auto_finish)
        self._controlled: ControlledExecution | None = None
        if self.auto_finish:
            self.backend: object = InlineExecutionBackend()
            self.runtime = ExecutionRuntime(self.backend)
            self.scope = self.runtime.open_scope(owner_id=f"test-execution:{id(self)}")
        else:
            controlled = ControlledExecution()
            self._controlled = controlled
            self.backend = controlled.backend
            self.runtime = controlled.runtime
            self.scope = controlled.scope

    @property
    def pending_count(self) -> int:
        """Return manually retained work, or zero for immediate execution."""
        return 0 if self._controlled is None else self._controlled.pending_count

    @property
    def cancelled(self) -> tuple[ExecutionJob, ...]:
        """Return pending jobs cancelled through the public lifecycle."""
        return () if self._controlled is None else self._controlled.cancelled

    def pending_jobs(self) -> tuple[ExecutionJob, ...]:
        """Return manually retained jobs in deterministic order."""
        return () if self._controlled is None else self._controlled.pending_jobs()

    def run_operation(self, operation: str) -> ExecutionJob:
        """Activate one manually retained semantic operation."""
        if self._controlled is None:
            raise LookupError("immediate execution has no pending jobs")
        return self._controlled.run_operation(operation)

    def run_job(self, job: ExecutionJob) -> ExecutionJob:
        """Activate one manually retained job."""
        if self._controlled is None:
            raise LookupError("immediate execution has no pending jobs")
        return self._controlled.run_job(job)

    def run_all(self) -> None:
        """Activate all manually retained jobs and follow-up work."""
        if self._controlled is not None:
            self._controlled.run_all()

    def close(self) -> None:
        """Close this test's runtime."""
        self.runtime.shutdown(wait=False)


__all__ = [
    "ControllableAffinityExecutionBackend",
    "ControllableExecutionBackend",
    "ControlledExecution",
    "InlineExecutionBackend",
    "RejectingAffinityExecutionBackend",
    "RejectingExecutionBackend",
    "TestExecution",
]
