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
"""Stable clocks for latency assertions in the mounted abuse harness."""

from __future__ import annotations

import os
from collections.abc import Callable
from math import ceil
from time import perf_counter, thread_time

import pytest

INTERACTIVE_PERFORMANCE = pytest.mark.interactive_performance


def interaction_clock() -> float:
    """Measure synchronous work without parallel or hosted scheduling delay."""
    if os.environ.get("PYTEST_XDIST_WORKER") or os.environ.get("CI"):
        return thread_time()
    return perf_counter()


def completion_clock() -> float:
    """Return a monotonic wall clock for bounded asynchronous waits."""
    return perf_counter()


def absolute_latency_assertions_are_isolated() -> bool:
    """Return whether wall-clock latency runs without shared or hosted contention."""
    return not bool(os.environ.get("PYTEST_XDIST_WORKER") or os.environ.get("CI"))


def average_interaction_latency_ms(
    operation: Callable[[], None],
    *,
    repetitions: int,
) -> float:
    """Measure repeated synchronous work with sub-tick per-operation precision."""
    count = int(repetitions)
    if count <= 0:
        raise ValueError("repetitions must be positive")
    started = interaction_clock()
    for _ in range(count):
        operation()
    return (interaction_clock() - started) * 1000.0 / count


def stable_latency_samples(
    latencies_ms: list[float],
    *,
    parallel_batch_size: int = 8,
) -> tuple[float, ...]:
    """Return raw isolated samples or quantization-resistant xdist CPU batches."""
    if absolute_latency_assertions_are_isolated():
        return tuple(latencies_ms)
    batch_size = max(1, int(parallel_batch_size))
    return tuple(
        sum(batch) / len(batch)
        for start in range(0, len(latencies_ms), batch_size)
        if (batch := latencies_ms[start : start + batch_size])
    )


def tail_interaction_latency_ms(
    latencies_ms: list[float],
    *,
    quantile: float = 0.9,
    parallel_batch_size: int = 8,
) -> float:
    """Return one nearest-rank tail sample under the shared timing policy."""
    if not latencies_ms:
        raise ValueError("latencies_ms must not be empty")
    if not 0.0 < quantile <= 1.0:
        raise ValueError("quantile must be in the interval (0, 1]")
    samples = sorted(
        stable_latency_samples(
            latencies_ms,
            parallel_batch_size=parallel_batch_size,
        )
    )
    return samples[min(len(samples) - 1, ceil(quantile * len(samples)) - 1)]
