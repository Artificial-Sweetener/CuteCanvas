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

"""Regression tests for xdist-safe abuse-harness timing."""

from __future__ import annotations

from tests.harness import timing


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
