#    CuteCanvas - High-performance layered image editor
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
"""Deterministic hysteretic snapping shared by editor movement workflows."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF

from .model import (
    SnapAxis,
    SnapCandidate,
    SnapFeatureKind,
    SnapGrid,
    SnapGuide,
    SnapResult,
)


@dataclass(frozen=True, slots=True)
class _AxisLock:
    """Retain one axis target through small pointer reversals."""

    moving_kind: SnapFeatureKind
    candidate: SnapCandidate


class SnapSession:
    """Resolve one drag with device-pixel thresholds and stable axis locks."""

    def __init__(
        self,
        source_owner_id: str,
        source_bounds: QRectF,
        candidates: tuple[SnapCandidate, ...],
        *,
        threshold_device_pixels: float = 8.0,
        release_device_pixels: float = 4.0,
        grid: SnapGrid | None = None,
    ) -> None:
        """Capture immutable gesture geometry and stationary candidates."""
        if threshold_device_pixels <= 0.0 or release_device_pixels < 0.0:
            raise ValueError("snap thresholds must be positive and non-negative")
        self._source_owner_id = str(source_owner_id)
        self._source_bounds = QRectF(source_bounds).normalized()
        candidates = tuple(
            candidate
            for candidate in candidates
            if candidate.owner_id != self._source_owner_id
        )
        self._candidates_by_axis = {
            SnapAxis.X: tuple(
                candidate for candidate in candidates if candidate.axis is SnapAxis.X
            ),
            SnapAxis.Y: tuple(
                candidate for candidate in candidates if candidate.axis is SnapAxis.Y
            ),
        }
        self._threshold_pixels = float(threshold_device_pixels)
        self._release_pixels = float(release_device_pixels)
        self._grid = grid
        self._x_lock: _AxisLock | None = None
        self._y_lock: _AxisLock | None = None

    def resolve(
        self,
        proposed_delta: QPointF,
        *,
        scene_units_per_device_pixel: float,
        suppressed: bool = False,
    ) -> SnapResult:
        """Return independently snapped axes for one proposed scene delta."""
        scale = float(scene_units_per_device_pixel)
        if scale <= 0.0:
            raise ValueError("scene units per device pixel must be positive")
        delta = QPointF(proposed_delta)
        if suppressed:
            return SnapResult(delta)
        threshold = self._threshold_pixels * scale
        release = (self._threshold_pixels + self._release_pixels) * scale
        x, self._x_lock = self._resolve_axis(
            SnapAxis.X,
            delta.x(),
            threshold,
            release,
            self._x_lock,
        )
        y, self._y_lock = self._resolve_axis(
            SnapAxis.Y,
            delta.y(),
            threshold,
            release,
            self._y_lock,
        )
        guides = tuple(
            self._guide(axis, lock, QPointF(x, y))
            for axis, lock in (
                (SnapAxis.X, self._x_lock),
                (SnapAxis.Y, self._y_lock),
            )
            if lock is not None
        )
        return SnapResult(
            QPointF(x, y),
            guides,
            snapped_x=self._x_lock is not None,
            snapped_y=self._y_lock is not None,
        )

    def _resolve_axis(
        self,
        axis: SnapAxis,
        raw_delta: float,
        threshold: float,
        release: float,
        locked: _AxisLock | None,
    ) -> tuple[float, _AxisLock | None]:
        """Resolve one axis with deterministic ties and hysteresis."""
        features = _moving_features(self._source_bounds, axis, raw_delta)
        if locked is not None:
            moving_position = dict(features)[locked.moving_kind]
            correction = locked.candidate.position - moving_position
            if abs(correction) <= release:
                resolved = raw_delta + correction
                return resolved, locked
        matches = []
        candidates = (
            *self._candidates_by_axis[axis],
            *self._grid_candidates(axis, features),
        )
        for moving_kind, moving_position in features:
            for candidate in candidates:
                relationship_rank = _relationship_rank(moving_kind, candidate.kind)
                if relationship_rank is None:
                    continue
                correction = candidate.position - moving_position
                if abs(correction) <= threshold:
                    matches.append(
                        (
                            abs(correction),
                            -candidate.priority,
                            relationship_rank,
                            candidate.position,
                            candidate.owner_id,
                            moving_kind,
                            candidate,
                            correction,
                        )
                    )
        if not matches:
            return raw_delta, None
        match = min(matches)
        moving_kind = match[5]
        candidate = match[6]
        correction = match[7]
        new_lock = _AxisLock(moving_kind, candidate)
        resolved = raw_delta + correction
        return resolved, new_lock

    def _grid_candidates(
        self,
        axis: SnapAxis,
        features: tuple[tuple[SnapFeatureKind, float], ...],
    ) -> tuple[SnapCandidate, ...]:
        """Return only nearby infinite-grid lines for one axis update."""
        grid = self._grid
        if grid is None:
            return ()
        origin = grid.origin.x() if axis is SnapAxis.X else grid.origin.y()
        spacing = grid.spacing_x if axis is SnapAxis.X else grid.spacing_y
        span = grid.guide_span
        span_start, span_end = (
            (span.top(), span.bottom())
            if axis is SnapAxis.X
            else (span.left(), span.right())
        )
        indexes: set[int] = set()
        for _kind, position in features:
            lower = math.floor((position - origin) / spacing)
            indexes.update((lower, lower + 1))
        return tuple(
            SnapCandidate(
                f"grid:{axis.value}:{index}",
                axis,
                origin + index * spacing,
                SnapFeatureKind.GRID,
                span_start,
                span_end,
                grid.priority,
            )
            for index in sorted(indexes)
        )

    def _guide(
        self,
        axis: SnapAxis,
        locked: _AxisLock,
        resolved_delta: QPointF,
    ) -> SnapGuide:
        """Build one guide spanning moving and stationary geometry."""
        perpendicular_delta = (
            resolved_delta.y() if axis is SnapAxis.X else resolved_delta.x()
        )
        source_start, source_end = _perpendicular_span(
            self._source_bounds, axis, perpendicular_delta
        )
        candidate = locked.candidate
        return SnapGuide(
            axis,
            candidate.position,
            min(source_start, candidate.span_start),
            max(source_end, candidate.span_end),
            self._source_owner_id,
            candidate.owner_id,
        )


class SnapEngine:
    """Create source-neutral snap sessions for layers, pixels, and selections."""

    def begin(
        self,
        source_owner_id: str,
        source_bounds: QRectF,
        candidates: tuple[SnapCandidate, ...],
        *,
        threshold_device_pixels: float = 8.0,
        release_device_pixels: float = 4.0,
        grid: SnapGrid | None = None,
    ) -> SnapSession:
        """Return an isolated gesture session."""
        return SnapSession(
            source_owner_id,
            source_bounds,
            candidates,
            threshold_device_pixels=threshold_device_pixels,
            release_device_pixels=release_device_pixels,
            grid=grid,
        )


def _moving_features(
    bounds: QRectF,
    axis: SnapAxis,
    delta: float,
) -> tuple[tuple[SnapFeatureKind, float], ...]:
    """Return translated start, center, and end positions for one axis."""
    if axis is SnapAxis.X:
        values = bounds.left(), bounds.center().x(), bounds.right()
    else:
        values = bounds.top(), bounds.center().y(), bounds.bottom()
    return tuple(
        (kind, value + delta)
        for kind, value in zip(
            (SnapFeatureKind.START, SnapFeatureKind.CENTER, SnapFeatureKind.END),
            values,
            strict=True,
        )
    )


def _perpendicular_span(
    bounds: QRectF,
    axis: SnapAxis,
    perpendicular_delta: float,
) -> tuple[float, float]:
    """Return the moving bounds span perpendicular to ``axis``."""
    if axis is SnapAxis.X:
        return (
            bounds.top() + perpendicular_delta,
            bounds.bottom() + perpendicular_delta,
        )
    return (
        bounds.left() + perpendicular_delta,
        bounds.right() + perpendicular_delta,
    )


def _relationship_rank(
    moving: SnapFeatureKind,
    target: SnapFeatureKind,
) -> int | None:
    """Rank meaningful feature relationships and reject cross-feature snaps."""
    if target in (SnapFeatureKind.GUIDE, SnapFeatureKind.GRID):
        return 0
    if moving is target:
        return 0
    if (moving, target) in (
        (SnapFeatureKind.START, SnapFeatureKind.END),
        (SnapFeatureKind.END, SnapFeatureKind.START),
    ):
        return 1
    return None
