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

"""Measure PySide6 software backing-store primitives at high resolution."""

from __future__ import annotations

import os
import statistics
import time
from collections.abc import Callable

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1.75")

import numpy as np
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import (
    QBackingStore,
    QGuiApplication,
    QImage,
    QPainter,
    QPixmap,
    QRegion,
    QWindow,
)

_LOGICAL_SIZE = QSize(3840, 2160)
_PHYSICAL_SIZE = QSize(6720, 3780)
_DEVICE_PIXEL_RATIO = 1.75
_SAMPLES = 40


def main() -> int:
    """Measure a full pixmap copy and flush through a software backing store."""
    application = QGuiApplication.instance() or QGuiApplication([])
    window = QWindow()
    window.resize(_LOGICAL_SIZE)
    window.show()
    application.processEvents()
    store = QBackingStore(window)
    store.resize(window.size())
    source = QPixmap(_PHYSICAL_SIZE)
    source.setDevicePixelRatio(_DEVICE_PIXEL_RATIO)
    source.fill(Qt.GlobalColor.blue)
    source_image = source.toImage().convertToFormat(
        QImage.Format.Format_ARGB32_Premultiplied
    )
    region = QRegion(QRect(QPoint(), window.size()))
    store.beginPaint(region)
    device = store.paintDevice()
    try:
        if device is None:
            raise RuntimeError("QBackingStore did not expose a software paint device")
        print(
            f"window={window.width()}x{window.height()} "
            f"dpr={window.devicePixelRatio():g} "
            f"store={store.size().width()}x{store.size().height()} "
            f"device={device.width()}x{device.height()} "
            f"device_dpr={device.devicePixelRatioF():g}"
        )
    finally:
        store.endPaint()

    def paint_and_flush() -> tuple[float, float, float]:
        """Copy one full frame and synchronously flush the backing store."""
        started = time.perf_counter()
        store.beginPaint(region)
        painter = QPainter(store.paintDevice())
        try:
            painter.drawPixmap(QPoint(), source)
        finally:
            painter.end()
        painted = time.perf_counter()
        store.endPaint()
        store.flush(region, window)
        finished = time.perf_counter()
        return (
            (painted - started) * 1000.0,
            (finished - painted) * 1000.0,
            (finished - started) * 1000.0,
        )

    for _index in range(5):
        paint_and_flush()
    samples = [paint_and_flush() for _index in range(_SAMPLES)]
    for index, label in enumerate(("paint", "flush", "total")):
        _print_summary(label, lambda sample, i=index: sample[i], samples)

    def copy_and_flush() -> tuple[float, float, float]:
        """Copy native image bytes directly into the software backing image."""
        started = time.perf_counter()
        store.beginPaint(region)
        target = store.paintDevice()
        if not isinstance(target, QImage):
            store.endPaint()
            raise TypeError("backing-store paint device is not a QImage")
        source_bytes = np.frombuffer(
            source_image.constBits(),
            dtype=np.uint8,
            count=source_image.sizeInBytes(),
        ).reshape(source_image.height(), source_image.bytesPerLine())
        target_bytes = np.frombuffer(
            target.bits(),
            dtype=np.uint8,
            count=target.sizeInBytes(),
        ).reshape(target.height(), target.bytesPerLine())
        np.copyto(
            target_bytes[:, : source_image.width() * 4],
            source_bytes[:, : source_image.width() * 4],
        )
        copied = time.perf_counter()
        store.endPaint()
        store.flush(region, window)
        finished = time.perf_counter()
        return (
            (copied - started) * 1000.0,
            (finished - copied) * 1000.0,
            (finished - started) * 1000.0,
        )

    for _index in range(5):
        copy_and_flush()
    copy_samples = [copy_and_flush() for _index in range(_SAMPLES)]
    for index, label in enumerate(("copy", "flush", "total")):
        _print_summary(
            f"numpy_{label}",
            lambda sample, i=index: sample[i],
            copy_samples,
        )
    for delta in (QPoint(1, 0), QPoint(4, 0), QPoint(-52, 44)):
        scroll_values = []
        results = []
        for _index in range(_SAMPLES):
            started = time.perf_counter()
            results.append(store.scroll(region, delta.x(), delta.y()))
            scroll_values.append((time.perf_counter() - started) * 1000.0)
        ordered = sorted(scroll_values)
        print(
            f"scroll({delta.x():d},{delta.y():d}): "
            f"success={sum(results)}/{len(results)} "
            f"mean={statistics.fmean(ordered):8.3f} "
            f"p95={ordered[min(len(ordered) - 1, 38)]:8.3f} "
            f"max={ordered[-1]:8.3f} ms"
        )
    pixels = np.zeros(
        (_PHYSICAL_SIZE.height(), _PHYSICAL_SIZE.width(), 4),
        dtype=np.uint8,
    )

    def shift_overlapping_pixels(dx: int, dy: int) -> None:
        """Shift one overlapping physical viewport through NumPy's safe copy path."""
        target_x = max(0, dx)
        target_y = max(0, dy)
        source_x = max(0, -dx)
        source_y = max(0, -dy)
        width = _PHYSICAL_SIZE.width() - abs(dx)
        height = _PHYSICAL_SIZE.height() - abs(dy)
        np.copyto(
            pixels[
                target_y : target_y + height,
                target_x : target_x + width,
            ],
            pixels[
                source_y : source_y + height,
                source_x : source_x + width,
            ],
        )

    for _index in range(3):
        shift_overlapping_pixels(-5, 91)
    overlap_samples = []
    for _index in range(20):
        started = time.perf_counter()
        shift_overlapping_pixels(-5, 91)
        overlap_samples.append((time.perf_counter() - started) * 1000.0)
    overlap_samples.sort()
    print(
        "numpy_overlap(-5,91): "
        f"mean={statistics.fmean(overlap_samples):8.3f} "
        f"p95={overlap_samples[18]:8.3f} "
        f"max={overlap_samples[-1]:8.3f} ms"
    )
    window.close()
    return 0


def _print_summary(
    label: str,
    value: Callable[[tuple[float, float, float]], float],
    samples: list[tuple[float, float, float]],
) -> None:
    """Print one nearest-rank primitive timing summary."""
    values = sorted(value(sample) for sample in samples)
    p95_index = min(len(values) - 1, round(len(values) * 0.95))
    print(
        f"{label:>8}: mean={statistics.fmean(values):8.3f} "
        f"p95={values[p95_index]:8.3f} max={values[-1]:8.3f} ms"
    )


if __name__ == "__main__":
    raise SystemExit(main())
