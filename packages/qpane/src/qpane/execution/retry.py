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

"""Coalesced producer retries over structured execution rejection."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from time import monotonic
from typing import Generic, TypeVar

from .handle import ExecutionHandle
from .model import ExecutionRejected
from .retry_model import (
    DelayHandle,
    DelayScheduler,
    RetryCategorySnapshot,
    RetryContext,
    RetryPolicy,
    RetrySchedulingError,
    RetrySnapshot,
)

K = TypeVar("K")
P = TypeVar("P")
R = TypeVar("R")
A = TypeVar("A")

RetrySubmission = ExecutionHandle[R, A]


@dataclass(slots=True)
class _RetryEntry(Generic[K, P, R, A]):
    """Retain one coalesced retry request between attempts."""

    attempt: int
    payload: P
    delay: DelayHandle
    submit: Callable[[P, int], RetrySubmission[R, A]]
    merge: Callable[[P, P], P] | None
    rejected: Callable[[K, int, ExecutionRejected], None]
    started_at: float
    abandoned: Callable[[K, P, int], None] | None


class RetryController(Generic[K, P, R, A]):
    """Own retry/coalescing policy for one producer operation."""

    def __init__(
        self,
        operation: str,
        policy: RetryPolicy[K],
        scheduler: DelayScheduler,
    ) -> None:
        """Capture retry policy and its owner-context delay scheduler."""
        self._operation = operation
        self._policy = policy
        self._scheduler = scheduler
        self._entries: dict[K, _RetryEntry[K, P, R, A]] = {}
        self._total_scheduled = 0
        self._peak_active = 0

    def submit_or_coalesce(
        self,
        key: K,
        payload: P,
        *,
        submit: Callable[[P, int], RetrySubmission[R, A]],
        rejected: Callable[[K, int, ExecutionRejected], None],
        merge: Callable[[P, P], P] | None = None,
        abandoned: Callable[[K, P, int], None] | None = None,
    ) -> None:
        """Attempt submission immediately or retain one bounded retry."""
        existing = self._entries.get(key)
        if existing is not None:
            merger = merge or existing.merge
            existing.payload = (
                merger(existing.payload, payload) if merger is not None else payload
            )
            if merge is not None:
                existing.merge = merge
            if abandoned is not None:
                existing.abandoned = abandoned
            return
        self._attempt(
            key,
            payload,
            attempt=0,
            submit=submit,
            rejected=rejected,
            merge=merge,
            abandoned=abandoned,
            started_at=monotonic(),
        )

    def complete(self, key: K) -> None:
        """Forget retry state after terminal work completion."""
        self.cancel(key)

    def cancel(self, key: K) -> None:
        """Cancel one delayed retry and release its retained payload."""
        entry = self._entries.pop(key, None)
        if entry is not None:
            entry.delay.cancel()

    def cancel_all(self) -> None:
        """Cancel all delayed retries owned by this producer."""
        for key in tuple(self._entries):
            self.cancel(key)

    def pending_keys(self) -> Iterable[K]:
        """Return a stable snapshot of keys waiting for capacity."""
        return tuple(self._entries)

    def snapshot(self) -> RetrySnapshot:
        """Return retry metrics for diagnostics."""
        category = RetryCategorySnapshot(
            active=len(self._entries),
            total_scheduled=self._total_scheduled,
            peak_active=self._peak_active,
        )
        return RetrySnapshot(categories={self._operation: category})

    def _attempt(
        self,
        key: K,
        payload: P,
        *,
        attempt: int,
        submit: Callable[[P, int], RetrySubmission[R, A]],
        rejected: Callable[[K, int, ExecutionRejected], None],
        merge: Callable[[P, P], P] | None,
        abandoned: Callable[[K, P, int], None] | None,
        started_at: float,
    ) -> None:
        """Submit once and schedule only structured rejection."""
        rejection: ExecutionRejected
        try:
            submit(payload, attempt)
        except ExecutionRejected as caught:
            rejection = caught
        else:
            return
        next_attempt = max(1, attempt + 1)
        rejected(key, next_attempt, rejection)
        elapsed_ms = (monotonic() - started_at) * 1000.0
        if self._policy.should_stop(next_attempt, elapsed_ms):
            if abandoned is not None:
                abandoned(key, payload, next_attempt)
            return
        context = RetryContext(
            operation=self._operation,
            key=key,
            payload_size=_payload_size(payload),
        )

        def _retry() -> None:
            """Pop and resubmit the latest coalesced payload."""
            entry = self._entries.pop(key, None)
            if entry is None:
                return
            self._attempt(
                key,
                entry.payload,
                attempt=entry.attempt,
                submit=entry.submit,
                rejected=entry.rejected,
                merge=entry.merge,
                abandoned=entry.abandoned,
                started_at=entry.started_at,
            )

        try:
            delay = self._scheduler.schedule(
                self._policy.delay_ms(next_attempt, context),
                _retry,
            )
        except RetrySchedulingError:
            if abandoned is not None:
                abandoned(key, payload, next_attempt)
            return
        self._entries[key] = _RetryEntry(
            attempt=next_attempt,
            payload=payload,
            delay=delay,
            submit=submit,
            merge=merge,
            rejected=rejected,
            started_at=started_at,
            abandoned=abandoned,
        )
        self._total_scheduled += 1
        self._peak_active = max(self._peak_active, len(self._entries))


def _payload_size(payload: object) -> int | None:
    """Return an optional retained-byte estimate for retry diagnostics."""
    size_in_bytes = getattr(payload, "sizeInBytes", None)
    if callable(size_in_bytes):
        try:
            return max(0, int(size_in_bytes()))
        except (TypeError, ValueError):
            return None
    if isinstance(payload, (bytes, bytearray)):
        return len(payload)
    return None
