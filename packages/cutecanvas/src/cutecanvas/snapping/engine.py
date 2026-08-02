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

from PySide6.QtCore import QPointF, QRectF

from .axis_resolution import AxisSnapLock, AxisSnapResolver, build_candidate_index
from .model import (
    SnapAxis,
    SnapCandidate,
    SnapFeatureKind,
    SnapGrid,
    SnapGuide,
    SnapResult,
)


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
        candidate_index = build_candidate_index(
            candidates,
            excluded_owner_id=self._source_owner_id,
        )
        self._x = AxisSnapResolver(
            SnapAxis.X,
            candidate_index.for_axis(SnapAxis.X),
            threshold_device_pixels=threshold_device_pixels,
            release_device_pixels=release_device_pixels,
            grid=grid,
            relationship_rank=_relationship_rank,
            moving_kinds=(
                SnapFeatureKind.START,
                SnapFeatureKind.CENTER,
                SnapFeatureKind.END,
            ),
        )
        self._y = AxisSnapResolver(
            SnapAxis.Y,
            candidate_index.for_axis(SnapAxis.Y),
            threshold_device_pixels=threshold_device_pixels,
            release_device_pixels=release_device_pixels,
            grid=grid,
            relationship_rank=_relationship_rank,
            moving_kinds=(
                SnapFeatureKind.START,
                SnapFeatureKind.CENTER,
                SnapFeatureKind.END,
            ),
        )

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
        x = self._x.resolve(
            delta.x(),
            _moving_features(self._source_bounds, SnapAxis.X, delta.x()),
            scene_units_per_device_pixel=scale,
        )
        y = self._y.resolve(
            delta.y(),
            _moving_features(self._source_bounds, SnapAxis.Y, delta.y()),
            scene_units_per_device_pixel=scale,
        )
        guides = tuple(
            self._guide(axis, lock, QPointF(x.value, y.value))
            for axis, lock in (
                (SnapAxis.X, x.lock),
                (SnapAxis.Y, y.lock),
            )
            if lock is not None
        )
        return SnapResult(
            QPointF(x.value, y.value),
            guides,
            snapped_x=x.lock is not None,
            snapped_y=y.lock is not None,
        )

    def _guide(
        self,
        axis: SnapAxis,
        locked: AxisSnapLock,
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
    accepts_cross_feature: bool,
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
    if SnapFeatureKind.CENTER in (moving, target):
        return 2 if accepts_cross_feature else None
    return None
