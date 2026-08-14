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
"""Measure the controlled Ferrastra Lanczos3 performance contract."""

from __future__ import annotations

import ctypes
import importlib
import json
import math
import os
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, cast

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 only
    import tomli as tomllib

from ferrastra import (
    CancellationToken,
    CompiledGraph,
    Engine,
    EvaluationBudget,
    EvaluationError,
    GraphBuilder,
    RasterResult,
    Region,
)

if __package__:
    from .check_ferrastra_benchmarks import validate_manifest
else:
    from check_ferrastra_benchmarks import validate_manifest

_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST = _ROOT / "benchmarks/ferrastra_manifest.toml"
_OPERATION = "ferrastra.resample.lanczos3"


@dataclass(frozen=True)
class BenchmarkCase:
    """Own the exact workload and execution budgets measured by the gate."""

    identifier: str
    source_width: int
    source_height: int
    destination_width: int
    destination_height: int
    edge_mode: str
    working_space: str
    memory_budget_bytes: int
    scratch_budget_bytes: int


@dataclass(frozen=True)
class BenchmarkPolicy:
    """Own executable sample counts and acceptance limits for one operation."""

    warmup_iterations: int
    sample_iterations: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    memory_ceiling_bytes: int
    cancellation_latency_ms: float
    thread_budget: int
    controlled_case: BenchmarkCase


class _ResourceUsage(Protocol):
    """Describe the resident-memory field returned by the resource module."""

    ru_maxrss: int


class _ResourceModule(Protocol):
    """Describe the portable subset of the resource module used here."""

    RUSAGE_SELF: int

    def getrusage(self, who: int) -> _ResourceUsage:
        """Return usage statistics for the requested process scope."""
        ...


@dataclass(frozen=True)
class BenchmarkResult:
    """Record measured latency, throughput, memory, cancellation, and identity."""

    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    throughput_per_second: float
    peak_resident_bytes: int
    allocated_bytes: int
    cancellation_latency_p99_ms: float
    deterministic_across_thread_budgets: bool


@dataclass(frozen=True)
class ResizeSession:
    """Retain one immutable source graph for repeated controlled evaluation."""

    engine: Engine
    compiled: CompiledGraph
    region: Region

    def evaluate(self, budget: EvaluationBudget) -> RasterResult:
        """Evaluate the canonical viewport case under one caller budget."""
        result = self.engine.evaluate(self.compiled, "result", self.region, budget)
        if not isinstance(result, RasterResult):
            raise TypeError("raster benchmark graph published a coverage product")
        return result


def percentile(samples: Sequence[float], requested: int) -> float:
    """Return the deterministic nearest-rank percentile for nonempty samples."""
    if not samples:
        raise ValueError("percentile samples must not be empty")
    if requested < 1 or requested > 100:
        raise ValueError("percentile must be between 1 and 100")
    ordered = sorted(samples)
    rank = math.ceil((requested / 100.0) * len(ordered))
    return ordered[rank - 1]


def load_policy(path: Path = _MANIFEST) -> BenchmarkPolicy:
    """Load the executable Lanczos3 limits from the validated manifest."""
    errors = validate_manifest(path)
    if errors:
        raise ValueError("; ".join(errors))
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    measurement = cast(Mapping[str, object], data["measurement"])
    registration = cast(Mapping[str, object], data["registration"])
    operations = cast(list[object], registration["operations"])
    operation: Mapping[str, object] | None = None
    for candidate in operations:
        if not isinstance(candidate, dict):
            continue
        record = cast(dict[str, object], candidate)
        if record.get("semantic_id") == _OPERATION:
            operation = record
            break
    if operation is None:
        raise ValueError(f"manifest does not register {_OPERATION}")
    thresholds = cast(Mapping[str, object], operation["latency_thresholds_ms"])
    controlled = cast(Mapping[str, object], operation["controlled_case"])
    return BenchmarkPolicy(
        warmup_iterations=_positive_integer(measurement["warmup_iterations"]),
        sample_iterations=_positive_integer(measurement["sample_iterations"]),
        p50_ms=_positive_float(thresholds["p50"]),
        p95_ms=_positive_float(thresholds["p95"]),
        p99_ms=_positive_float(thresholds["p99"]),
        memory_ceiling_bytes=_positive_integer(operation["memory_ceiling_bytes"]),
        cancellation_latency_ms=_positive_float(operation["cancellation_latency_ms"]),
        thread_budget=_positive_integer(operation["thread_budget"]),
        controlled_case=BenchmarkCase(
            identifier=_nonempty_string(controlled["id"]),
            source_width=_positive_integer(controlled["source_width"]),
            source_height=_positive_integer(controlled["source_height"]),
            destination_width=_positive_integer(controlled["destination_width"]),
            destination_height=_positive_integer(controlled["destination_height"]),
            edge_mode=_nonempty_string(controlled["edge_mode"]),
            working_space=_nonempty_string(controlled["working_space"]),
            memory_budget_bytes=_positive_integer(controlled["memory_budget_bytes"]),
            scratch_budget_bytes=_positive_integer(controlled["scratch_budget_bytes"]),
        ),
    )


