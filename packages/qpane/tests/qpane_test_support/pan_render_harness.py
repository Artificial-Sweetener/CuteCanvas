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

"""Detect pan-rendering artifacts by comparing reuse against full redraws."""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtGui import QImage, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qpane import QPane


@dataclass(frozen=True)
class FrameDifference:
    """Describe the pixels that differ between an incremental and clean frame."""

    mismatch_pixels: int
    mismatch_bounds: QRect
    column_spans: tuple[tuple[int, int], ...]
    max_channel_delta: int
    max_column_coverage: float

    @property
    def detected(self) -> bool:
        """Return whether the compared frames contain any meaningful difference."""
        return self.mismatch_pixels > 0


@dataclass(frozen=True)
class PanHarnessFailure:
    """Record one pan step whose incremental frame differs from its redraw oracle."""

    step_index: int
    requested_pan: QPointF
    actual_pan: QPointF
    difference: FrameDifference
    artifact_directory: Path


class FrameArtifactDetector:
    """Compare rendered frames without assuming any artifact color or shape."""

    def __init__(self, *, channel_tolerance: int = 0) -> None:
        """Configure the maximum harmless difference in any RGBA channel."""
        if not 0 <= channel_tolerance <= 255:
            raise ValueError("channel_tolerance must be between 0 and 255")
        self._channel_tolerance = channel_tolerance

    def compare(self, actual: QImage, expected: QImage) -> FrameDifference:
        """Return spatial and pixel statistics for two equally sized frames."""
        if actual.size() != expected.size():
            raise ValueError(
                "frame sizes differ: "
                f"actual={actual.width()}x{actual.height()}, "
                f"expected={expected.width()}x{expected.height()}"
            )
        actual_pixels = _rgba_pixels(actual)
        expected_pixels = _rgba_pixels(expected)
        channel_delta = np.abs(
            actual_pixels.astype(np.int16) - expected_pixels.astype(np.int16)
        )
        pixel_delta = channel_delta.max(axis=2)
        mismatch_mask = pixel_delta > self._channel_tolerance
        mismatch_y, mismatch_x = np.nonzero(mismatch_mask)
        mismatch_pixels = int(mismatch_mask.sum())
        if mismatch_pixels == 0:
            return FrameDifference(
                mismatch_pixels=0,
                mismatch_bounds=QRect(),
                column_spans=(),
                max_channel_delta=0,
                max_column_coverage=0.0,
            )
        mismatched_columns = np.flatnonzero(mismatch_mask.any(axis=0))
        column_coverage = mismatch_mask.mean(axis=0)
        return FrameDifference(
            mismatch_pixels=mismatch_pixels,
            mismatch_bounds=QRect(
                int(mismatch_x.min()),
                int(mismatch_y.min()),
                int(mismatch_x.max() - mismatch_x.min() + 1),
                int(mismatch_y.max() - mismatch_y.min() + 1),
            ),
            column_spans=_contiguous_spans(mismatched_columns),
            max_channel_delta=int(pixel_delta.max()),
            max_column_coverage=float(column_coverage.max()),
        )

    def difference_image(self, actual: QImage, expected: QImage) -> QImage:
        """Return a diagnostic image highlighting mismatches over the reference."""
        if actual.size() != expected.size():
            raise ValueError("difference images must have matching sizes")
        actual_pixels = _rgba_pixels(actual)
        expected_pixels = _rgba_pixels(expected)
        channel_delta = np.abs(
            actual_pixels.astype(np.int16) - expected_pixels.astype(np.int16)
        )
        mismatch_mask = channel_delta.max(axis=2) > self._channel_tolerance
        visualization = expected_pixels.copy()
        visualization[..., :3] //= 4
        visualization[mismatch_mask] = np.array([255, 0, 255, 255], dtype=np.uint8)
        return _image_from_rgba(visualization)


