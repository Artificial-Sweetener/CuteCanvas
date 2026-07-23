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

from qpane.concurrency import (
    BackoffPolicy,
    RetryContext,
    RetryController,
    RetryPolicy,
    TaskRejected,
)

from tests.helpers.executor_stubs import RetryTestScheduler


def _reject_once_then_accept(state):
    def _submit(payload, attempt):
        if attempt == 0:
            raise TaskRejected(
                "rej",
                category="sam",
                device=None,
                limit_type="category",
                limit_value=1,
                pending_total=0,
                pending_category=0,
            )
        state["attempts"].append(attempt)

    return _submit


def _scheduled_delay(scheduler: RetryTestScheduler) -> int:
    assert scheduler.scheduled, "expected a scheduled retry"  # pragma: no cover - guard
    return scheduler.scheduled[-1].when_ms


def test_context_provider_sets_device_and_affects_jitter():
    backoff = BackoffPolicy(100, 1000, jitter_pct=0.25)
    # With device=cpu
    sched_cpu = RetryTestScheduler()
    controller_cpu = RetryController(
        "sam",
        RetryPolicy(backoff),
        scheduler=sched_cpu,
        contextProvider=lambda k, p: RetryContext("sam", "cpu", k, None),
    )
    attempts_cpu = {"attempts": []}
    controller_cpu.queueOrCoalesce(
        "k",
        b"p",
        submit=_reject_once_then_accept(attempts_cpu),
        throttle=lambda *a: None,
    )
    delay_cpu = _scheduled_delay(sched_cpu)
    # With device=cuda
    sched_cuda = RetryTestScheduler()
    controller_cuda = RetryController(
        "sam",
        RetryPolicy(backoff),
        scheduler=sched_cuda,
        contextProvider=lambda k, p: RetryContext("sam", "cuda", k, None),
    )
    attempts_cuda = {"attempts": []}
    controller_cuda.queueOrCoalesce(
        "k",
        b"p",
        submit=_reject_once_then_accept(attempts_cuda),
        throttle=lambda *a: None,
    )
    delay_cuda = _scheduled_delay(sched_cuda)
    assert (
        delay_cpu != delay_cuda
    )  # different device produces different deterministic jitter


def test_default_context_preserved_when_provider_none():
    backoff = BackoffPolicy(80, 1000, jitter_pct=0.0)  # no jitter for determinism
    # Baseline without provider
    sched1 = RetryTestScheduler()
    c1 = RetryController("tiles", RetryPolicy(backoff), scheduler=sched1)
    c1.queueOrCoalesce(
        "k",
        b"p",
        submit=lambda p, a: (_ for _ in ()).throw(
            TaskRejected(
                "rej",
                category="tiles",
                device=None,
                limit_type="category",
                limit_value=1,
                pending_total=0,
                pending_category=0,
            )
        ),
        throttle=lambda *a: None,
    )
    d1 = _scheduled_delay(sched1)
    # With provider that returns equivalent context (device=None)
    sched2 = RetryTestScheduler()
    c2 = RetryController(
        "tiles",
        RetryPolicy(backoff),
        scheduler=sched2,
        contextProvider=lambda k, p: RetryContext(
            "tiles",
            None,
            k,
            len(p) if isinstance(p, (bytes, bytearray)) else None,
        ),
    )
    c2.queueOrCoalesce(
        "k",
        b"p",
        submit=lambda p, a: (_ for _ in ()).throw(
            TaskRejected(
                "rej",
                category="tiles",
                device=None,
                limit_type="category",
                limit_value=1,
                pending_total=0,
                pending_category=0,
            )
        ),
        throttle=lambda *a: None,
    )
    d2 = _scheduled_delay(sched2)
    assert d1 == d2
