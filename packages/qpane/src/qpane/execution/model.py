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
"""Define immutable values shared by the public execution lifecycle."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, TypeVar

from .task_context import ExecutionTaskContext

TResult = TypeVar("TResult")
TProgress = TypeVar("TProgress")
ExecutionTagValue = Hashable | None


class ExecutionResource(str, Enum):
    """Describe the physical resource behavior of one operation."""

    BLOCKING_IO = "blocking_io"
    PYTHON_CPU = "python_cpu"
    NATIVE_CPU = "native_cpu"
    DEVICE = "device"
    THREAD_AFFINE_NATIVE = "thread_affine_native"


class ExecutionUrgency(str, Enum):
    """Describe how promptly useful work should begin."""

    INTERACTIVE = "interactive"
    FOREGROUND = "foreground"
    BACKGROUND = "background"
    OPPORTUNISTIC = "opportunistic"
    MAINTENANCE = "maintenance"


class ExecutionLeaseRelease(str, Enum):
    """Choose when a backend may release an exclusive resource lease."""

    WORK_FINISHED = "work_finished"
    ADOPTION_FINISHED = "adoption_finished"


class ExecutionState(str, Enum):
    """Describe one accepted task's lifecycle state."""

    PENDING = "pending"
    RUNNING = "running"
    DELIVERING = "delivering"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """Return whether this state cannot transition again."""

        return self in {
            ExecutionState.SUCCEEDED,
            ExecutionState.FAILED,
            ExecutionState.CANCELLED,
        }


class ExecutionFailurePhase(str, Enum):
    """Identify which authoritative phase raised a task failure."""

    WORK = "work"
    ADOPTION = "adoption"


class ExecutionRejectionReason(str, Enum):
    """Describe why a request was not accepted."""

    SATURATED = "saturated"
    UNSUPPORTED_REQUIREMENTS = "unsupported_requirements"
    SCOPE_CLOSED = "scope_closed"
    RUNTIME_CLOSED = "runtime_closed"
    BACKEND_UNAVAILABLE = "backend_unavailable"


@dataclass(frozen=True, slots=True)
class ExecutionRequirements:
    """Declare host-neutral scheduling and resource requirements."""

    resource: ExecutionResource = ExecutionResource.NATIVE_CPU
    urgency: ExecutionUrgency = ExecutionUrgency.BACKGROUND
    resource_id: str | None = None
    exclusive_key: str | None = None
    affinity_key: str | None = None
    maximum_concurrency: int | None = None
    lease_release: ExecutionLeaseRelease = ExecutionLeaseRelease.WORK_FINISHED
    estimated_retained_bytes: int | None = None

    def __post_init__(self) -> None:
        """Reject contradictory or unusable scheduling requirements."""

        _require_optional_label(self.resource_id, field_name="resource_id")
        _require_optional_label(self.exclusive_key, field_name="exclusive_key")
        _require_optional_label(self.affinity_key, field_name="affinity_key")
        if self.maximum_concurrency is not None and self.maximum_concurrency <= 0:
            raise ValueError("maximum_concurrency must be positive")
        if (
            self.estimated_retained_bytes is not None
            and self.estimated_retained_bytes < 0
        ):
            raise ValueError("estimated_retained_bytes must not be negative")
        if (
            self.resource == ExecutionResource.THREAD_AFFINE_NATIVE
            and self.affinity_key is None
        ):
            raise ValueError("thread-affine work requires affinity_key")
        if (
            self.lease_release == ExecutionLeaseRelease.ADOPTION_FINISHED
            and self.exclusive_key is None
        ):
            raise ValueError("adoption-held leases require exclusive_key")


ExecutionWork = Callable[[ExecutionTaskContext[TProgress]], TResult]