class HeadlessPanHarness:
    """Compare an abused QPane with an independent full-redraw oracle."""

    def __init__(
        self,
        application: QApplication,
        image: QImage,
        *,
        viewport_size: QSize | None = None,
        device_pixel_ratio: float = 1.0,
        zoom: float = 1.0,
        channel_tolerance: int = 0,
        artifact_root: Path = Path("pan-harness-artifacts"),
        configure_qpane: Callable[[QPane], None] | None = None,
    ) -> None:
        """Mount the offscreen widgets and initialize their identical scenes."""
        viewport_size = (
            QSize(512, 512) if viewport_size is None else QSize(viewport_size)
        )
        if image.isNull():
            raise ValueError("image must be non-null")
        if viewport_size.isEmpty():
            raise ValueError("viewport_size must be non-empty")
        if device_pixel_ratio <= 0.0:
            raise ValueError("device_pixel_ratio must be positive")
        if zoom <= 0.0:
            raise ValueError("zoom must be positive")
        self._application = application
        self._detector = FrameArtifactDetector(channel_tolerance=channel_tolerance)
        self._artifact_root = artifact_root
        self._device_pixel_ratio = float(device_pixel_ratio)
        self._zoom = float(zoom)
        self._configure_qpane = configure_qpane
        self._qpane = self._create_qpane(image, viewport_size)
        self._reference_qpane = self._create_qpane(image, viewport_size)
        self._settle_widget()
        self._wait_for_raster_idle(self._qpane)
        self._wait_for_raster_idle(self._reference_qpane)

    def run(
        self,
        pan_sequence: Sequence[QPointF],
        *,
        stop_on_failure: bool = True,
        comparison_steps: Collection[int] | None = None,
        direct_navigation: bool = False,
    ) -> list[PanHarnessFailure]:
        """Apply pans and return mismatches from the selected oracle checkpoints."""
        failures: list[PanHarnessFailure] = []
        requested_history: list[QPointF] = []
        actual_history: list[QPointF] = []
        selected_steps = (
            None if comparison_steps is None else frozenset(comparison_steps)
        )
        presenter = self._qpane._rendering.presenter
        if direct_navigation:
            presenter.begin_navigation_interaction()
        try:
            for step_index, requested_pan in enumerate(pan_sequence):
                requested_history.append(QPointF(requested_pan))
                self._qpane.setPan(requested_pan)
                self._qpane.update()
                self._settle_widget()
                actual_pan = self._qpane.currentPan()
                actual_history.append(QPointF(actual_pan))
                if selected_steps is not None and step_index not in selected_steps:
                    continue
                actual_frame = self.capture_settled_buffer(self._qpane)
                renderer = presenter.renderer
                buffer_pan = QPointF(renderer._buffer_pan)
                valid_region = QRegion(renderer._buffer_valid_region)
                expected_frame = self._capture_full_redraw_reference(buffer_pan)
                visible_rect = QRect(
                    renderer.buffer_overscan_physical_px,
                    renderer.buffer_overscan_physical_px,
                    renderer._viewport_physical_size.width(),
                    renderer._viewport_physical_size.height(),
                )
                if not QRegion(visible_rect).subtracted(valid_region).isEmpty():
                    raise AssertionError(
                        "incremental renderer exposed pixels outside its valid region"
                    )
                comparable_actual = _copy_region_onto_reference(
                    actual_frame,
                    expected_frame,
                    valid_region,
                )
                difference = self._detector.compare(
                    comparable_actual,
                    expected_frame,
                )
                if not difference.detected:
                    continue
                artifact_directory = self._write_failure_artifacts(
                    step_index=step_index,
                    requested_pan=requested_pan,
                    actual_pan=actual_pan,
                    actual_frame=comparable_actual,
                    expected_frame=expected_frame,
                    difference=difference,
                    requested_history=requested_history,
                    actual_history=actual_history,
                )
                failures.append(
                    PanHarnessFailure(
                        step_index=step_index,
                        requested_pan=QPointF(requested_pan),
                        actual_pan=QPointF(actual_pan),
                        difference=difference,
                        artifact_directory=artifact_directory,
                    )
                )
                if stop_on_failure:
                    break
        finally:
            if direct_navigation:
                presenter.finish_navigation_interaction()
                self._settle_widget()
        return failures

    def close(self) -> None:
        """Release the mounted widget and drain its deferred Qt cleanup."""
        for pane in (self._reference_qpane, self._qpane):
            pane.close()
            pane.deleteLater()
        self._application.processEvents()

    @staticmethod
    def capture_settled_buffer(qpane: QPane) -> QImage:
        """Return every settled pixel, including the offscreen repair guard."""
        renderer = qpane._rendering.presenter.renderer
        base_buffer = renderer.get_base_buffer()
        if base_buffer is None:
            raise RuntimeError("QPane has no allocated render buffer")
        return QImage(base_buffer)

    @staticmethod
    def capture_settled_buffer_frame(qpane: QPane) -> QImage:
        """Return the viewport crop represented by the renderer's settled buffer."""
        renderer = qpane._rendering.presenter.renderer
        base_buffer = renderer.get_base_buffer()
        if base_buffer is None:
            raise RuntimeError("QPane has no allocated render buffer")
        viewport_size = renderer._viewport_physical_size
        margin = renderer.buffer_overscan_physical_px
        frame = base_buffer.copy(
            QRect(
                margin,
                margin,
                viewport_size.width(),
                viewport_size.height(),
            )
        )
        frame.setDevicePixelRatio(base_buffer.devicePixelRatio())
        return frame

    @staticmethod
    def capture_visible_frame(qpane: QPane) -> QImage:
        """Return the viewport crop of the renderer's settled backing frame."""
        return HeadlessPanHarness.capture_settled_buffer_frame(qpane)

    def _create_qpane(self, image: QImage, viewport_size: QSize) -> QPane:
        """Create one configured QPane used by the differential harness."""
        qpane = QPane()
        try:
            device_pixel_ratio = self._device_pixel_ratio
            qpane.devicePixelRatioF = lambda: device_pixel_ratio  # type: ignore[method-assign]
            qpane.resize(viewport_size)
            qpane.setImage(QImage(image))
            qpane.setZoom1To1()
            if self._configure_qpane is not None:
                self._configure_qpane(qpane)
            qpane._rendering.viewport.setZoomAndPan(
                self._zoom,
                QPointF(0.0, 0.0),
            )
            qpane.show()
            qpane._rendering.presenter.ensure_view_alignment(force=True)
            qpane._rendering.presenter.mark_dirty()
            qpane.update()
            return qpane
        except Exception:
            qpane.close()
            qpane.deleteLater()
            self._application.processEvents()
            raise

    def _settle_widget(self) -> None:
        """Process queued paint work until the widget exposes its current buffer."""
        self._application.sendPostedEvents()
        self._application.processEvents()

    def _wait_for_raster_idle(
        self,
        qpane: QPane,
        *,
        timeout_seconds: float = 5.0,
    ) -> None:
        """Settle asynchronous pyramid and tile products before comparisons."""
        deadline = time.perf_counter() + timeout_seconds
        idle_since: float | None = None
        view = qpane._rendering
        while time.perf_counter() < deadline:
            self._settle_widget()
            tile_metrics = view.presenter.tile_manager.snapshot_metrics()
            idle = (
                not view.pyramids.pending_asset_keys()
                and not view.pyramids.pending_retry_asset_keys()
                and tile_metrics.active_jobs == 0
                and tile_metrics.pending_retries == 0
            )
            now = time.perf_counter()
            if idle:
                idle_since = now if idle_since is None else idle_since
                if now - idle_since >= 0.025:
                    view.presenter.mark_dirty()
                    qpane.update()
                    self._settle_widget()
                    return
            else:
                idle_since = None
            QTest.qWait(1)
        raise TimeoutError("pan harness raster products did not settle")

    def _capture_full_redraw_reference(self, buffer_pan: QPointF) -> QImage:
        """Render a clean reference at the incremental buffer's settled pan."""
        presenter = self._reference_qpane._rendering.presenter
        plan = presenter.calculateRenderPlan(use_pan=buffer_pan, is_blank=False)
        if plan is None:
            raise RuntimeError("QPane produced no render plan for the redraw oracle")
        presenter.renderer.markDirty()
        presenter.renderer.paint(plan)
        return self.capture_settled_buffer(self._reference_qpane)

    def _write_failure_artifacts(
        self,
        *,
        step_index: int,
        requested_pan: QPointF,
        actual_pan: QPointF,
        actual_frame: QImage,
        expected_frame: QImage,
        difference: FrameDifference,
        requested_history: Sequence[QPointF],
        actual_history: Sequence[QPointF],
    ) -> Path:
        """Persist a reproducible frame triplet and mismatch metadata."""
        artifact_directory = self._artifact_root / f"step-{step_index:05d}"
        artifact_directory.mkdir(parents=True, exist_ok=True)
        actual_frame.save(str(artifact_directory / "actual.png"))
        expected_frame.save(str(artifact_directory / "expected.png"))
        self._detector.difference_image(actual_frame, expected_frame).save(
            str(artifact_directory / "difference.png")
        )
        bounds = difference.mismatch_bounds
        metadata = {
            "step_index": step_index,
            "requested_pan": [requested_pan.x(), requested_pan.y()],
            "actual_pan": [actual_pan.x(), actual_pan.y()],
            "device_pixel_ratio": self._device_pixel_ratio,
            "zoom": self._zoom,
            "mismatch_pixels": difference.mismatch_pixels,
            "mismatch_bounds": [
                bounds.x(),
                bounds.y(),
                bounds.width(),
                bounds.height(),
            ],
            "column_spans": [list(span) for span in difference.column_spans],
            "max_channel_delta": difference.max_channel_delta,
            "max_column_coverage": difference.max_column_coverage,
            "requested_pan_sequence": [[pan.x(), pan.y()] for pan in requested_history],
            "actual_pan_sequence": [[pan.x(), pan.y()] for pan in actual_history],
        }
        (artifact_directory / "metadata.json").write_text(
            json.dumps(metadata, indent=2),
            encoding="utf-8",
        )
        return artifact_directory


