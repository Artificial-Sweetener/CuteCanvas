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

"""Observe every mounted frame during provisional-to-durable stroke release."""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest

from .mounted_qpane import MountedQPaneHarness


@dataclass(frozen=True, slots=True)
class ReleaseFrame:
    """Pair one distinct release frame with its elapsed presentation time."""

    elapsed_ms: float
    image: QImage
    mask_render: QImage


@dataclass(frozen=True, slots=True)
class ReleaseTransition:
    """Summarize temporal frame continuity from pointer-up through render idle."""

    frames: tuple[ReleaseFrame, ...]
    settled: bool
    worst_frame_index: int
    changed_pixels: int
    maximum_channel_delta: int
    missing_required_point: QPoint | None


class ReleaseTransitionProbe:
    """Measure post-release frame changes without draining past the transition."""

    def __init__(self, harness: MountedQPaneHarness) -> None:
        """Bind the probe to one mounted production pane."""
        self._harness = harness

    def observe(
        self,
        *,
        required_points: tuple[QPoint, ...] = (),
        timeout_ms: int = 3000,
    ) -> ReleaseTransition:
        """Capture mask and composite evidence until all render owners become idle."""
        started_at = time.perf_counter()
        first = self._harness.viewer.grab().toImage()
        first_mask_render = self._harness.capture_active_mask_render()
        frames = [ReleaseFrame(0.0, first, first_mask_render)]
        deadline = started_at + timeout_ms / 1000.0
        idle_turns = 0
        settled = False
        while time.perf_counter() < deadline:
            self._harness.qapp.processEvents()
            current = self._harness.viewer.grab().toImage()
            current_mask_render = self._harness.capture_active_mask_render()
            if (
                current != frames[-1].image
                or current_mask_render != frames[-1].mask_render
            ):
                frames.append(
                    ReleaseFrame(
                        (time.perf_counter() - started_at) * 1000.0,
                        current,
                        current_mask_render,
                    )
                )
            service = getattr(self._harness.viewer, "mask_service", None)
            busy = service is None or service.hasPendingRenderWork()
            idle_turns = 0 if busy else idle_turns + 1
            if idle_turns >= 2:
                settled = True
                break
            QTest.qWait(1)
        worst_index, changed_pixels, maximum_delta = self._worst_mask_delta(frames)
        missing_required_point = self._first_missing_required_point(
            frames,
            required_points,
        )
        return ReleaseTransition(
            frames=tuple(frames),
            settled=settled,
            worst_frame_index=worst_index,
            changed_pixels=changed_pixels,
            maximum_channel_delta=maximum_delta,
            missing_required_point=missing_required_point,
        )

    @staticmethod
    def _worst_mask_delta(
        frames: list[ReleaseFrame],
    ) -> tuple[int, int, int]:
        """Return the largest mask-render delta from the first release frame."""
        baseline = _image_array(frames[0].mask_render)
        worst_index = 0
        worst_count = 0
        worst_delta = 0
        for index, frame in enumerate(frames[1:], start=1):
            candidate = _image_array(frame.mask_render)
            if candidate.shape != baseline.shape:
                changed_count = max(
                    baseline.shape[0] * baseline.shape[1],
                    candidate.shape[0] * candidate.shape[1],
                )
                maximum_delta = 255
                if (changed_count, maximum_delta) > (worst_count, worst_delta):
                    worst_index = index
                    worst_count = changed_count
                    worst_delta = maximum_delta
                continue
            channel_delta = np.abs(
                baseline.astype(np.int16) - candidate.astype(np.int16)
            )
            changed = np.any(channel_delta > 2, axis=2)
            changed_count = int(np.count_nonzero(changed))
            maximum_delta = int(channel_delta[changed].max()) if changed_count else 0
            if (changed_count, maximum_delta) > (worst_count, worst_delta):
                worst_index = index
                worst_count = changed_count
                worst_delta = maximum_delta
        return worst_index, worst_count, worst_delta

    def _first_missing_required_point(
        self,
        frames: list[ReleaseFrame],
        required_points: tuple[QPoint, ...],
    ) -> QPoint | None:
        """Return the first semantic mask sample absent from a composite frame."""
        for frame in frames:
            for point in required_points:
                if not self._harness.is_mask_tint(frame.image.pixelColor(point)):
                    return QPoint(point)
        return None


def _image_array(image: QImage) -> np.ndarray:
    """Return a detached BGRA view of one captured widget frame."""
    if image.isNull():
        return np.empty((0, 0, 4), dtype=np.uint8)
    converted = image.convertToFormat(QImage.Format.Format_ARGB32)
    rows = np.frombuffer(converted.constBits(), dtype=np.uint8).reshape(
        converted.height(), converted.bytesPerLine()
    )
    pixels = rows[:, : converted.width() * 4].reshape(
        converted.height(), converted.width(), 4
    )
    return np.array(pixels, copy=True)
