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
from dataclasses import dataclass
import json
import os
from pathlib import Path
import random
import sys
from typing import TYPE_CHECKING, Callable, Sequence
import uuid

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, QSize
from PySide6.QtGui import QImage, QPainter, QRegion
from PySide6.QtWidgets import QApplication

from qpane import QPane

if TYPE_CHECKING:
    from qpane.scene.render_plan import SceneRenderPlan


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


@dataclass(frozen=True)
class _RendererBufferSnapshot:
    """Preserve incremental renderer state while a clean oracle is captured."""

    base_buffer: QImage
    buffer_pan: QPointF
    subpixel_pan_offset: QPointF
    dirty_region: QRegion
    current_render_plan: SceneRenderPlan | None


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
    """Compare one QPane's incremental path with its own full-redraw oracle."""

    def __init__(
        self,
        application: QApplication,
        image: QImage,
        *,
        viewport_size: QSize = QSize(512, 512),
        device_pixel_ratio: float = 1.0,
        zoom: float = 1.0,
        channel_tolerance: int = 0,
        artifact_root: Path = Path("pan-harness-artifacts"),
        configure_qpane: Callable[[QPane], None] | None = None,
        features: Sequence[str] = (),
    ) -> None:
        """Mount the offscreen widgets and initialize their identical scenes."""
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
        self._features = tuple(features)
        self._qpane = self._create_qpane(image, viewport_size)
        self._settle_widget()

    def run(
        self,
        pan_sequence: Sequence[QPointF],
        *,
        stop_on_failure: bool = True,
    ) -> list[PanHarnessFailure]:
        """Apply pans and return every incremental-render mismatch found."""
        failures: list[PanHarnessFailure] = []
        requested_history: list[QPointF] = []
        actual_history: list[QPointF] = []
        for step_index, requested_pan in enumerate(pan_sequence):
            requested_history.append(QPointF(requested_pan))
            self._qpane.setPan(requested_pan)
            self._qpane.update()
            self._settle_widget()
            actual_pan = self._qpane.getPan()
            actual_history.append(QPointF(actual_pan))
            actual_frame = self.capture_visible_frame(self._qpane)
            snapshot = self._snapshot_incremental_renderer()
            expected_frame = self._capture_full_redraw_reference()
            self._restore_incremental_renderer(snapshot)
            difference = self._detector.compare(actual_frame, expected_frame)
            if not difference.detected:
                continue
            artifact_directory = self._write_failure_artifacts(
                step_index=step_index,
                requested_pan=requested_pan,
                actual_pan=actual_pan,
                actual_frame=actual_frame,
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
        return failures

    def close(self) -> None:
        """Release the mounted widget and drain its deferred Qt cleanup."""
        self._qpane.close()
        self._qpane.deleteLater()
        self._application.processEvents()

    @staticmethod
    def capture_visible_frame(qpane: QPane) -> QImage:
        """Return the exact viewport crop presented from a QPane render buffer."""
        renderer = qpane.view().renderer
        base_buffer = renderer.get_base_buffer()
        if base_buffer is None:
            raise RuntimeError("QPane has no allocated render buffer")
        viewport_size = renderer._viewport_physical_size
        frame = QImage(
            viewport_size,
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        frame.setDevicePixelRatio(base_buffer.devicePixelRatio())
        frame.fill(0)
        margin = renderer._BUFFER_OVERSCAN_PHYSICAL_PX
        subpixel_offset = renderer.get_subpixel_pan_offset()
        safe_dpr = max(float(base_buffer.devicePixelRatio()), 1.0)
        painter = QPainter(frame)
        try:
            painter.drawImage(
                QRectF(
                    0.0,
                    0.0,
                    viewport_size.width() / safe_dpr,
                    viewport_size.height() / safe_dpr,
                ),
                base_buffer,
                QRectF(
                    margin - subpixel_offset.x(),
                    margin - subpixel_offset.y(),
                    float(viewport_size.width()),
                    float(viewport_size.height()),
                ),
            )
        finally:
            painter.end()
        return frame

    def _create_qpane(self, image: QImage, viewport_size: QSize) -> QPane:
        """Create one configured QPane used by the differential harness."""
        qpane = QPane(features=self._features)
        try:
            device_pixel_ratio = self._device_pixel_ratio
            qpane.devicePixelRatioF = lambda: device_pixel_ratio  # type: ignore[method-assign]
            qpane.resize(viewport_size)
            image_id = uuid.uuid4()
            qpane.setImagesByID(
                QPane.imageMapFromLists([QImage(image)], [None], [image_id]),
                image_id,
            )
            qpane.setZoom1To1()
            if self._configure_qpane is not None:
                self._configure_qpane(qpane)
            qpane.view().viewport.setZoomAndPan(self._zoom, QPointF(0.0, 0.0))
            qpane.show()
            qpane.view().ensure_view_alignment(force=True)
            qpane.markDirty()
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

    def _snapshot_incremental_renderer(self) -> _RendererBufferSnapshot:
        """Capture the buffer identity needed to continue incremental abuse."""
        renderer = self._qpane.view().renderer
        base_buffer = renderer.get_base_buffer()
        if base_buffer is None:
            raise RuntimeError("QPane has no allocated render buffer")
        return _RendererBufferSnapshot(
            base_buffer=QImage(base_buffer),
            buffer_pan=QPointF(renderer._buffer_pan),
            subpixel_pan_offset=QPointF(renderer._subpixel_pan_offset),
            dirty_region=QRegion(renderer._dirty_region),
            current_render_plan=renderer._current_render_plan,
        )

    def _capture_full_redraw_reference(self) -> QImage:
        """Render and capture a clean frame from the same live QPane state."""
        presenter = self._qpane.view().presenter
        presenter.mark_dirty()
        presenter.paint(
            is_blank=False,
            content_overlays={},
            scene_overlays={},
            overlays_suspended=False,
            draw_tool_overlay=None,
        )
        return self.capture_visible_frame(self._qpane)

    def _restore_incremental_renderer(
        self,
        snapshot: _RendererBufferSnapshot,
    ) -> None:
        """Restore the incremental buffer after capturing its redraw oracle."""
        renderer = self._qpane.view().renderer
        renderer._base_image_buffer = QImage(snapshot.base_buffer)
        renderer._buffer_pan = QPointF(snapshot.buffer_pan)
        renderer._subpixel_pan_offset = QPointF(snapshot.subpixel_pan_offset)
        renderer._dirty_region = QRegion(snapshot.dirty_region)
        renderer._current_render_plan = snapshot.current_render_plan

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
    parser.add_argument("--features", nargs="*", default=())
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
        features=options.features,
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