def coordinate_fingerprint_image(size: QSize) -> QImage:
    """Return opaque coordinate-dependent pixels that expose stale rows or columns."""
    if size.isEmpty():
        raise ValueError("size must be non-empty")
    y, x = np.indices((size.height(), size.width()), dtype=np.uint32)
    rgba = np.empty((size.height(), size.width(), 4), dtype=np.uint8)
    rgba[..., 0] = (x * 17 + y * 3 + (x // 7) * 29) % 256
    rgba[..., 1] = (x * 5 + y * 19 + (y // 11) * 31) % 256
    rgba[..., 2] = (x * 13 + y * 7 + ((x + y) // 5) * 23) % 256
    rgba[..., 3] = 255
    return _image_from_rgba(rgba)


def random_walk_pans(
    *,
    steps: int,
    seed: int,
    max_step: float = 24.0,
) -> tuple[QPointF, ...]:
    """Return a reproducible fractional pan sequence with frequent direction changes."""
    if steps < 0:
        raise ValueError("steps must be non-negative")
    if max_step <= 0.0:
        raise ValueError("max_step must be positive")
    generator = random.Random(seed)
    pans: list[QPointF] = []
    current = QPointF(0.0, 0.0)
    fractions = (0.0, 0.25, 0.5, 0.75)
    for step_index in range(steps):
        if step_index % 17 == 0:
            delta_x = generator.uniform(-max_step * 4.0, max_step * 4.0)
            delta_y = generator.uniform(-max_step * 4.0, max_step * 4.0)
        else:
            delta_x = generator.uniform(-max_step, max_step)
            delta_y = generator.uniform(-max_step, max_step)
        delta_x = round(delta_x) + generator.choice(fractions)
        delta_y = round(delta_y) + generator.choice(fractions)
        current += QPointF(delta_x, delta_y)
        pans.append(QPointF(current))
    return tuple(pans)


def _copy_region_onto_reference(
    actual: QImage,
    reference: QImage,
    region: QRegion,
) -> QImage:
    """Return actual valid pixels over an otherwise clean reference frame."""
    if actual.size() != reference.size():
        raise ValueError("actual and reference frame sizes must match")
    actual_pixels = _rgba_pixels(actual)
    combined = _rgba_pixels(reference)
    bounds = QRect(0, 0, actual.width(), actual.height())
    for rect in region:
        clipped = rect.intersected(bounds)
        if clipped.isEmpty():
            continue
        y_slice = slice(clipped.top(), clipped.bottom() + 1)
        x_slice = slice(clipped.left(), clipped.right() + 1)
        combined[y_slice, x_slice] = actual_pixels[y_slice, x_slice]
    return _image_from_rgba(combined)


def _rgba_pixels(image: QImage) -> np.ndarray:
    """Return a copied height-by-width RGBA array for ``image``."""
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    buffer = np.frombuffer(
        converted.constBits(),
        dtype=np.uint8,
        count=converted.sizeInBytes(),
    )
    rows = buffer.reshape(converted.height(), converted.bytesPerLine())
    return (
        rows[:, : converted.width() * 4]
        .reshape(converted.height(), converted.width(), 4)
        .copy()
    )


def _image_from_rgba(pixels: np.ndarray) -> QImage:
    """Return an owned QImage copy of a contiguous RGBA array."""
    contiguous = np.ascontiguousarray(pixels, dtype=np.uint8)
    height, width, _channels = contiguous.shape
    return QImage(
        contiguous.data,
        width,
        height,
        int(contiguous.strides[0]),
        QImage.Format.Format_RGBA8888,
    ).copy()


def _contiguous_spans(indices: np.ndarray) -> tuple[tuple[int, int], ...]:
    """Collapse sorted integer indices into inclusive contiguous spans."""
    if indices.size == 0:
        return ()
    spans: list[tuple[int, int]] = []
    start = previous = int(indices[0])
    for value in indices[1:]:
        current = int(value)
        if current != previous + 1:
            spans.append((start, previous))
            start = current
        previous = current
    spans.append((start, previous))
    return tuple(spans)


def _parse_args(arguments: Sequence[str]) -> argparse.Namespace:
    """Parse command-line options for a headless pan-abuse run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--viewport-width", type=int, default=512)
    parser.add_argument("--viewport-height", type=int, default=512)
    parser.add_argument("--image-width", type=int, default=2048)
    parser.add_argument("--image-height", type=int, default=2048)
    parser.add_argument("--dpr", type=float, default=1.0)
    parser.add_argument("--zoom", type=float, default=1.0)
    parser.add_argument("--tolerance", type=int, default=0)
    parser.add_argument("--max-step", type=float, default=24.0)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("pan-harness-artifacts"),
    )
    parser.add_argument("--keep-going", action="store_true")
    return parser.parse_args(arguments)


def _load_probe_image(arguments: argparse.Namespace) -> QImage:
    """Load the requested image or create the default diagnostic pattern."""
    if arguments.image is None:
        return coordinate_fingerprint_image(
            QSize(arguments.image_width, arguments.image_height)
        )
    image = QImage(str(arguments.image))
    if image.isNull():
        raise ValueError(f"could not load image: {arguments.image}")
    return image


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the differential pan harness and report the first mismatching frame."""
    options = _parse_args(arguments if arguments is not None else sys.argv[1:])
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    harness = HeadlessPanHarness(
        application,
        _load_probe_image(options),
        viewport_size=QSize(options.viewport_width, options.viewport_height),
        device_pixel_ratio=options.dpr,
        zoom=options.zoom,
        channel_tolerance=options.tolerance,
        artifact_root=options.artifact_root,
    )
    try:
        failures = harness.run(
            random_walk_pans(
                steps=options.steps,
                seed=options.seed,
                max_step=options.max_step,
            ),
            stop_on_failure=not options.keep_going,
        )
    finally:
        harness.close()
    if not failures:
        print(
            f"PASS: {options.steps} pan steps matched full redraws "
            f"at DPR {options.dpr:g}."
        )
        return 0
    first = failures[0]
    print(
        f"FAIL: {len(failures)} mismatching pan frame(s); first at step "
        f"{first.step_index} with {first.difference.mismatch_pixels} pixels."
    )
    print(f"Artifacts: {first.artifact_directory.resolve()}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