def run_benchmark(policy: BenchmarkPolicy) -> BenchmarkResult:
    """Measure the complete controlled contract against a release native build."""
    session = _build_session(policy.controlled_case)
    budget = _budget(policy.controlled_case, policy.thread_budget)
    for _ in range(policy.warmup_iterations):
        session.evaluate(budget)
    latency_samples = _measure_milliseconds(
        lambda: session.evaluate(budget), policy.sample_iterations
    )
    allocated_bytes = _measure_native_allocation(lambda: session.evaluate(budget))
    cancellation_samples = _measure_cancellation(session, policy)
    deterministic = _verify_thread_determinism(session, policy.controlled_case)
    p50 = percentile(latency_samples, 50)
    return BenchmarkResult(
        latency_p50_ms=p50,
        latency_p95_ms=percentile(latency_samples, 95),
        latency_p99_ms=percentile(latency_samples, 99),
        throughput_per_second=(
            policy.controlled_case.destination_width
            * policy.controlled_case.destination_height
        )
        / (p50 / 1000.0),
        peak_resident_bytes=_peak_resident_bytes(),
        allocated_bytes=allocated_bytes,
        cancellation_latency_p99_ms=percentile(cancellation_samples, 99),
        deterministic_across_thread_budgets=deterministic,
    )


def validate_result(result: BenchmarkResult, policy: BenchmarkPolicy) -> list[str]:
    """Return every measured contract violation without relaxing any limit."""
    errors: list[str] = []
    for label, measured, limit in (
        ("latency p50", result.latency_p50_ms, policy.p50_ms),
        ("latency p95", result.latency_p95_ms, policy.p95_ms),
        ("latency p99", result.latency_p99_ms, policy.p99_ms),
        (
            "cancellation latency p99",
            result.cancellation_latency_p99_ms,
            policy.cancellation_latency_ms,
        ),
    ):
        if measured > limit:
            errors.append(f"{label} {measured:.3f} ms exceeds {limit:.3f} ms")
    for label, measured in (
        ("peak resident memory", result.peak_resident_bytes),
        ("allocated memory", result.allocated_bytes),
    ):
        if measured > policy.memory_ceiling_bytes:
            errors.append(
                f"{label} {measured} bytes exceeds {policy.memory_ceiling_bytes} bytes"
            )
    if result.throughput_per_second <= 0:
        errors.append("throughput must be positive")
    if not result.deterministic_across_thread_budgets:
        errors.append("output differs across declared thread budgets")
    return errors


def _build_session(case: BenchmarkCase) -> ResizeSession:
    """Construct the canonical linear-light 50-percent viewport benchmark graph."""
    source = bytes((24, 48, 96, 255)) * (case.source_width * case.source_height)
    engine = Engine()
    revision = engine.add_rgba8(source, case.source_width, case.source_height)
    builder = GraphBuilder(1)
    builder.add_node(1, "ferrastra.source.raster")
    builder.set_source_revision(1, revision)
    builder.add_node(2, _OPERATION)
    builder.connect(1, "result", 2, "source")
    for name, value in (
        ("source_width", case.source_width),
        ("source_height", case.source_height),
        ("destination_width", case.destination_width),
        ("destination_height", case.destination_height),
    ):
        builder.set_integer(2, name, value)
    builder.set_enum(2, "edge_mode", case.edge_mode)
    builder.set_enum(2, "working_space", case.working_space)
    builder.add_output("result", 2)
    return ResizeSession(
        engine,
        engine.compile(builder.build()),
        Region(0, 0, case.destination_width, case.destination_height),
    )


def _budget(
    case: BenchmarkCase,
    threads: int,
    cancellation: CancellationToken | None = None,
) -> EvaluationBudget:
    """Construct the fixed controlled execution budget."""
    return EvaluationBudget(
        memory_bytes=case.memory_budget_bytes,
        scratch_bytes=case.scratch_budget_bytes,
        threads=threads,
        cancellation=cancellation,
    )


