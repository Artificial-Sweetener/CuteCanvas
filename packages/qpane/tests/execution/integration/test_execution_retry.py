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

"""Characterize bounded producer retries over the public execution lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from qpane.sdk.execution import (
    ExecutionRejected,
    ExecutionRejectionReason,
    ExecutionRequest,
    RetryContext,
    RetryController,
    RetryPolicy,
)
from qpane_test_support.execution_backend import TestExecution


@dataclass(slots=True)
class _ScheduledDelay:
    """Retain one deterministic delayed callback."""

    callback: Callable[[], None]
    cancelled: bool = False

    def cancel(self) -> None:
        """Prevent this callback from firing."""
        self.cancelled = True

    def fire(self) -> None:
        """Invoke this callback unless its owner cancelled it."""
        if not self.cancelled:
            self.callback()


class _ManualScheduler:
    """Capture retry delays without waiting for wall-clock time."""

    def __init__(self) -> None:
        """Create an empty delay queue."""
        self.delays: list[tuple[int, _ScheduledDelay]] = []

    def schedule(
        self,
        delay_ms: int,
        callback: Callable[[], None],
    ) -> _ScheduledDelay:
        """Retain one callback and its requested delay."""
        handle = _ScheduledDelay(callback)
        self.delays.append((delay_ms, handle))
        return handle


def test_retry_coalesces_latest_payload_and_resubmits_once() -> None:
    """Retain one key and merge payloads while physical admission is saturated."""
    execution = TestExecution()
    scheduler = _ManualScheduler()
    controller = RetryController[str, int, int, object](
        "visible-tile",
        RetryPolicy(base_ms=5, max_ms=20, jitter_fraction=0),
        scheduler,
    )
    attempts: list[tuple[int, int]] = []
    rejections: list[tuple[str, int, ExecutionRejectionReason]] = []

    def submit(payload: int, attempt: int):
        """Reject once, then enter the normal runtime lifecycle."""
        attempts.append((payload, attempt))
        if attempt == 0:
            raise ExecutionRejected(
                ExecutionRejectionReason.SATURATED,
                "host lane full",
            )
        return execution.scope.submit(
            ExecutionRequest(
                operation="visible-tile",
                work=lambda _context: payload,
            )
        )

    controller.submit_or_coalesce(
        "tile-1",
        2,
        submit=submit,
        rejected=lambda key, attempt, error: rejections.append(
            (key, attempt, error.reason)
        ),
        merge=lambda previous, current: previous + current,
    )
    controller.submit_or_coalesce(
        "tile-1",
        3,
        submit=submit,
        rejected=lambda key, attempt, error: rejections.append(
            (key, attempt, error.reason)
        ),
        merge=lambda previous, current: previous + current,
    )

    assert tuple(controller.pending_keys()) == ("tile-1",)
    assert len(scheduler.delays) == 1
    assert scheduler.delays[0][0] == 5
    scheduler.delays[0][1].fire()

    assert attempts == [(2, 0), (5, 1)]
    assert rejections == [("tile-1", 1, ExecutionRejectionReason.SATURATED)]
    assert not tuple(controller.pending_keys())
    snapshot = controller.snapshot().categories["visible-tile"]
    assert snapshot.total_scheduled == 1
    assert snapshot.peak_active == 1
    execution.close()


def test_retry_policy_is_deterministic_and_bounded() -> None:
    """Keep generic construction and retry bounds stable on supported Python."""
    policy = RetryPolicy[str](
        base_ms=10,
        max_ms=25,
        jitter_fraction=0.5,
        attempt_limit=3,
        elapsed_limit_ms=100,
    )
    context = RetryContext[str](operation="decode", key="same")

    assert policy.delay_ms(1, context) == policy.delay_ms(1, context)
    assert 10 <= policy.delay_ms(1, context) <= 15
    assert 20 <= policy.delay_ms(2, context) <= 25
    assert policy.delay_ms(20, context) == 25
    assert not policy.should_stop(3, 100)
    assert policy.should_stop(4, 100)
    assert policy.should_stop(1, 101)
