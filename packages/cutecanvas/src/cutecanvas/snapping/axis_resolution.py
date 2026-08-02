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

"""One-axis snapping mechanics shared by movement and authoring sessions."""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from operator import attrgetter

from .model import SnapAxis, SnapCandidate, SnapFeatureKind, SnapGrid

SnapRelationshipRank = Callable[[SnapFeatureKind, SnapFeatureKind], int | None]
_CANDIDATE_POSITION = attrgetter("position")


@dataclass(frozen=True, slots=True)
class AxisSnapLock:
    """Retain one moving-feature relationship through pointer jitter."""

    moving_kind: SnapFeatureKind
    candidate: SnapCandidate


@dataclass(frozen=True, slots=True)
class AxisSnapResolution:
    """Describe one corrected scalar and its acquired relationship."""

    value: float
    lock: AxisSnapLock | None = None


class AxisSnapResolver:
    """Resolve one gesture axis with deterministic priority and hysteresis."""

    def __init__(
        self,
        axis: SnapAxis,
        candidates: tuple[SnapCandidate, ...],
        *,
        threshold_device_pixels: float,
        release_device_pixels: float,
        grid: SnapGrid | None,
        relationship_rank: SnapRelationshipRank,
        moving_kinds: tuple[SnapFeatureKind, ...],
    ) -> None:
        """Capture immutable candidates and thresholds for one gesture axis."""
        self._axis = axis
        self._threshold_pixels = float(threshold_device_pixels)
        self._release_pixels = float(release_device_pixels)
        self._grid = grid
        self._relationship_rank = relationship_rank
        candidates_by_kind: dict[SnapFeatureKind, list[SnapCandidate]] = {
            kind: [] for kind in SnapFeatureKind
        }
        for candidate in candidates:
            candidates_by_kind[candidate.kind].append(candidate)
        for target_candidates in candidates_by_kind.values():
            target_candidates.sort(key=_CANDIDATE_POSITION)
        self._matches_by_moving_kind = {
            moving_kind: tuple(
                (target_candidates, rank)
                for target_kind, target_candidates in candidates_by_kind.items()
                if (rank := relationship_rank(moving_kind, target_kind)) is not None
                and target_candidates
            )
            for moving_kind in moving_kinds
        }
        self._lock: AxisSnapLock | None = None

    @property
    def lock(self) -> AxisSnapLock | None:
        """Return the currently acquired relationship."""
        return self._lock

    def clear(self) -> None:
        """Release the active relationship without changing candidates."""
        self._lock = None

    def resolve(
        self,
        raw_value: float,
        features: tuple[tuple[SnapFeatureKind, float], ...],
        *,
        scene_units_per_device_pixel: float,
    ) -> AxisSnapResolution:
        """Return the corrected scalar for supplied moving feature positions."""
        scale = float(scene_units_per_device_pixel)
        if scale <= 0.0:
            raise ValueError("scene units per device pixel must be positive")
        threshold = self._threshold_pixels * scale
        release = (self._threshold_pixels + self._release_pixels) * scale
        locked = self._lock
        if locked is not None:
            moving_position = dict(features)[locked.moving_kind]
            correction = locked.candidate.position - moving_position
            if abs(correction) <= release:
                return AxisSnapResolution(raw_value + correction, locked)
        matches = []
        grid_candidates = self._grid_candidates(features)
        for moving_kind, moving_position in features:
            for candidates, rank in self._matches_by_moving_kind[moving_kind]:
                start = bisect_left(
                    candidates,
                    moving_position - threshold,
                    key=_CANDIDATE_POSITION,
                )
                stop = bisect_right(
                    candidates,
                    moving_position + threshold,
                    key=_CANDIDATE_POSITION,
                )
                for index in range(start, stop):
                    candidate = candidates[index]
                    correction = candidate.position - moving_position
                    if abs(correction) <= threshold:
                        matches.append(
                            (
                                abs(correction),
                                -candidate.priority,
                                rank,
                                candidate.position,
                                candidate.owner_id,
                                moving_kind,
                                candidate,
                                correction,
                            )
                        )
            for candidate in grid_candidates:
                rank = self._relationship_rank(moving_kind, candidate.kind)
                if rank is None:
                    continue
                correction = candidate.position - moving_position
                if abs(correction) <= threshold:
                    matches.append(
                        (
                            abs(correction),
                            -candidate.priority,
                            rank,
                            candidate.position,
                            candidate.owner_id,
                            moving_kind,
                            candidate,
                            correction,
                        )
                    )
        if not matches:
            self._lock = None
            return AxisSnapResolution(raw_value)
        match = min(matches)
        self._lock = AxisSnapLock(match[5], match[6])
        return AxisSnapResolution(raw_value + match[7], self._lock)

    def _grid_candidates(
        self,
        features: tuple[tuple[SnapFeatureKind, float], ...],
    ) -> tuple[SnapCandidate, ...]:
        """Return only nearby infinite-grid lines for the active axis."""
        grid = self._grid
        if grid is None:
            return ()
        origin = grid.origin.x() if self._axis is SnapAxis.X else grid.origin.y()
        spacing = grid.spacing_x if self._axis is SnapAxis.X else grid.spacing_y
        span = grid.guide_span
        span_start, span_end = (
            (span.top(), span.bottom())
            if self._axis is SnapAxis.X
            else (span.left(), span.right())
        )
        indexes: set[int] = set()
        for _kind, position in features:
            lower = math.floor((position - origin) / spacing)
            indexes.update((lower, lower + 1))
        return tuple(
            SnapCandidate(
                f"grid:{self._axis.value}:{index}",
                self._axis,
                origin + index * spacing,
                SnapFeatureKind.GRID,
                span_start,
                span_end,
                grid.priority,
            )
            for index in sorted(indexes)
        )
