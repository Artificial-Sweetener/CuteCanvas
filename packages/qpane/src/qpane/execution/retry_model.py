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

"""Retry value objects and delay scheduling contracts."""

from __future__ import annotations

import hashlib
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

K = TypeVar("K")
P = TypeVar("P")


class RetrySchedulingError(RuntimeError):
    """Report that a retry delay could not be scheduled."""


@dataclass(frozen=True, slots=True)
class RetryContext(Generic[K]):
    """Describe one producer retry without retaining its payload."""

    operation: str
    key: K
    payload_size: int | None = None


@dataclass(frozen=True, slots=True)
class RetryPolicy(Generic[K]):
    """Compute bounded exponential delays and optional termination."""

    base_ms: int
    max_ms: int
    jitter_fraction: float = 0.25
    attempt_limit: int | None = None
    elapsed_limit_ms: int | None = None

    def __post_init__(self) -> None:
        """Validate retry bounds when the policy is constructed."""
        if self.base_ms <= 0 or self.max_ms <= 0:
            raise ValueError("retry delays must be positive")
        if self.max_ms < self.base_ms:
            raise ValueError("max_ms must be at least base_ms")

    def delay_ms(self, attempt: int, context: RetryContext[K]) -> int:
        """Return the deterministic delay for one retry attempt."""
        ordinal = max(1, int(attempt))
        base = min(self.max_ms, self.base_ms * (2 ** (ordinal - 1)))
        jitter_cap = min(
            self.base_ms,
            max(0, int(base * max(0.0, self.jitter_fraction))),
        )
        if jitter_cap == 0:
            return base
        digest = hashlib.sha1(
            f"{context.operation}|{context.key!r}|{ordinal}".encode()
        ).digest()
        jitter = random.Random(int.from_bytes(digest[:4], "big")).randint(
            0,
            jitter_cap,
        )
        return min(self.max_ms, base + jitter)

    def should_stop(self, attempt: int, elapsed_ms: float) -> bool:
        """Return whether the producer must abandon another retry."""
        if self.attempt_limit is not None and attempt > self.attempt_limit:
            return True
        return bool(
            self.elapsed_limit_ms is not None and elapsed_ms > self.elapsed_limit_ms
        )


class DelayHandle(Protocol):
    """Cancel one delayed callback."""

    def cancel(self) -> None:
        """Prevent callback delivery when it has not fired."""
        ...


class DelayScheduler(Protocol):
    """Schedule owner-context producer policy callbacks."""

    def schedule(self, delay_ms: int, callback: Callable[[], None]) -> DelayHandle:
        """Schedule ``callback`` once and return its cancellation handle."""
        ...


@dataclass(frozen=True, slots=True)
class RetryCategorySnapshot:
    """Summarize one retry producer for diagnostics."""

    active: int
    total_scheduled: int
    peak_active: int


@dataclass(frozen=True, slots=True)
class RetrySnapshot:
    """Expose retry producer metrics by operation."""

    categories: dict[str, RetryCategorySnapshot]
