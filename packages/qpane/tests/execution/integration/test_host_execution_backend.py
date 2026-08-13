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

"""Prove a bounded named-lane host using only QPane's public execution SDK."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event, Lock

import pytest

from qpane.sdk.execution import (
    BackendSubmission,
    ExecutionBackendCapabilities,
    ExecutionJob,
    ExecutionRejected,
    ExecutionRejectionReason,
    ExecutionRequest,
    ExecutionRequirements,
    ExecutionResource,
    ExecutionRuntime,
    ExecutionState,
    ExecutionUrgency,
)


@dataclass(frozen=True, slots=True)
class _LanePolicy:
    """Configure one host-owned physical lane."""

    workers: int
    capacity: int


class _LaneSubmission(BackendSubmission):
    """Cancel one pending host future without duplicating task lifecycle."""

    def __init__(
        self,
        future: Future[None],
        *,
        job: ExecutionJob,
        release: Callable[[], None],
    ) -> None:
        """Retain only physical cancellation and capacity release."""
        self._future = future
        self._job = job
        self._release = release

    def cancel(self, *, reason: str) -> bool:
        """Remove pending work and terminalize it through the public job."""
        if not self._future.cancel():
            return False
        cancelled = self._job.cancel_before_start(reason=reason)
        self._release()
        return cancelled


class NamedLaneHostBackend:
    """Map semantic requirements onto bounded application-owned lanes."""

    capabilities = ExecutionBackendCapabilities(
        resources=frozenset(
            {
                ExecutionResource.BLOCKING_IO,
                ExecutionResource.PYTHON_CPU,
                ExecutionResource.NATIVE_CPU,
                ExecutionResource.DEVICE,
            }
        )
    )

    def __init__(self) -> None:
        """Create two representative host lanes with finite admission."""
        policies = {
            "interactive": _LanePolicy(workers=1, capacity=1),
            "background-io": _LanePolicy(workers=1, capacity=2),
        }
        self._pools = {
            name: ThreadPoolExecutor(
                max_workers=policy.workers,
                thread_name_prefix=f"host-{name}",
            )
            for name, policy in policies.items()
        }
        self._capacities = {name: policy.capacity for name, policy in policies.items()}
        self._accepted = {name: 0 for name in policies}
        self._closed = False
        self._lock = Lock()
        self.admitted_lanes: list[str] = []

    def supports(self, requirements: ExecutionRequirements) -> bool:
        """Accept requirements the two physical lanes can honestly honor."""
        return self.capabilities.supports(requirements)

    def submit(self, job: ExecutionJob) -> BackendSubmission:
        """Admit once, schedule ``job.run`` once, or reject immediately."""
        lane = self._lane_for(job.requirements)
        with self._lock:
            if self._closed:
                raise ExecutionRejected(
                    ExecutionRejectionReason.BACKEND_UNAVAILABLE,
                    "host execution backend is closed",
                )
            if self._accepted[lane] >= self._capacities[lane]:
                raise ExecutionRejected(
                    ExecutionRejectionReason.SATURATED,
                    f"host lane {lane} is saturated",
                    details=(("lane", lane),),
                )
            self._accepted[lane] += 1
            self.admitted_lanes.append(lane)
        release = _ReleaseOnce(lambda: self._release(lane))

        def run() -> None:
            """Activate the QPane-owned job and return host capacity afterward."""
            try:
                job.run()
            finally:
                release()

        try:
            future = self._pools[lane].submit(run)
        except BaseException:
            release()
            raise
        return _LaneSubmission(future, job=job, release=release)

    def shutdown(self, *, wait: bool = False) -> None:
        """Stop host admission and release both physical pools."""
        with self._lock:
            self._closed = True
        for pool in self._pools.values():
            pool.shutdown(wait=wait, cancel_futures=False)

    def _lane_for(self, requirements: ExecutionRequirements) -> str:
        """Map semantic urgency and resources without QPane operation names."""
        if (
            requirements.urgency
            in {ExecutionUrgency.INTERACTIVE, ExecutionUrgency.FOREGROUND}
            or requirements.resource != ExecutionResource.BLOCKING_IO
        ):
            return "interactive"
        return "background-io"

    def _release(self, lane: str) -> None:
        """Return one admission slot to its host-owned lane."""
        with self._lock:
            self._accepted[lane] -= 1


class _ReleaseOnce:
    """Make a physical capacity release safe across cancel/run races."""

    def __init__(self, release: Callable[[], None]) -> None:
        """Store one release callback."""
        self._release = release
        self._released = False
        self._lock = Lock()

    def __call__(self) -> None:
        """Invoke the callback at most once."""
        with self._lock:
            if self._released:
                return
            self._released = True
        self._release()


def test_named_lane_host_shares_capacity_across_runtime_scopes() -> None:
    """Use one host admission owner across independent QPane consumers."""
    backend = NamedLaneHostBackend()
    runtime = ExecutionRuntime(backend)
    first_scope = runtime.open_scope(owner_id="first-view")
    second_scope = runtime.open_scope(owner_id="second-view")
    started = Event()
    release = Event()

    def occupy_lane(_context: object) -> str:
        """Hold the single interactive admission slot."""
        started.set()
        release.wait(timeout=5)
        return "first"

    first = first_scope.submit(
        ExecutionRequest(
            operation="viewer.visible_tile",
            work=occupy_lane,
            requirements=ExecutionRequirements(
                resource=ExecutionResource.NATIVE_CPU,
                urgency=ExecutionUrgency.INTERACTIVE,
            ),
        )
    )
    assert started.wait(timeout=2)
    with pytest.raises(ExecutionRejected) as raised:
        second_scope.submit(
            ExecutionRequest(
                operation="editor.preview",
                work=lambda _context: "second",
                requirements=ExecutionRequirements(
                    resource=ExecutionResource.NATIVE_CPU,
                    urgency=ExecutionUrgency.INTERACTIVE,
                ),
            )
        )
    assert raised.value.reason == ExecutionRejectionReason.SATURATED

    background = second_scope.submit(
        ExecutionRequest(
            operation="host.file.decode",
            work=lambda _context: "decoded",
            requirements=ExecutionRequirements(
                resource=ExecutionResource.BLOCKING_IO,
                urgency=ExecutionUrgency.BACKGROUND,
            ),
        )
    )
    _wait_terminal(background)
    release.set()
    _wait_terminal(first)

    assert first.state == ExecutionState.SUCCEEDED
    assert background.state == ExecutionState.SUCCEEDED
    assert backend.admitted_lanes == ["interactive", "background-io"]
    runtime.shutdown(wait=True)
    backend.shutdown(wait=True)


def _wait_terminal(handle: object) -> None:
    """Wait boundedly for a public execution handle to settle."""
    from time import monotonic, sleep

    deadline = monotonic() + 2
    while not handle.state.is_terminal and monotonic() < deadline:  # type: ignore[attr-defined]
        sleep(0.001)
    assert handle.state.is_terminal  # type: ignore[attr-defined]
