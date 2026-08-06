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

"""Profile a headless high-resolution viewport and verify replayed pixels."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from cutecanvas_test_support.harness_tools.pan_performance_analysis import (
    LatencySummary,
    PerformanceRegression,
    build_summaries,
    compare_summaries,
    run_correctness_replay,
)
from cutecanvas_test_support.harness_tools.pan_performance_runtime import (
    HeadlessPanPerformanceHarness,
    PanFrameTiming,
    PanPerformanceProfile,
)
from cutecanvas_test_support.harness_tools.pan_render_harness import (
    coordinate_fingerprint_image,
)

_RESULT_VERSION = 1
_DEFAULT_REGRESSION_RATIO = 0.20
_DEFAULT_REGRESSION_SLACK_MS = 1.0


def _profile_catalog() -> dict[str, PanPerformanceProfile]:
    """Return the supported local benchmark workloads."""
    return {
        "quick": PanPerformanceProfile(
            name="quick",
            physical_viewport=QSize(1280, 720),
            image_size=QSize(2048, 1536),
            zoom=5.0,
            steps=60,
            warmup_steps=12,
            path_cycles=1.5,
        ),
        "1440p-5x": PanPerformanceProfile(
            name="1440p-5x",
            physical_viewport=QSize(2560, 1440),
            image_size=QSize(4096, 2160),
            zoom=5.0,
            steps=240,
            warmup_steps=32,
            path_cycles=4.0,
        ),
        "4k-5x": PanPerformanceProfile(
            name="4k-5x",
            physical_viewport=QSize(3840, 2160),
            image_size=QSize(4096, 2160),
            zoom=5.0,
            steps=240,
            warmup_steps=32,
            path_cycles=4.0,
        ),
    }


def _parse_args(arguments: Sequence[str]) -> argparse.Namespace:
    """Parse standalone headless navigation benchmark options."""
    catalog = _profile_catalog()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=tuple(catalog),
        default="4k-5x",
        help="Reproducible workload geometry.",
    )
    parser.add_argument("--image", type=Path)
    parser.add_argument("--steps", type=int)
    parser.add_argument("--warmup-steps", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument(
        "--regression-ratio",
        type=float,
        default=_DEFAULT_REGRESSION_RATIO,
    )
    parser.add_argument(
        "--regression-slack-ms",
        type=float,
        default=_DEFAULT_REGRESSION_SLACK_MS,
    )
    parser.add_argument("--correctness-steps", type=int, default=12)
    parser.add_argument(
        "--no-correctness",
        action="store_true",
        help="Skip the post-timing differential replay.",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("pan-performance-artifacts"),
    )
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    """Run a headless performance pass followed by optional correctness replay."""
    options = _parse_args(arguments if arguments is not None else sys.argv[1:])
    application = QApplication.instance() or QApplication(sys.argv)
    qt_platform = application.platformName().lower()
    if qt_platform != "offscreen":
        print(
            "ERROR: pan performance results require Qt's headless offscreen platform; "
            f"active platform is {qt_platform!r}.",
            file=sys.stderr,
        )
        return 2
    profile = _profile_catalog()[options.profile]
    if options.steps is not None:
        profile = _replace_profile(profile, steps=options.steps)
    if options.warmup_steps is not None:
        profile = _replace_profile(profile, warmup_steps=options.warmup_steps)
    image = _load_image(options.image, profile.image_size)
    content_identity = _content_identity(options.image, image)
    harness = HeadlessPanPerformanceHarness(application, profile, image)
    try:
        frames = harness.run()
        summaries = build_summaries(frames)
        result = _build_result(
            profile,
            harness,
            qt_platform=qt_platform,
            content_identity=content_identity,
            frames=frames,
            summaries=summaries,
        )
        if not options.no_correctness:
            result["correctness"] = run_correctness_replay(
                application,
                image,
                logical_viewport=harness.logical_viewport,
                device_pixel_ratio=harness.device_pixel_ratio,
                zoom=profile.zoom,
                frames=frames,
                checkpoint_limit=options.correctness_steps,
                artifact_root=options.artifact_root / profile.name,
            )
    finally:
        harness.close()
    regressions: tuple[PerformanceRegression, ...] = ()
    if options.compare is not None:
        baseline = json.loads(options.compare.read_text(encoding="utf-8"))
        _validate_baseline_identity(result, baseline)
        regressions = compare_summaries(
            result["summaries"],
            baseline["summaries"],
            regression_ratio=options.regression_ratio,
            regression_slack_ms=options.regression_slack_ms,
        )
    result["regressions"] = [asdict(regression) for regression in regressions]
    _print_summary(result)
    if options.output is not None:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(
            json.dumps(result, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"JSON: {options.output.resolve()}")
    correctness = result.get("correctness")
    correctness_failed = (
        isinstance(correctness, dict) and correctness.get("passed") is False
    )
    return 1 if regressions or correctness_failed else 0


def _replace_profile(
    profile: PanPerformanceProfile,
    *,
    steps: int | None = None,
    warmup_steps: int | None = None,
) -> PanPerformanceProfile:
    """Return one profile with validated CLI sample-count overrides."""
    resolved_steps = profile.steps if steps is None else int(steps)
    resolved_warmup = (
        profile.warmup_steps if warmup_steps is None else int(warmup_steps)
    )
    if resolved_steps < 2:
        raise ValueError("steps must be at least two")
    if resolved_warmup < 2:
        raise ValueError("warmup steps must be at least two")
    return PanPerformanceProfile(
        name=profile.name,
        physical_viewport=QSize(profile.physical_viewport),
        image_size=QSize(profile.image_size),
        zoom=profile.zoom,
        steps=resolved_steps,
        warmup_steps=resolved_warmup,
        path_cycles=profile.path_cycles,
    )


def _load_image(path: Path | None, fallback_size: QSize) -> QImage:
    """Load a real image or create deterministic coordinate-dependent content."""
    if path is None:
        return coordinate_fingerprint_image(fallback_size)
    image = QImage(str(path))
    if image.isNull():
        raise ValueError(f"could not load image: {path}")
    return image


def _content_identity(path: Path | None, image: QImage) -> dict[str, object]:
    """Return stable baseline identity for generated or file-backed content."""
    if path is None:
        return {
            "source": "coordinate-fingerprint",
            "width": image.width(),
            "height": image.height(),
        }
    resolved = path.resolve()
    stat = resolved.stat()
    return {
        "source": str(resolved),
        "width": image.width(),
        "height": image.height(),
        "file_size": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
    }


def _build_result(
    profile: PanPerformanceProfile,
    harness: HeadlessPanPerformanceHarness,
    *,
    qt_platform: str,
    content_identity: dict[str, object],
    frames: Sequence[PanFrameTiming],
    summaries: dict[str, LatencySummary | None],
) -> dict[str, object]:
    """Build the complete serializable benchmark result."""
    renderer = harness.pane._rendering.presenter.renderer
    buffer = renderer.get_base_buffer()
    buffer_size = QSize() if buffer is None else buffer.size()
    return {
        "version": _RESULT_VERSION,
        "profile": profile.name,
        "platform": {
            "qt": qt_platform,
            "python": platform.python_version(),
            "system": platform.platform(),
        },
        "content": content_identity,
        "geometry": {
            "requested_physical_width": profile.physical_viewport.width(),
            "requested_physical_height": profile.physical_viewport.height(),
            "actual_physical_width": harness.physical_viewport.width(),
            "actual_physical_height": harness.physical_viewport.height(),
            "logical_width": harness.logical_viewport.width(),
            "logical_height": harness.logical_viewport.height(),
            "device_pixel_ratio": harness.device_pixel_ratio,
            "buffer_width": buffer_size.width(),
            "buffer_height": buffer_size.height(),
            "overscan_physical_px": renderer.buffer_overscan_physical_px,
            "zoom": profile.zoom,
        },
        "summaries": {
            name: None if summary is None else asdict(summary)
            for name, summary in summaries.items()
        },
        "counts": {
            "frames": len(frames),
            "paint_events": sum(frame.paint_event_count for frame in frames),
            "scroll_attempts": sum(frame.scroll_attempted for frame in frames),
            "scroll_repairs": sum(frame.scroll_repaired for frame in frames),
            "full_redraws": sum(frame.full_redraw for frame in frames),
            "frames_over_16_67_ms": sum(
                frame.end_to_end_ms > 1000.0 / 60.0 for frame in frames
            ),
            "frames_over_33_33_ms": sum(
                frame.end_to_end_ms > 1000.0 / 30.0 for frame in frames
            ),
            "frames_over_100_ms": sum(frame.end_to_end_ms > 100.0 for frame in frames),
        },
        "frames": [asdict(frame) for frame in frames],
    }


def _print_summary(result: dict[str, object]) -> None:
    """Print a compact human-readable benchmark and correctness report."""
    geometry = result["geometry"]
    summaries = result["summaries"]
    counts = result["counts"]
    if not isinstance(geometry, dict) or not isinstance(summaries, dict):
        raise TypeError("benchmark result has invalid geometry or summaries")
    if not isinstance(counts, dict):
        raise TypeError("benchmark result has invalid counts")
    platform_details = result["platform"]
    if not isinstance(platform_details, dict):
        raise TypeError("benchmark result has invalid platform details")
    print(
        f"profile={result['profile']} qt={platform_details['qt']} "
        f"viewport={geometry['actual_physical_width']}x"
        f"{geometry['actual_physical_height']} "
        f"dpr={geometry['device_pixel_ratio']:.3g} "
        f"buffer={geometry['buffer_width']}x{geometry['buffer_height']}"
    )
    for name in (
        "end_to_end",
        "explicit_repaint",
        "event_drain",
        "paint_event",
        "input_dispatch",
        "planning",
        "surface_scroll",
        "repair",
        "backing_paint",
        "presentation",
        "repair_end_to_end",
    ):
        summary = summaries.get(name)
        if not isinstance(summary, dict) or not summary["count"]:
            continue
        print(
            f"{name:>20}: mean={summary['mean_ms']:8.3f} "
            f"p95={summary['p95_ms']:8.3f} "
            f"p99={summary['p99_ms']:8.3f} "
            f"max={summary['max_ms']:8.3f} ms"
        )
    print(
        f"frames={counts['frames']} repairs={counts['scroll_repairs']} "
        f">16.67ms={counts['frames_over_16_67_ms']} "
        f">33.33ms={counts['frames_over_33_33_ms']} "
        f">100ms={counts['frames_over_100_ms']}"
    )
    correctness = result.get("correctness")
    if isinstance(correctness, dict):
        label = "PASS" if correctness.get("passed") else "FAIL"
        print(
            f"correctness={label} "
            f"checkpoints={len(correctness.get('checked_steps', ()))}"
        )
    regressions = result.get("regressions")
    if isinstance(regressions, list):
        for regression in regressions:
            print(
                "REGRESSION: "
                f"{regression['metric']} current={regression['current_ms']:.3f}ms "
                f"baseline={regression['baseline_ms']:.3f}ms "
                f"limit={regression['limit_ms']:.3f}ms"
            )


def _validate_baseline_identity(
    current: dict[str, object],
    baseline: dict[str, object],
) -> None:
    """Reject comparisons across different workloads or physical geometry."""
    if current.get("version") != baseline.get("version"):
        raise ValueError("baseline result version does not match")
    if current.get("profile") != baseline.get("profile"):
        raise ValueError("baseline profile does not match")
    if current.get("content") != baseline.get("content"):
        raise ValueError("baseline content does not match")
    current_geometry = current.get("geometry")
    baseline_geometry = baseline.get("geometry")
    if not isinstance(current_geometry, dict) or not isinstance(
        baseline_geometry,
        dict,
    ):
        raise TypeError("baseline geometry is missing")
    identity_keys = (
        "actual_physical_width",
        "actual_physical_height",
        "device_pixel_ratio",
        "zoom",
    )
    if any(
        current_geometry.get(key) != baseline_geometry.get(key) for key in identity_keys
    ):
        raise ValueError("baseline viewport geometry does not match")


if __name__ == "__main__":
    raise SystemExit(main())
