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

"""Tests for deterministic standalone pan-performance analysis helpers."""

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from cutecanvas_test_support.harness_tools.cutecanvas_pan_performance_harness import (
    compare_images,
    elliptical_pointer_path,
)
from cutecanvas_test_support.harness_tools.pan_performance_analysis import (
    compare_summaries,
    select_correctness_steps,
    summarize_latencies,
)
from cutecanvas_test_support.harness_tools.pan_performance_runtime import (
    PanFrameTiming,
    pointer_path,
)
from cutecanvas_test_support.harness_tools.pan_render_harness import (
    HeadlessPanHarness,
    _ProgressWatchdog,
    coordinate_fingerprint_image,
)


def _frame(
    index: int,
    elapsed_ms: float,
    *,
    repaired: bool = False,
) -> PanFrameTiming:
    """Return one compact timing frame for analysis-helper tests."""
    return PanFrameTiming(
        step_index=index,
        pointer_x=index,
        pointer_y=index,
        pan_x=float(index),
        pan_y=float(-index),
        end_to_end_ms=elapsed_ms,
        input_dispatch_ms=elapsed_ms / 2.0,
        explicit_repaint_ms=elapsed_ms / 3.0,
        event_drain_ms=elapsed_ms / 6.0,
        paint_event_ms=elapsed_ms / 2.0,
        planning_ms=0.0,
        scroll_attempt_ms=0.0,
        surface_scroll_ms=0.0,
        repair_ms=0.0,
        backing_paint_ms=0.0,
        presentation_ms=0.0,
        paint_event_count=1,
        scroll_attempted=True,
        scroll_repaired=repaired,
        full_redraw=False,
    )


def test_pointer_path_is_deterministic_bounded_and_starts_at_center() -> None:
    """The headless drag workload should remain reproducible and widget-bounded."""
    size = QSize(320, 180)

    first = pointer_path(size, steps=41, cycles=2.0)
    second = pointer_path(size, steps=41, cycles=2.0)

    assert first == second
    assert first[0].x() == size.width() // 2
    assert first[0].y() == size.height() // 2
    assert all(0 <= point.x() < size.width() for point in first)
    assert all(0 <= point.y() < size.height() for point in first)


def test_headless_pan_harness_close_joins_every_owned_execution_worker(
    qapp,
    tmp_path,
) -> None:
    """Harness teardown must leave no native work competing with later tests."""
    harness = HeadlessPanHarness(
        qapp,
        coordinate_fingerprint_image(QSize(256, 256)),
        viewport_size=QSize(96, 96),
        artifact_root=tmp_path,
    )
    runtimes = (
        harness._qpane._execution_runtime,
        harness._reference_qpane._execution_runtime,
    )
    workers = tuple(
        thread
        for runtime in runtimes
        for backend in runtime._backends
        for thread in getattr(backend, "_threads", ())
    )

    harness.close()

    assert all(runtime.is_closed for runtime in runtimes)
    assert workers
    assert not any(thread.is_alive() for thread in workers)


def test_progress_watchdog_extends_only_after_observable_progress() -> None:
    """A busy queue may continue only while its diagnostic state advances."""
    watchdog = _ProgressWatchdog.start(
        now=0.0,
        stall_timeout_seconds=5.0,
        hard_timeout_seconds=30.0,
        initial_state=("pending", 0),
    )

    assert watchdog.permits_wait(("pending", 0), now=4.99)
    assert watchdog.permits_wait(("pending", 1), now=4.99)
    assert watchdog.permits_wait(("pending", 1), now=9.98)
    assert not watchdog.permits_wait(("pending", 1), now=9.99)


def test_progress_watchdog_never_extends_past_hard_deadline() -> None:
    """Continuous active work must not defeat the wait's absolute bound."""
    watchdog = _ProgressWatchdog.start(
        now=0.0,
        stall_timeout_seconds=5.0,
        hard_timeout_seconds=12.0,
        initial_state=("pending", 0),
    )

    assert watchdog.permits_wait(("pending", 0), now=4.0, work_active=True)
    assert watchdog.permits_wait(("pending", 0), now=8.0, work_active=True)
    assert not watchdog.permits_wait(("pending", 0), now=12.0, work_active=True)


