#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Stable clocks for latency assertions in the mounted abuse harness."""

from __future__ import annotations

import os
from time import perf_counter, thread_time


def interaction_clock() -> float:
    """Measure synchronous dispatch work without xdist scheduler contention."""
    if os.environ.get("PYTEST_XDIST_WORKER"):
        return thread_time()
    return perf_counter()


def absolute_latency_assertions_are_isolated() -> bool:
    """Return whether no parallel test workers can contend with wall-clock timing."""
    return not bool(os.environ.get("PYTEST_XDIST_WORKER"))


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