def _measure_milliseconds(
    operation: Callable[[], object], iterations: int
) -> list[float]:
    """Measure independent wall-latency samples in milliseconds."""
    samples: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        operation()
        samples.append((time.perf_counter_ns() - started) / 1_000_000.0)
    return samples


def _measure_native_allocation(operation: Callable[[], RasterResult]) -> int:
    """Return exact peak request-owned native bytes reported by evaluation."""
    return operation().peak_memory_bytes


def _measure_cancellation(
    session: ResizeSession, policy: BenchmarkPolicy
) -> list[float]:
    """Measure request-to-return latency for synchronized in-flight cancellation."""
    samples: list[float] = []
    iterations = min(50, policy.sample_iterations)
    for _ in range(iterations):
        token = CancellationToken()
        ready = threading.Event()
        cancelled: list[bool] = []
        worker = threading.Thread(
            target=_evaluate_until_cancelled,
            args=(
                session,
                policy.controlled_case,
                policy.thread_budget,
                token,
                ready,
                cancelled,
            ),
            name="ferrastra-cancellation-probe",
        )
        worker.start()
        if not ready.wait(timeout=1.0):
            raise RuntimeError("cancellation benchmark did not enter evaluation")
        started = time.perf_counter_ns()
        token.cancel()
        worker.join(timeout=1.0)
        samples.append((time.perf_counter_ns() - started) / 1_000_000.0)
        if worker.is_alive() or cancelled != [True]:
            raise RuntimeError("evaluation did not terminate through cancellation")
    return samples


def _evaluate_until_cancelled(
    session: ResizeSession,
    case: BenchmarkCase,
    threads: int,
    token: CancellationToken,
    ready: threading.Event,
    cancelled: list[bool],
) -> None:
    """Enter evaluation after publishing readiness to the cancelling thread."""
    ready.set()
    try:
        session.evaluate(_budget(case, threads, token))
    except EvaluationError:
        cancelled.append(True)


def _verify_thread_determinism(session: ResizeSession, case: BenchmarkCase) -> bool:
    """Compare exact output bytes across every declared thread budget."""
    products = [
        session.evaluate(_budget(case, threads)).pixels for threads in (1, 2, 4, 8)
    ]
    return all(product == products[0] for product in products[1:])


def _peak_resident_bytes() -> int:
    """Return the process high-water resident set on each supported platform."""
    if os.name == "nt":
        return _windows_peak_resident_bytes()
    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) * 1024
    resource_module = cast(
        _ResourceModule,
        importlib.import_module("resource"),
    )
    usage = resource_module.getrusage(resource_module.RUSAGE_SELF)
    scale = 1 if sys.platform == "darwin" else 1024
    return int(usage.ru_maxrss) * scale


def _windows_peak_resident_bytes() -> int:
    """Query the Windows process peak working set without an optional dependency."""

    class ProcessMemoryCounters(ctypes.Structure):
        """Mirror the stable PROCESS_MEMORY_COUNTERS layout."""

        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.argtypes = []
    get_current_process.restype = wintypes.HANDLE
    get_process_memory = psapi.GetProcessMemoryInfo
    get_process_memory.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCounters),
        wintypes.DWORD,
    ]
    get_process_memory.restype = wintypes.BOOL
    process = get_current_process()
    succeeded = get_process_memory(process, ctypes.byref(counters), counters.cb)
    if not succeeded:
        raise OSError("GetProcessMemoryInfo failed")
    return int(counters.PeakWorkingSetSize)


def _positive_integer(value: object) -> int:
    """Narrow one validated positive manifest integer."""
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("expected a positive integer")
    return value


def _positive_float(value: object) -> float:
    """Narrow one validated positive manifest number."""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ValueError("expected a positive number")
    return float(value)


def _nonempty_string(value: object) -> str:
    """Narrow one validated nonempty manifest string."""
    if not isinstance(value, str) or not value:
        raise ValueError("expected a nonempty string")
    return value


def run() -> None:
    """Measure, print, and enforce the controlled performance contract."""
    policy = load_policy()
    result = run_benchmark(policy)
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    errors = validate_result(result, policy)
    if errors:
        for error in errors:
            print(f"FAILED: {error}", file=sys.stderr)
        raise SystemExit(1)
    print("SUCCESS: Ferrastra Lanczos3 meets the controlled performance contract.")


if __name__ == "__main__":
    run()
