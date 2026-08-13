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

"""Deterministic tests for direct touch viewport manipulation."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from PySide6.QtCore import QPointF, QRectF

from qpane import TouchNavigationPort, TouchNavigationSession


@dataclass
class _Viewport:
    zoom: float = 1.0
    pan: QPointF = field(default_factory=QPointF)
    changes: list[tuple[float, QPointF]] = field(default_factory=list)

    def stop_transient_motion(self) -> None:
        pass

    def apply_direct_manipulation(self, zoom: float, pan: QPointF) -> None:
        self.zoom = zoom
        self.pan = QPointF(pan)
        self.changes.append((zoom, QPointF(pan)))

    def start_translation_inertia(
        self,
        velocity: QPointF,
        deceleration: float,
    ) -> bool:
        del velocity, deceleration
        return True


def _port(viewport: _Viewport, dpr: float = 2.0) -> TouchNavigationPort:
    """Build the focused viewport boundary used by each test."""
    return TouchNavigationPort(
        viewport=lambda: viewport,
        device_pixel_ratio=lambda: dpr,
        physical_viewport_rect=lambda: QRectF(0.0, 0.0, 200.0, 200.0),
        inertia_enabled=lambda: True,
        inertia_deceleration=lambda: 4500.0,
    )


def test_one_finger_pan_tracks_contact_in_physical_pixels() -> None:
    viewport = _Viewport()
    session = TouchNavigationSession(_port(viewport))

    session.update({1: QPointF(20.0, 30.0)})
    session.update({1: QPointF(30.0, 35.0)})

    assert viewport.changes == [(1.0, QPointF(20.0, 10.0))]


def test_two_finger_pinch_keeps_content_under_centroid() -> None:
    viewport = _Viewport()
    session = TouchNavigationSession(_port(viewport))

    session.update({1: QPointF(40.0, 50.0), 2: QPointF(60.0, 50.0)})
    session.update({1: QPointF(50.0, 50.0), 2: QPointF(90.0, 50.0)})

    assert len(viewport.changes) == 1
    zoom, pan = viewport.changes[0]
    assert zoom == pytest.approx(2.0)
    assert pan == QPointF(40.0, 0.0)


def test_contact_count_transitions_rebaseline_without_jumping() -> None:
    viewport = _Viewport()
    session = TouchNavigationSession(_port(viewport))

    session.update({1: QPointF(20.0, 20.0)})
    session.update({1: QPointF(30.0, 20.0)})
    session.update({1: QPointF(30.0, 20.0), 2: QPointF(50.0, 20.0)})
    session.update({1: QPointF(30.0, 20.0)})

    assert viewport.changes == [(1.0, QPointF(20.0, 0.0))]


def test_cancel_discards_gesture_baseline() -> None:
    viewport = _Viewport()
    session = TouchNavigationSession(_port(viewport))

    session.update({1: QPointF(20.0, 20.0)})
    session.reset()
    session.update({1: QPointF(80.0, 80.0)})

    assert session.active
    assert viewport.changes == []
