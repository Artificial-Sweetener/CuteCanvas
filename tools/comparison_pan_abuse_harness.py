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

"""Abuse native comparison pan rendering against a same-state full redraw."""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from cutecanvas.document import CanvasDocument
from cutecanvas.presentation import CanvasWorkspace
from PySide6.QtCore import QBuffer, QEvent, QIODevice, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tools.pan_render_harness import (
    FrameArtifactDetector,
    FrameDifference,
    coordinate_fingerprint_image,
)


@dataclass(frozen=True, slots=True)
class ComparisonPanAbuseResult:
    """Describe the final retained frame and its canonical redraw."""

    retained: QImage
    canonical: QImage
    difference: FrameDifference


class NativeComparisonPanHarness:
    """Drive a visible native comparison through hostile wheel and pan input."""

    _PAN_DELTAS = (
        QPoint(420, -280),
        QPoint(420, -280),
        QPoint(420, -280),
        QPoint(-560, 360),
        QPoint(-560, 360),
        QPoint(-560, 360),
        QPoint(-560, 360),
        QPoint(480, -320),
        QPoint(480, -320),
    )

    def __init__(self, application: QApplication) -> None:
        """Bind the native Qt application used for the bounded probe."""
        self._application = application
        self._document = CanvasDocument()
        primary = coordinate_fingerprint_image(QSize(960, 1344))
        secondary = coordinate_fingerprint_image(QSize(1144, 1608))
        secondary.invertPixels(QImage.InvertMode.InvertRgb)
        self._primary_id = self._document.create_composition_from_image(primary)
        self._secondary_id = self._document.create_composition_from_image(secondary)
        self._workspace = CanvasWorkspace(document=self._document, features=())

    def run(self) -> ComparisonPanAbuseResult:
        """Return the retained-versus-redraw result after the accepted abuse path."""
        workspace = self._workspace
        workspace.resize(1152, 1104)
        workspace.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        workspace.move(20, 20)
        workspace.setComparisonPresentation(
            self._primary_id,
            self._secondary_id,
            split_position=0.5,
        )
        workspace.show()
        workspace.raise_()
        workspace.activateWindow()
        ctypes.windll.user32.SetForegroundWindow(int(workspace.winId()))
        QTest.qWait(500)
        pane = workspace.currentCanvas()
        if pane is None or not pane.comparisonState().enabled:
            raise RuntimeError("native comparison pane did not mount")
        self._zoom(pane)
        QTest.qWait(300)
        self._pan(pane)
        for _step in range(5):
            QTest.qWait(20)
            self._capture_native_surface(pane)
        QTest.qWait(500)
        retained = pane.grab().toImage()
        pane._rendering.presenter.renderer.markDirty()
        pane.repaint()
        self._application.processEvents()
        canonical = pane.grab().toImage()
        difference = FrameArtifactDetector(channel_tolerance=1).compare(
            retained,
            canonical,
        )
        return ComparisonPanAbuseResult(retained, canonical, difference)

    def close(self) -> None:
        """Release the workspace, document, and queued native resources."""
        self._workspace.close()
        self._document.close()
        self._application.processEvents()

    def _zoom(self, pane) -> None:
        """Zoom through the production top-level wheel path."""
        anchor = QPointF(pane.width() * 0.72, pane.height() * 0.38)
        window = pane.window()
        window_handle = window.windowHandle()
        if window_handle is None:
            raise RuntimeError("native comparison has no top-level window")
        window_anchor = pane.mapTo(window, anchor.toPoint())
        for _step in range(8):
            QTest.wheelEvent(
                window_handle,
                window_anchor,
                QPoint(0, 120),
                QPoint(),
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.ScrollUpdate,
            )
            QTest.qWait(10)
            self._capture_native_surface(pane)

    def _pan(self, pane) -> None:
        """Traverse most of the available pan range in both directions."""
        start = QPoint(pane.width() * 3 // 4, pane.height() // 2)
        for delta in self._PAN_DELTAS:
            self._send_mouse(
                pane,
                QEvent.Type.MouseButtonPress,
                start,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
            )
            for step in range(1, 13):
                position = start + QPoint(
                    delta.x() * step // 12,
                    delta.y() * step // 12,
                )
                self._send_mouse(
                    pane,
                    QEvent.Type.MouseMove,
                    position,
                    Qt.MouseButton.NoButton,
                    Qt.MouseButton.LeftButton,
                )
                QTest.qWait(10)
                self._capture_native_surface(pane)
            self._send_mouse(
                pane,
                QEvent.Type.MouseButtonRelease,
                start + delta,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
            )
            QTest.qWait(20)

    def _send_mouse(
        self,
        pane,
        event_type: QEvent.Type,
        position: QPoint,
        button: Qt.MouseButton,
        buttons: Qt.MouseButton,
    ) -> None:
        """Deliver one explicit held-button sample through QPane."""
        self._application.sendEvent(
            pane,
            QMouseEvent(
                event_type,
                QPointF(position),
                QPointF(pane.mapToGlobal(position)),
                button,
                buttons,
                Qt.KeyboardModifier.NoModifier,
            ),
        )

    @staticmethod
    def _capture_native_surface(pane) -> QImage:
        """Capture actual desktop pixels without asking QPane to repaint."""
        screen = pane.window().screen()
        if screen is None:
            raise RuntimeError("native comparison window has no screen")
        origin = pane.mapToGlobal(QPoint())
        pixmap = screen.grabWindow(
            0,
            origin.x(),
            origin.y(),
            pane.width(),
            pane.height(),
        )
        if pixmap.isNull():
            raise RuntimeError("native comparison surface capture failed")
        encoded = QBuffer()
        encoded.open(QIODevice.OpenModeFlag.WriteOnly)
        if not pixmap.save(encoded, "PNG"):
            raise RuntimeError("native comparison surface serialization failed")
        encoded.close()
        return pixmap.toImage()


def _write_failure_artifacts(
    root: Path,
    result: ComparisonPanAbuseResult,
) -> None:
    """Write the retained, canonical, difference, and metric artifacts."""
    root.mkdir(parents=True, exist_ok=True)
    result.retained.save(str(root / "retained.png"))
    result.canonical.save(str(root / "canonical.png"))
    FrameArtifactDetector(channel_tolerance=1).difference_image(
        result.retained,
        result.canonical,
    ).save(str(root / "difference.png"))
    difference = result.difference
    bounds = difference.mismatch_bounds
    (root / "result.json").write_text(
        json.dumps(
            {
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
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _parse_args(arguments: list[str]) -> argparse.Namespace:
    """Parse explicit desktop permission and the optional artifact destination."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument(
        "--allow-desktop-window",
        action="store_true",
        help="allow the probe to show and foreground a native desktop window",
    )
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    """Run the native abuse path and return failure for any divergent pixel."""
    if sys.platform != "win32":
        raise RuntimeError("native comparison pan abuse currently requires Windows")
    options = _parse_args(sys.argv[1:] if arguments is None else arguments)
    if not options.allow_desktop_window:
        raise RuntimeError(
            "native comparison pan abuse requires explicit --allow-desktop-window"
        )
    application = QApplication.instance() or QApplication([])
    harness = NativeComparisonPanHarness(application)
    try:
        result = harness.run()
    finally:
        harness.close()
    if result.difference.detected and options.artifact_root is not None:
        _write_failure_artifacts(options.artifact_root, result)
    print(
        json.dumps(
            {
                "detected": result.difference.detected,
                "mismatch_pixels": result.difference.mismatch_pixels,
                "max_channel_delta": result.difference.max_channel_delta,
            }
        )
    )
    return 1 if result.difference.detected else 0


if __name__ == "__main__":
    raise SystemExit(main())
