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

"""Latency analysis, regression comparison, and pan correctness replay."""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from tools.pan_performance_runtime import PanFrameTiming
from tools.pan_render_harness import HeadlessPanHarness

COMPARISON_METRICS = (
    "end_to_end.p95_ms",
    "end_to_end.p99_ms",
    "end_to_end.max_ms",
    "explicit_repaint.p95_ms",
    "explicit_repaint.max_ms",
    "event_drain.p95_ms",
    "event_drain.max_ms",
    "paint_event.p95_ms",
    "paint_event.max_ms",
    "presentation.p95_ms",
    "presentation.max_ms",
    "repair_end_to_end.p95_ms",
    "repair_end_to_end.max_ms",
)


@dataclass(frozen=True, slots=True)
class LatencySummary:
    """Summarize one non-empty latency population in milliseconds."""

    count: int
    mean_ms: float
    median_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float


@dataclass(frozen=True, slots=True)
class PerformanceRegression:
    """Describe one baseline metric whose allowed latency was exceeded."""

    metric: str
    baseline_ms: float
    current_ms: float
    limit_ms: float


def summarize_latencies(values: Iterable[float]) -> LatencySummary | None:
    """Return nearest-rank latency statistics, or ``None`` for no samples."""
    samples = tuple(float(value) for value in values)
    if not samples:
        return None
    ordered = sorted(samples)
    return LatencySummary(
        count=len(samples),
        mean_ms=statistics.fmean(samples),
        median_ms=statistics.median(samples),
        p90_ms=_nearest_rank(ordered, 0.90),
        p95_ms=_nearest_rank(ordered, 0.95),
        p99_ms=_nearest_rank(ordered, 0.99),
        max_ms=ordered[-1],
    )


def build_summaries(
    frames: Sequence[PanFrameTiming],
) -> dict[str, LatencySummary | None]:
    """Summarize end-to-end latency and each measured renderer phase."""
    metrics = {
        "end_to_end": (frame.end_to_end_ms for frame in frames),
        "input_dispatch": (frame.input_dispatch_ms for frame in frames),
        "explicit_repaint": (frame.explicit_repaint_ms for frame in frames),
        "event_drain": (frame.event_drain_ms for frame in frames),
        "paint_event": (frame.paint_event_ms for frame in frames),
        "planning": (frame.planning_ms for frame in frames),
        "scroll_attempt": (frame.scroll_attempt_ms for frame in frames),
        "surface_scroll": (frame.surface_scroll_ms for frame in frames),
        "repair": (frame.repair_ms for frame in frames),
        "backing_paint": (frame.backing_paint_ms for frame in frames),
        "presentation": (frame.presentation_ms for frame in frames),
        "repair_end_to_end": (
            frame.end_to_end_ms for frame in frames if frame.scroll_repaired
        ),
        "ordinary_end_to_end": (
            frame.end_to_end_ms for frame in frames if not frame.scroll_repaired
        ),
    }
    return {name: summarize_latencies(values) for name, values in metrics.items()}


def select_correctness_steps(
    frames: Sequence[PanFrameTiming],
    *,
    limit: int,
) -> tuple[int, ...]:
    """Select slow, repaired, and distributed checkpoints from one measured run."""
    if limit <= 0 or not frames:
        return ()
    count = min(limit, len(frames))
    selected = {0, len(frames) - 1}
    slowest = sorted(
        range(len(frames)),
        key=lambda index: frames[index].end_to_end_ms,
        reverse=True,
    )
    selected.update(slowest[: max(1, count // 3)])
    repairs = [index for index, frame in enumerate(frames) if frame.scroll_repaired]
    selected.update(_evenly_spaced_indices(repairs, max(1, count // 3)))
    selected.update(_evenly_spaced_indices(list(range(len(frames))), count))
    ranked = sorted(
        selected,
        key=lambda index: (
            index not in repairs,
            -frames[index].end_to_end_ms,
            index,
        ),
    )
    return tuple(sorted(ranked[:count]))


def compare_summaries(
    current: dict[str, object],
    baseline: dict[str, object],
    *,
    regression_ratio: float,
    regression_slack_ms: float,
) -> tuple[PerformanceRegression, ...]:
    """Return material latency regressions across stable summary metrics."""
    if regression_ratio < 0.0:
        raise ValueError("regression_ratio must be non-negative")
    if regression_slack_ms < 0.0:
        raise ValueError("regression_slack_ms must be non-negative")
    regressions: list[PerformanceRegression] = []
    for metric in COMPARISON_METRICS:
        current_value = _nested_number(current, metric)
        baseline_value = _nested_number(baseline, metric)
        if current_value is None or baseline_value is None:
            continue
        limit = baseline_value * (1.0 + regression_ratio) + regression_slack_ms
        if current_value > limit:
            regressions.append(
                PerformanceRegression(
                    metric=metric,
                    baseline_ms=baseline_value,
                    current_ms=current_value,
                    limit_ms=limit,
                )
            )
    return tuple(regressions)


def run_correctness_replay(
    application: QApplication,
    image: QImage,
    *,
    logical_viewport: QSize,
    device_pixel_ratio: float,
    zoom: float,
    frames: Sequence[PanFrameTiming],
    checkpoint_limit: int,
    artifact_root: Path,
) -> dict[str, object]:
    """Replay measured pans and compare selected frames with clean redraws."""
    checkpoints = select_correctness_steps(frames, limit=checkpoint_limit)
    harness = HeadlessPanHarness(
        application,
        image,
        viewport_size=logical_viewport,
        device_pixel_ratio=device_pixel_ratio,
        zoom=zoom,
        artifact_root=artifact_root,
    )
    try:
        failures = harness.run(
            tuple(QPointF(frame.pan_x, frame.pan_y) for frame in frames),
            comparison_steps=frozenset(checkpoints),
            direct_navigation=True,
        )
    finally:
        harness.close()
    return {
        "passed": not failures,
        "checked_steps": list(checkpoints),
        "failure_count": len(failures),
        "first_failure": (
            None
            if not failures
            else {
                "step_index": failures[0].step_index,
                "artifact_directory": str(failures[0].artifact_directory.resolve()),
                "mismatch_pixels": failures[0].difference.mismatch_pixels,
            }
        ),
    }


def _nearest_rank(ordered: Sequence[float], quantile: float) -> float:
    """Return one nearest-rank quantile from sorted non-empty values."""
    if not ordered:
        raise ValueError("ordered values must be non-empty")
    index = min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1)
    return float(ordered[index])


def _evenly_spaced_indices(indices: Sequence[int], count: int) -> set[int]:
    """Return up to ``count`` values distributed across ordered indices."""
    if count <= 0 or not indices:
        return set()
    if count >= len(indices):
        return set(indices)
    if count == 1:
        return {indices[len(indices) // 2]}
    return {
        indices[round(position * (len(indices) - 1) / (count - 1))]
        for position in range(count)
    }


def _nested_number(mapping: dict[str, object], path: str) -> float | None:
    """Resolve one dot-separated numeric value from a JSON-style mapping."""
    current: object = mapping
    for component in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(component)
    if isinstance(current, bool) or not isinstance(current, (int, float)):
        return None
    return float(current)
