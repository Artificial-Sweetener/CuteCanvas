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

import pytest
from cutecanvas import Config
from PySide6.QtCore import QObject, QPointF, QRectF, QSize, QSizeF

from qpane.rendering import Viewport, ViewportZoomMode


class DummyViewportHost(QObject):
    def __init__(self, width: int, height: int, dpr: float) -> None:
        super().__init__()
        self._size = QSize(width, height)
        self._dpr = dpr
        self.viewport = None

    def size(self) -> QSize:
        return self._size

    def width(self) -> int:
        return self._size.width()

    def height(self) -> int:
        return self._size.height()

    def devicePixelRatioF(self) -> float:
        return self._dpr

    def physicalViewportRect(self) -> QRectF:
        return QRectF(
            0,
            0,
            self._size.width() * self._dpr,
            self._size.height() * self._dpr,
        )


def _make_viewport(
    *,
    qpane_size: tuple[int, int] = (400, 400),
    dpr: float = 2.0,
    content_size: tuple[int, int] = (600, 600),
    zoom: float = 1.0,
    pan: QPointF | None = None,
) -> tuple[Viewport, DummyViewportHost]:
    config = Config()
    host = DummyViewportHost(*qpane_size, dpr)
    viewport = Viewport(host, config)
    host.viewport = viewport
    viewport.setContentSize(QSize(*content_size))
    viewport.zoom = zoom
    viewport.pan = pan if pan is not None else QPointF(0, 0)
    return viewport, host


def test_clamp_pan_respects_physical_extents():
    viewport, host = _make_viewport()
    pan = QPointF(200, 0)
    panel_size = QSizeF(host.physicalViewportRect().size())
    clamped = viewport.clampPan(pan, viewport.zoom, panel_size, viewport.content_size)
    assert clamped.x() == pytest.approx(0.0)
    assert clamped.y() == pytest.approx(0.0)


def test_apply_zoom_recenters_when_image_fits_physical_view():
    viewport, _ = _make_viewport(pan=QPointF(50, -25))
    viewport.applyZoom(1.0)
    assert viewport.pan.x() == pytest.approx(0.0)
    assert viewport.pan.y() == pytest.approx(0.0)


def test_custom_zoom_uses_the_configured_authoritative_ceiling() -> None:
    """Clamp custom zoom through the viewport's scene-aware bound provider."""

    viewport, _ = _make_viewport()
    viewport.configure_maximum_zoom(lambda: 20.0)

    viewport.applyZoom(1000.0)

    assert viewport.zoom == pytest.approx(20.0)


def test_custom_zoom_below_minimum_canvas_size_remains_available() -> None:
    """Apply API zoom-out without touch manipulation's minimum-size clamp."""

    viewport, _ = _make_viewport(content_size=(64, 64), zoom=10.0)

    viewport.applyZoom(0.5)

    assert viewport.zoom == pytest.approx(0.5)


def test_pan_and_zoom_mutators_respect_lock_state():
    viewport, _ = _make_viewport(dpr=1.5, pan=QPointF(10, 12), zoom=0.5)
    viewport.set_locked(True)
    viewport.setPan(QPointF(250, -80))
    assert viewport.pan == QPointF(10, 12)
    viewport.setZoomAndPan(2.0, QPointF(0, 0))
    assert viewport.zoom == pytest.approx(0.5)
    assert viewport.pan == QPointF(10, 12)
    viewport.setZoomFit()
    assert viewport.zoom == pytest.approx(0.5)
    assert viewport.pan == QPointF(10, 12)
    viewport.setZoom1To1()
    assert viewport.zoom == pytest.approx(0.5)
    assert viewport.pan == QPointF(10, 12)


def test_set_zoom_and_pan_commits_one_atomic_view_change():
    """Zoom and pan should publish one coherent viewport state."""
    viewport, _ = _make_viewport(
        dpr=1.0,
        content_size=(1200, 1200),
        zoom=1.0,
        pan=QPointF(0, 0),
    )
    snapshots: list[tuple[float, QPointF]] = []
    viewport.viewChanged.connect(
        lambda: snapshots.append((viewport.zoom, QPointF(viewport.pan)))
    )

    viewport.setZoomAndPan(2.0, QPointF(75, -50))

    assert snapshots == [(2.0, QPointF(75, -50))]


def test_pan_commit_removes_arithmetic_residue() -> None:
    """Equivalent pan calculations should resolve to one render coordinate."""
    viewport, _ = _make_viewport(
        dpr=1.0,
        content_size=(1200, 1200),
        zoom=2.0,
    )

    viewport.setPan(QPointF(2.7291666666667425, -2.0e-13))

    assert viewport.pan == QPointF(2.729166667, 0.0)


def test_noop_direct_manipulation_preserves_semantic_zoom_mode() -> None:
    """A stationary touch update must not turn Fit into Custom mode."""
    viewport, _ = _make_viewport(
        dpr=1.0,
        content_size=(1200, 800),
        zoom=0.25,
        pan=QPointF(),
    )
    viewport.zoom_mode = ViewportZoomMode.FIT

    viewport.apply_direct_manipulation(0.25, QPointF())

    assert viewport.zoom == pytest.approx(0.25)
    assert viewport.pan == QPointF()
    assert viewport.get_zoom_mode() is ViewportZoomMode.FIT


def test_fit_mode_rejects_pan_after_near_exact_fit():
    viewport, _ = _make_viewport(
        qpane_size=(593, 887),
        dpr=1.0,
        content_size=(2048, 3072),
        zoom=0.28873697916666674,
    )
    viewport.zoom_mode = ViewportZoomMode.FIT
    viewport.fit_zoom = 887 / 3072

    assert viewport.can_pan() is False

    viewport.setPan(QPointF(0, 50))

    assert viewport.pan == QPointF(0, 0)


def test_clamp_pan_treats_near_zero_overflow_as_fitting():
    viewport, _ = _make_viewport(
        qpane_size=(593, 887),
        dpr=1.0,
        content_size=(2048, 3072),
        zoom=0.28873697916666674,
    )
    clamped = viewport.clampPan(
        QPointF(0, 50),
        0.28873697916666674,
        QSizeF(593, 887),
        QSize(2048, 3072),
    )

    assert clamped == QPointF(0, 0)


def test_custom_mode_allows_pan_with_meaningful_overflow():
    viewport, _ = _make_viewport(
        qpane_size=(593, 887),
        dpr=1.0,
        content_size=(2048, 3072),
        zoom=0.5,
    )
    viewport.zoom_mode = ViewportZoomMode.CUSTOM

    assert viewport.can_pan() is True

    clamped = viewport.clampPan(
        QPointF(20, 30),
        viewport.zoom,
        QSizeF(593, 887),
        viewport.content_size,
    )
    assert clamped == QPointF(20, 30)
