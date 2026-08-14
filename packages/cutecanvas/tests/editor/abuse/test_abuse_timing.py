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

"""Regression tests for xdist-safe abuse-harness timing."""

from __future__ import annotations

from cutecanvas_test_support.harness import timing


def test_xdist_clock_uses_thread_work_instead_of_wall_time(monkeypatch) -> None:
    """Parallel abuse timing must exclude other workers' scheduling delays."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "timing-proof")
    thread_samples = iter((2.0, 2.004))
    monkeypatch.setattr(timing, "thread_time", lambda: next(thread_samples))
    monkeypatch.setattr(
        timing,
        "perf_counter",
        lambda: (_ for _ in ()).throw(AssertionError("wall clock used under xdist")),
    )

    started = timing.interaction_clock()
    assert round((timing.interaction_clock() - started) * 1000.0, 3) == 4.0


def test_xdist_percentiles_batch_coarse_thread_cpu_samples(monkeypatch) -> None:
    """Parallel percentiles must retain strict per-sample work over short batches."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "timing-proof")

    assert timing.stable_latency_samples(
        [0.0, 31.25, 0.0, 31.25],
        parallel_batch_size=2,
    ) == (15.625, 15.625)


def test_tail_latency_uses_nearest_rank_after_contention_safe_batching(
    monkeypatch,
) -> None:
    """Tail timing must use the same xdist batching policy as strict samples."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "timing-proof")

    assert (
        timing.tail_interaction_latency_ms(
            [2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0],
            quantile=0.75,
            parallel_batch_size=2,
        )
        == 11.0
    )


def test_tail_sample_count_preserves_p99_after_hosted_batching(monkeypatch) -> None:
    """A hosted p99 proof must retain 100 samples instead of becoming a maximum."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "timing-proof")
    sample_count = timing.tail_latency_sample_count(quantile=0.99)
    latencies = [1.0] * (sample_count - 8) + [100.0] * 8

    assert sample_count == 800
    assert len(timing.stable_latency_samples(latencies)) == 100
    assert timing.tail_interaction_latency_ms(latencies, quantile=0.99) == 1.0

    insufficient_latencies = latencies[8:]
    assert len(timing.stable_latency_samples(insufficient_latencies)) == 99
    assert (
        timing.tail_interaction_latency_ms(
            insufficient_latencies,
            quantile=0.99,
        )
        == 100.0
    )