@dataclass(frozen=True, slots=True)
class ExecutionRequest(Generic[TResult, TProgress]):
    """Describe one detached unit of work for runtime submission."""

    operation: str
    work: ExecutionWork[TResult, TProgress]
    requirements: ExecutionRequirements = field(default_factory=ExecutionRequirements)
    tags: tuple[tuple[str, ExecutionTagValue], ...] = ()

    def __post_init__(self) -> None:
        """Validate diagnostic identity without interpreting domain policy."""

        _require_label(self.operation, field_name="operation")
        if not callable(self.work):
            raise TypeError("work must be callable")
        seen_names: set[str] = set()
        for name, _value in self.tags:
            _require_label(name, field_name="tag name")
            if name in seen_names:
                raise ValueError(f"duplicate execution tag: {name}")
            seen_names.add(name)


@dataclass(frozen=True, slots=True)
class ExecutionTimings:
    """Record monotonic timestamps for accepted task phases."""

    queued_at: float
    started_at: float | None = None
    work_finished_at: float | None = None
    settled_at: float | None = None

    @property
    def queue_delay_seconds(self) -> float | None:
        """Return time spent waiting for physical execution."""

        if self.started_at is None:
            return None
        return self.started_at - self.queued_at

    @property
    def work_duration_seconds(self) -> float | None:
        """Return worker execution duration."""

        if self.started_at is None or self.work_finished_at is None:
            return None
        return self.work_finished_at - self.started_at

    @property
    def adoption_delay_seconds(self) -> float | None:
        """Return time from work completion through settlement."""

        if self.work_finished_at is None or self.settled_at is None:
            return None
        return self.settled_at - self.work_finished_at


@dataclass(frozen=True, slots=True)
class ExecutionOutcome(Generic[TResult]):
    """Carry one terminal execution result without raising during observation."""

    task_id: uuid.UUID
    operation: str
    state: ExecutionState
    timings: ExecutionTimings
    result: TResult | None = None
    error: BaseException | None = None
    failure_phase: ExecutionFailurePhase | None = None
    cancellation_reason: str | None = None

    def __post_init__(self) -> None:
        """Reject ambiguous terminal outcome combinations."""

        if not self.state.is_terminal:
            raise ValueError("execution outcome state must be terminal")
        if self.state == ExecutionState.SUCCEEDED:
            if (
                self.error is not None
                or self.failure_phase is not None
                or self.cancellation_reason is not None
            ):
                raise ValueError("successful outcome contains failure state")
        elif self.state == ExecutionState.FAILED:
            if self.error is None or self.failure_phase is None:
                raise ValueError("failed outcome requires error and failure_phase")
            if self.result is not None or self.cancellation_reason is not None:
                raise ValueError("failed outcome contains result or cancellation")
        else:
            if self.result is not None or self.error is not None:
                raise ValueError("cancelled outcome contains result or error")
            _require_label(
                self.cancellation_reason,
                field_name="cancellation_reason",
            )


class ExecutionRejected(RuntimeError):
    """Report structured refusal before a runtime accepts work."""

    def __init__(
        self,
        reason: ExecutionRejectionReason,
        message: str,
        *,
        details: tuple[tuple[str, ExecutionTagValue], ...] = (),
    ) -> None:
        """Store stable rejection identity and safe diagnostic details."""

        _require_label(message, field_name="message")
        self.reason = reason
        self.details = details
        super().__init__(message)


def _require_optional_label(value: str | None, *, field_name: str) -> None:
    """Reject blank optional labels."""

    if value is not None:
        _require_label(value, field_name=field_name)


def _require_label(value: str | None, *, field_name: str) -> None:
    """Reject missing or blank labels."""

    if value is None or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


__all__ = [
    "ExecutionFailurePhase",
    "ExecutionLeaseRelease",
    "ExecutionOutcome",
    "ExecutionRejected",
    "ExecutionRejectionReason",
    "ExecutionRequest",
    "ExecutionRequirements",
    "ExecutionResource",
    "ExecutionState",
    "ExecutionTagValue",
    "ExecutionTimings",
    "ExecutionUrgency",
    "ExecutionWork",
]
