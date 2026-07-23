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
    RetryController,
    RetryPolicy,
    RetrySchedulingError,
    TaskRejected,
)

from tests.helpers.executor_stubs import RetryTestScheduler


def _always_reject(*args, **kwargs):
    raise TaskRejected(
        "rej",
        category="tiles",
        device=None,
        limit_type="category",
        limit_value=1,
        pending_total=0,
        pending_category=0,
    )


def test_give_up_triggers_callback_and_stops():
    policy = RetryPolicy(BackoffPolicy(10, 10), termination=None)
    controller = RetryController("tiles", policy, scheduler=RetryTestScheduler())
    attempts = []
    abandoned = []

    def throttle(key, attempt, exc):
        attempts.append(attempt)

    def giveup(key, payload, attempt):
        abandoned.append((key, attempt))

    class _Cap:
        def nextDelayMs(self, attempt, context=None):
            return 10

        def shouldGiveUp(self, attempt, *, started_at, now, context=None):
            return attempt >= 1

    controller._policy = _Cap()  # type: ignore
    controller.queueOrCoalesce(
        ("img", 0),
        b"payload",
        submit=_always_reject,
        throttle=throttle,
        onGiveUp=giveup,
    )
    assert abandoned and abandoned[-1][1] == 1


def test_coalesce_replaces_payload_before_retry():
    sched = RetryTestScheduler()
    controller = RetryController(
        "tiles",
        RetryPolicy(BackoffPolicy(10, 1000, jitter_pct=0.0)),
        scheduler=sched,
    )
    seen = {"payloads": []}

    def submit(payload, attempt):
        if attempt == 0:
            raise TaskRejected(
                "rej",
                category="tiles",
                device=None,
                limit_type="category",
                limit_value=1,
                pending_total=0,
                pending_category=0,
            )
        seen["payloads"].append(payload)

    def coalesce(old, new):
        return old + new

    def throttle(key, attempt, exc):
        pass

    key = ("img", 1)
    controller.queueOrCoalesce(
        key, b"A", submit=submit, coalesce=coalesce, throttle=throttle
    )
    controller.queueOrCoalesce(
        key, b"B", submit=submit, coalesce=coalesce, throttle=throttle
    )
    assert len(list(controller.pendingKeys())) == 1
    sched.run_next()  # triggers retry submit with coalesced payload
    assert seen["payloads"] == [b"AB"]


def test_scheduler_failure_invokes_giveup_and_drops_entry():
    class _FailingScheduler:
        def schedule(self, key, delay_ms: int, callback):
            raise RetrySchedulingError("no main thread")

        def cancel(self, handle):
            pass

    throttle_attempts = []
    give_up_calls = []
    controller = RetryController(
        "tiles",
        RetryPolicy(BackoffPolicy(10, 10)),
        scheduler=_FailingScheduler(),
    )
    controller.queueOrCoalesce(
        ("img", 2),
        b"payload",
        submit=_always_reject,
        throttle=lambda key, attempt, exc: throttle_attempts.append(attempt),
        onGiveUp=lambda key, payload, attempt: give_up_calls.append((key, attempt)),
    )
    assert throttle_attempts == [1]
    assert give_up_calls == [(("img", 2), 1)]
    assert len(list(controller.pendingKeys())) == 0
    assert controller.totalScheduled == 0


def test_backoff_progression_and_throttle_attempts():
    sched = RetryTestScheduler()
    backoff = BackoffPolicy(50, 1000, jitter_pct=0.0)
    controller = RetryController("tiles", RetryPolicy(backoff), scheduler=sched)
    throttle_attempts = []

    def throttle(key, attempt, exc):
        throttle_attempts.append(attempt)

    def submit(payload, attempt):
        # Reject for first two attempts (initial and first retry)
        if attempt < 2:
            raise TaskRejected(
                "rej",
                category="tiles",
                device=None,
                limit_type="category",
                limit_value=1,
                pending_total=0,
                pending_category=0,
            )

    controller.queueOrCoalesce(("k", 0), b"p", submit=submit, throttle=throttle)
    # First schedule: attempt becomes 1, delay should be 50
    assert sched.scheduled and sched.scheduled[0].when_ms == 50
    sched.run_next()
    # Second schedule: attempt becomes 2, delay should be 100
    assert sched.scheduled and sched.scheduled[0].when_ms == 100
    assert throttle_attempts == [1, 2]


def test_cancel_and_cancelAll_stop_retries():
    sched = RetryTestScheduler()
    controller = RetryController(
        "tiles", RetryPolicy(BackoffPolicy(10, 100)), scheduler=sched
    )

    def submit(payload, attempt):
        raise TaskRejected(
            "rej",
            category="tiles",
            device=None,
            limit_type="category",
            limit_value=1,
            pending_total=0,
            pending_category=0,
        )

    controller.queueOrCoalesce(
        ("a", 0), b"1", submit=submit, throttle=lambda *args: None
    )
    controller.queueOrCoalesce(
        ("b", 0), b"2", submit=submit, throttle=lambda *args: None
    )
    assert len(list(controller.pendingKeys())) == 2
    controller.cancel(("a", 0))
    assert len(list(controller.pendingKeys())) == 1
    controller.cancelAll()
    assert len(list(controller.pendingKeys())) == 0
    # No pending retries should execute
    sched.run_all()


def test_peak_concurrent_pending_updates():
    sched = RetryTestScheduler()
    controller = RetryController(
        "tiles", RetryPolicy(BackoffPolicy(10, 100)), scheduler=sched
    )

    def submit_always_reject(*args, **kwargs):
        raise TaskRejected(
            "rej",
            category="tiles",
            device=None,
            limit_type="category",
            limit_value=1,
            pending_total=0,
            pending_category=0,
        )

    # Queue two distinct keys; both should schedule retries, peak should become 2
    controller.queueOrCoalesce(
        ("a", 0), b"1", submit=submit_always_reject, throttle=lambda *a: None
    )
    controller.queueOrCoalesce(
        ("b", 0), b"2", submit=submit_always_reject, throttle=lambda *a: None
    )
    snap = controller.snapshot()
    info = snap.categories.get("tiles")
    assert info is not None
    assert getattr(info, "peak_active", 0) == 2
    # Cancel one; peak must remain 2 even if active decreases
    controller.cancel(("a", 0))
    snap2 = controller.snapshot()
    info2 = snap2.categories.get("tiles")
    assert info2 is not None
    assert getattr(info2, "peak_active", 0) == 2