def test_cutecanvas_reproducer_path_retains_exact_large_first_jump() -> None:
    """The document benchmark should retain its 97 immutable pointer updates."""
    size = QSize(3840, 2160)

    positions = elliptical_pointer_path(
        size,
        steps=96,
        radius_x=1500,
        radius_y=800,
    )

    assert len(positions) == 97
    assert positions[0].x() == size.width() // 2 + 1500
    assert positions[0].y() == size.height() // 2
    assert positions[-1].x() == size.width() // 2
    assert positions[-1].y() == size.height() // 2


def test_cutecanvas_image_comparison_counts_pixels_not_channel_bytes() -> None:
    """The clean-redraw oracle should report each changed pixel once."""
    actual = QImage(QSize(3, 2), QImage.Format.Format_ARGB32_Premultiplied)
    expected = QImage(QSize(3, 2), QImage.Format.Format_ARGB32_Premultiplied)
    actual.fill(QColor("black"))
    expected.fill(QColor("black"))
    actual.setPixelColor(1, 0, QColor(10, 20, 30, 255))
    actual.setPixelColor(2, 1, QColor(40, 50, 60, 255))

    difference = compare_images(actual, expected)

    assert difference["mismatch_pixels"] == 2
    assert difference["exact_mismatch_pixels"] == 2
    assert difference["max_channel_delta"] == 60
    assert difference["size_mismatch"] is False


def test_cutecanvas_image_comparison_reports_filtered_rounding_separately() -> None:
    """The document oracle should retain exact counts below its filter tolerance."""
    actual = QImage(QSize(2, 1), QImage.Format.Format_ARGB32_Premultiplied)
    expected = QImage(QSize(2, 1), QImage.Format.Format_ARGB32_Premultiplied)
    actual.fill(QColor(10, 20, 30, 255))
    expected.fill(QColor(10, 20, 30, 255))
    actual.setPixelColor(1, 0, QColor(11, 20, 30, 255))

    difference = compare_images(actual, expected, channel_tolerance=1)

    assert difference["mismatch_pixels"] == 0
    assert difference["exact_mismatch_pixels"] == 1
    assert difference["max_channel_delta"] == 1


def test_latency_summary_uses_nearest_rank_tail_samples() -> None:
    """Summary tails should retain isolated slow frames instead of averaging them."""
    summary = summarize_latencies((1.0, 2.0, 3.0, 4.0, 100.0))

    assert summary is not None
    assert summary.count == 5
    assert summary.median_ms == 3.0
    assert summary.p90_ms == 100.0
    assert summary.p99_ms == 100.0
    assert summary.max_ms == 100.0


def test_correctness_checkpoints_include_slow_and_repair_frames() -> None:
    """Oracle sampling should prioritize the risky transitions from the timing run."""
    frames = tuple(
        _frame(
            index,
            90.0 if index == 7 else 5.0 + index,
            repaired=index in {3, 7},
        )
        for index in range(12)
    )

    selected = select_correctness_steps(frames, limit=6)

    assert len(selected) == 6
    assert 7 in selected
    assert any(frames[index].scroll_repaired for index in selected)


def test_baseline_comparison_requires_ratio_and_absolute_slack() -> None:
    """Small noise should pass while a material tail regression is reported."""
    baseline = {
        "end_to_end": {
            "p95_ms": 10.0,
            "p99_ms": 12.0,
            "max_ms": 14.0,
        }
    }
    current = {
        "end_to_end": {
            "p95_ms": 12.5,
            "p99_ms": 16.0,
            "max_ms": 18.0,
        }
    }

    regressions = compare_summaries(
        current,
        baseline,
        regression_ratio=0.20,
        regression_slack_ms=1.0,
    )

    assert [regression.metric for regression in regressions] == [
        "end_to_end.p99_ms",
        "end_to_end.max_ms",
    ]
