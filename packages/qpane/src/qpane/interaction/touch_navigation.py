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
"""Direct-manipulation calculations for touch viewport navigation."""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import QPointF, QRectF


class DirectManipulationViewport(Protocol):
    """Viewport behavior required by touch navigation."""

    zoom: float
    pan: QPointF

    def is_locked(self) -> bool:
        """Return whether direct viewport navigation is disabled."""
        ...

    def stop_transient_motion(self) -> None:
        """Stop kinetic or animated viewport movement."""
        ...

    def apply_direct_manipulation(self, zoom: float, pan: QPointF) -> None:
        """Apply one immediate touch-derived viewport state."""
        ...

    def start_translation_inertia(
        self,
        velocity: QPointF,
        deceleration: float,
    ) -> bool:
        """Begin kinetic translation after touch release."""
        ...


@dataclass(frozen=True, slots=True)
class TouchNavigationPort:
    """Supply source-neutral viewport and host geometry to touch navigation."""

    viewport: Callable[[], DirectManipulationViewport]
    device_pixel_ratio: Callable[[], float]
    physical_viewport_rect: Callable[[], QRectF]
    inertia_enabled: Callable[[], bool]
    inertia_deceleration: Callable[[], float]


class TouchNavigationSession:
    """Keep touch contacts anchored while applying incremental pan and zoom."""

    def __init__(self, port: TouchNavigationPort) -> None:
        """Capture the focused viewport collaboration boundary."""
        self._port = port
        self._baseline_points: dict[int, QPointF] = {}
        self._baseline_zoom = 1.0
        self._baseline_pan = QPointF()
        self._last_update_at: float | None = None
        self._translation_velocities: deque[QPointF] = deque(maxlen=4)

    @property
    def active(self) -> bool:
        """Return whether the session currently owns touch contacts."""
        return bool(self._baseline_points)

    def update(
        self,
        points: Mapping[int, QPointF],
        *,
        timestamp_ms: int | None = None,
    ) -> None:
        """Apply the latest contact geometry or reset when none remain."""
        update_at = self._timestamp_seconds(timestamp_ms)
        current = {point_id: QPointF(point) for point_id, point in points.items()}
        if not current:
            self.reset()
            return
        if current.keys() != self._baseline_points.keys():
            self._rebaseline(current, update_at=update_at, reset_velocity=True)
            return
        viewport = self._port.viewport()
        baseline_centroid = self._centroid(self._baseline_points)
        current_centroid = self._centroid(current)
        self._record_translation_velocity(
            baseline_centroid, current_centroid, update_at
        )
        if len(current) == 1:
            pointer_id = next(iter(current))
            logical_delta = current[pointer_id] - self._baseline_points[pointer_id]
            dpr = self._safe_dpr()
            pan = self._baseline_pan + QPointF(
                logical_delta.x() * dpr,
                logical_delta.y() * dpr,
            )
            viewport.apply_direct_manipulation(self._baseline_zoom, pan)
            self._rebaseline(current, update_at=update_at)
            return
        baseline_distance = self._mean_radius(self._baseline_points, baseline_centroid)
        current_distance = self._mean_radius(current, current_centroid)
        scale = current_distance / baseline_distance if baseline_distance > 0 else 1.0
        requested_zoom = self._baseline_zoom * scale
        dpr = self._safe_dpr()
        baseline_physical = QPointF(
            baseline_centroid.x() * dpr,
            baseline_centroid.y() * dpr,
        )
        current_physical = QPointF(
            current_centroid.x() * dpr,
            current_centroid.y() * dpr,
        )
        panel_center = self._port.physical_viewport_rect().center()
        content_offset = baseline_physical - panel_center - self._baseline_pan
        if self._baseline_zoom > 0:
            content_offset /= self._baseline_zoom
        pan = current_physical - panel_center - content_offset * requested_zoom
        viewport.apply_direct_manipulation(requested_zoom, pan)
        self._rebaseline(current, update_at=update_at)

    def finish(self) -> bool:
        """Release contacts and start configured translation inertia if eligible."""
        velocity = self._average_translation_velocity()
        viewport = self._port.viewport()
        enabled = bool(self._port.inertia_enabled())
        deceleration = float(self._port.inertia_deceleration())
        self.reset()
        if not enabled or velocity.isNull():
            return False
        return viewport.start_translation_inertia(velocity, deceleration)

    def reset(self) -> None:
        """Release all contacts and discard transient gesture geometry."""
        self._baseline_points.clear()
        self._last_update_at = None
        self._translation_velocities.clear()

    def _rebaseline(
        self,
        points: Mapping[int, QPointF],
        *,
        update_at: float,
        reset_velocity: bool = False,
    ) -> None:
        """Anchor subsequent deltas to the current viewport state."""
        viewport = self._port.viewport()
        if not self._baseline_points:
            viewport.stop_transient_motion()
        self._baseline_points = {
            point_id: QPointF(point) for point_id, point in points.items()
        }
        self._baseline_zoom = float(viewport.zoom)
        self._baseline_pan = QPointF(viewport.pan)
        self._last_update_at = update_at
        if reset_velocity:
            self._translation_velocities.clear()

    def _safe_dpr(self) -> float:
        """Return a positive device-pixel ratio."""
        dpr = float(self._port.device_pixel_ratio())
        return dpr if math.isfinite(dpr) and dpr > 0 else 1.0

    @staticmethod
    def _centroid(points: Mapping[int, QPointF]) -> QPointF:
        """Return the arithmetic center of supplied contacts."""
        count = len(points)
        return QPointF(
            sum(point.x() for point in points.values()) / count,
            sum(point.y() for point in points.values()) / count,
        )

    @staticmethod
    def _mean_radius(points: Mapping[int, QPointF], centroid: QPointF) -> float:
        """Return mean contact distance from the gesture centroid."""
        return sum(
            math.hypot(point.x() - centroid.x(), point.y() - centroid.y())
            for point in points.values()
        ) / len(points)

    def _record_translation_velocity(
        self,
        baseline_centroid: QPointF,
        current_centroid: QPointF,
        update_at: float,
    ) -> None:
        """Record one physical translation velocity sample."""
        previous_at = self._last_update_at
        if previous_at is None:
            return
        elapsed = update_at - previous_at
        delta = current_centroid - baseline_centroid
        if elapsed <= 0 or delta.isNull():
            return
        dpr = self._safe_dpr()
        self._translation_velocities.append(
            QPointF(delta.x() * dpr / elapsed, delta.y() * dpr / elapsed)
        )

    def _average_translation_velocity(self) -> QPointF:
        """Return a recency-weighted velocity across recent frames."""
        if not self._translation_velocities:
            return QPointF()
        weights = tuple(range(1, len(self._translation_velocities) + 1))
        weight_sum = sum(weights)
        return QPointF(
            sum(
                velocity.x() * weight
                for velocity, weight in zip(self._translation_velocities, weights)
            )
            / weight_sum,
            sum(
                velocity.y() * weight
                for velocity, weight in zip(self._translation_velocities, weights)
            )
            / weight_sum,
        )

    @staticmethod
    def _timestamp_seconds(timestamp_ms: int | None) -> float:
        """Return monotonic seconds, preferring meaningful Qt event time."""
        if timestamp_ms is not None and timestamp_ms > 0:
            return timestamp_ms / 1000.0
        return time.monotonic()
