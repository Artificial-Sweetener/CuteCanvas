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
"""Exercise CuteCanvas resize invariants in a fresh fractional-DPR process."""

from __future__ import annotations

import json
import math

from cutecanvas import CuteCanvas
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
from qpane.sdk.rendering import ViewportZoomMode

from tests.harness.viewport_resize_probe import MountedViewportResizeProbe

RESULT_PREFIX = "VIEWPORT_RESIZE_DPI_RESULT="


def main() -> None:
    """Run the mounted hostile sequence and emit machine-readable evidence."""
    app = QApplication.instance() or QApplication([])
    canvas = CuteCanvas(features=())
    canvas.resize(800, 600)
    image = QImage(1600, 1200, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(32, 64, 96, 255))
    canvas.createCompositionFromImage(image, title="High-DPI resize probe")
    canvas.show()
    app.processEvents()
    try:
        view = canvas.view()
        viewport = view.viewport
        viewport.zoom_mode = ViewportZoomMode.CUSTOM
        viewport.setZoomAndPan(1.375, QPointF(143.0, -97.0))
        app.processEvents()
        probe = MountedViewportResizeProbe(app, canvas, view, viewport)
        observations = (
            probe.capture("initial"),
            probe.resize_and_capture("shrink", QSize(503, 311)),
            probe.resize_and_capture("tiny", QSize(17, 19)),
            probe.resize_and_capture("grow", QSize(1201, 907)),
            probe.resize_and_capture("restore", QSize(800, 600)),
        )
        expected = observations[0]
        for observation in observations[1:]:
            values = (
                observation.zoom,
                observation.pan.x(),
                observation.pan.y(),
                observation.scene_center.x(),
                observation.scene_center.y(),
                observation.scene_basis_scale.x(),
                observation.scene_basis_scale.y(),
            )
            expected_values = (
                expected.zoom,
                expected.pan.x(),
                expected.pan.y(),
                expected.scene_center.x(),
                expected.scene_center.y(),
                expected.scene_basis_scale.x(),
                expected.scene_basis_scale.y(),
            )
            if not all(
                math.isclose(actual, wanted, rel_tol=1e-9, abs_tol=1e-9)
                for actual, wanted in zip(values, expected_values, strict=True)
            ):
                raise AssertionError(observations)
        print(
            RESULT_PREFIX
            + json.dumps(
                {
                    "device_pixel_ratio": canvas.devicePixelRatioF(),
                    "physical_sizes": [
                        [item.physical_size.width(), item.physical_size.height()]
                        for item in observations
                    ],
                    "zooms": [item.zoom for item in observations],
                    "scene_basis_scales": [
                        [
                            item.scene_basis_scale.x(),
                            item.scene_basis_scale.y(),
                        ]
                        for item in observations
                    ],
                }
            )
        )
    finally:
        canvas.close()
        canvas.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    main()
