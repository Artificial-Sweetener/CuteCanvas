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

from qpane.concurrency import BackoffPolicy, RetryPolicy, TerminationPolicy


def test_backoff_is_monotonic_and_bounded():
    backoff = BackoffPolicy(50, 1000, jitter_pct=0.25)
    policy = RetryPolicy(backoff)
    delays = [policy.nextDelayMs(i) for i in range(1, 6)]
    assert delays[0] >= 50 and delays[-1] <= 1000
    assert all(d2 >= 50 for d2 in delays)


def test_deterministic_jitter_for_same_key():
    backoff = BackoffPolicy(50, 1000, jitter_pct=0.25)
    policy = RetryPolicy(backoff)
    ctx = type(
        "C",
        (),
        {
            "category": "tiles",
            "device": None,
            "key": ("a", 1),
            "payload_size": None,
        },
    )()
    series1 = [policy.nextDelayMs(i, ctx) for i in range(1, 5)]
    series2 = [policy.nextDelayMs(i, ctx) for i in range(1, 5)]
    assert series1 == series2
    # Different key should change the series
    ctx2 = type(
        "C2",
        (),
        {
            "category": "tiles",
            "device": None,
            "key": ("b", 1),
            "payload_size": None,
        },
    )()
    series3 = [policy.nextDelayMs(i, ctx2) for i in range(1, 5)]
    assert series3 != series1


def test_termination_by_attempt_cap():
    term = TerminationPolicy(attempt_cap=2)
    assert term.shouldGiveUp(3, started_at=0.0, now=0.0, context=None) is True
    assert term.shouldGiveUp(1, started_at=0.0, now=0.0, context=None) is False
