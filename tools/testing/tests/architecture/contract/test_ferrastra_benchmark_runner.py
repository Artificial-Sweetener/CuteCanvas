#    QPane + CuteCanvas + Ferrastra - Native graphics architecture tooling
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
"""Prove deterministic benchmark policy parsing and acceptance behavior."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tools.ferrastra_benchmarks import (
    BenchmarkCase,
    BenchmarkPolicy,
    BenchmarkResult,
    load_policy,
    percentile,
    validate_result,
)


def test_manifest_loads_as_executable_positive_limits() -> None:
    """Keep the measured gate connected to the checked-in manifest."""
    policy = load_policy()

    assert policy.warmup_iterations == 25
    assert policy.sample_iterations == 200
    assert policy.p50_ms < policy.p95_ms < policy.p99_ms
    assert policy.thread_budget == 8
    assert policy.controlled_case == BenchmarkCase(
        "scale-50-percent",
        2048,
        2048,
        1024,
        1024,
        "clamp",
        "srgb_linear",
        536_870_912,
        268_435_456,
    )


def test_percentile_uses_nearest_rank_without_interpolation() -> None:
    """Keep percentile decisions stable across Python and platform versions."""
    samples = [9.0, 1.0, 5.0, 3.0]

    assert percentile(samples, 50) == pytest.approx(3.0)
    assert percentile(samples, 99) == pytest.approx(9.0)
    with pytest.raises(ValueError, match="must not be empty"):
        percentile([], 50)


def test_validation_reports_each_exceeded_contract() -> None:
    """Reject latency, memory, cancellation, and determinism regressions together."""
    case = BenchmarkCase("test", 1, 1, 1, 1, "clamp", "srgb_linear", 100, 100)
    policy = BenchmarkPolicy(1, 1, 10.0, 20.0, 30.0, 100, 5.0, 8, case)
    result = BenchmarkResult(11.0, 21.0, 31.0, 0.0, 101, 102, 6.0, False)

    assert validate_result(result, policy) == [
        "latency p50 11.000 ms exceeds 10.000 ms",
        "latency p95 21.000 ms exceeds 20.000 ms",
        "latency p99 31.000 ms exceeds 30.000 ms",
        "cancellation latency p99 6.000 ms exceeds 5.000 ms",
        "peak resident memory 101 bytes exceeds 100 bytes",
        "allocated memory 102 bytes exceeds 100 bytes",
        "throughput must be positive",
        "output differs across declared thread budgets",
    ]
    assert (
        validate_result(
            replace(
                result,
                latency_p50_ms=10.0,
                latency_p95_ms=20.0,
                latency_p99_ms=30.0,
                throughput_per_second=1.0,
                peak_resident_bytes=100,
                allocated_bytes=100,
                cancellation_latency_p99_ms=5.0,
                deterministic_across_thread_budgets=True,
            ),
            policy,
        )
        == []
    )
