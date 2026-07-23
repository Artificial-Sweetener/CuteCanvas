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
"""Mounted characterization for QPane's built-in and extension tools."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from qpane import QPane
from qpane.interaction import NavigationInteractionPort, PanZoomTool, ViewerTool
from qpane.rendering import ViewportZoomMode


@pytest.fixture()
def viewer(qapp) -> Iterator[QPane]:
    """Provide one mounted-independent viewer and dispose it after the test."""
    del qapp
    widget = QPane()
    yield widget
    widget.close()
    widget.deleteLater()


class _WheelEvent:
    """Minimal deterministic wheel event used for navigation policy tests."""

    def __init__(self, delta: int) -> None:
        self._delta = delta
        self.accepted = False

    def angleDelta(self) -> QPoint:
        """Return the configured vertical wheel delta."""
        return QPoint(0, self._delta)

    def position(self) -> QPointF:
        """Return a stable logical anchor."""
        return QPointF(20.0, 30.0)

    def accept(self) -> None:
        """Record event consumption."""
        self.accepted = True


def test_navigation_wheel_preserves_historical_factor_and_native_snap() -> None:
    """Wheel steps should remain 1.25x and snap when crossing native scale."""
    tool = PanZoomTool()
    zooms: list[float] = []
    snaps: list[tuple[float, object]] = []
    current_zoom = 0.9
    tool.activate(
        NavigationInteractionPort(
            is_navigation_locked=lambda: False,
            is_content_empty=lambda: False,
            get_zoom=lambda: current_zoom,
            get_native_zoom=lambda: 1.0,
            get_fit_zoom=lambda: 0.25,
        )
    )
    tool.signals.zoom_requested.connect(lambda zoom, _anchor: zooms.append(zoom))
    tool.signals.zoom_snap_requested.connect(
        lambda zoom, _anchor, mode: snaps.append((zoom, mode))
    )

    event = _WheelEvent(120)
    tool.wheelEvent(event)  # type: ignore[arg-type]

    assert zooms == []
    assert snaps == [(1.0, ViewportZoomMode.ONE_TO_ONE)]
    assert event.accepted


def test_navigation_double_tap_toggles_fit_and_one_to_one() -> None:
    """Double-tap policy should toggle semantic modes, not arbitrary scales."""
    tool = PanZoomTool()
    calls: list[object] = []
    mode = ViewportZoomMode.FIT
    tool.activate(
        NavigationInteractionPort(
            is_navigation_locked=lambda: False,
            is_content_empty=lambda: False,
            get_zoom_mode=lambda: mode,
            set_zoom_fit_interpolated=lambda: calls.append("fit"),
            set_zoom_one_to_one_interpolated=lambda point: calls.append(point),
        )
    )

    assert tool.handle_double_tap(QPointF(14.0, 9.0))
    assert calls == [QPointF(14.0, 9.0)]

    mode = ViewportZoomMode.CUSTOM
    assert tool.handle_double_tap(QPointF())
    assert calls[-1] == "fit"


def test_mounted_viewer_double_click_toggles_native_and_fit(
    qapp,
    viewer: QPane,
) -> None:
    """The public widget should ship with the real Pan/Zoom tool active."""
    viewer.resize(640, 480)
    viewer.setImage(QImage(1280, 960, QImage.Format.Format_RGBA8888))
    viewer.show()
    qapp.processEvents()
    QTest.mouseDClick(viewer, Qt.MouseButton.LeftButton, pos=viewer.rect().center())
    QTest.qWait(100)
    assert viewer.viewport.get_zoom_mode() is ViewportZoomMode.ONE_TO_ONE
    QTest.mouseDClick(viewer, Qt.MouseButton.LeftButton, pos=viewer.rect().center())
    QTest.qWait(100)
    assert viewer.viewport.get_zoom_mode() is ViewportZoomMode.FIT


def test_mounted_viewer_custom_tool_is_fault_contained(
    viewer: QPane,
    caplog,
) -> None:
    """A failing host extension must not escape into the Qt event loop."""

    class ExplodingTool(ViewerTool):
        """Raise on presses to exercise the public extension boundary."""

        def mousePressEvent(self, event: QMouseEvent) -> None:
            """Raise a representative host extension error."""
            del event
            raise RuntimeError("extension failed")

    viewer.registerTool("explode", ExplodingTool)
    viewer.setControlMode("explode")
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(1.0, 1.0),
        QPointF(1.0, 1.0),
        QPointF(1.0, 1.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    viewer.mousePressEvent(event)

    assert "raised during mousePressEvent" in caplog.text
    assert viewer.controlMode() == "explode"


def test_failed_tool_activation_preserves_the_active_tool(viewer: QPane) -> None:
    """A bad extension activation must not corrupt the working mode."""

    class BrokenActivation(ViewerTool):
        """Represent an extension that rejects its activation boundary."""

        def activate(self, dependencies: object) -> None:
            """Fail before the tool can become active."""
            del dependencies
            raise RuntimeError("activation failed")

    viewer.registerTool("broken", BrokenActivation)

    with pytest.raises(RuntimeError, match="activation failed"):
        viewer.setControlMode("broken")

    assert viewer.controlMode() == viewer.CONTROL_MODE_PANZOOM


def test_blank_viewer_ignores_navigation_wheel(viewer: QPane) -> None:
    """Blank content must remain stable under navigation input."""
    event = QWheelEvent(
        QPointF(10.0, 10.0),
        QPointF(10.0, 10.0),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )

    viewer.wheelEvent(event)

    assert viewer.currentZoom() == pytest.approx(1.0)
