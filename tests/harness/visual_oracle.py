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

"""Independent centerline oracle for mounted mask-stroke observations."""

from __future__ import annotations

import itertools
import math

from PySide6.QtCore import QPoint

from .abuse_model import HarnessPoint, StrokeAction


class StrokeVisualOracle:
    """Track expected stroke interiors without using CuteCanvas's rasterizer."""

    def __init__(self, *, sample_spacing: float = 8.0) -> None:
        """Initialize independent committed and redo histories."""
        if sample_spacing <= 0:
            raise ValueError("sample_spacing must be positive")
        self._sample_spacing = sample_spacing
        self._history: dict[int, list[StrokeAction]] = {}
        self._redo: dict[int, list[StrokeAction]] = {}

    def commit(self, action: StrokeAction) -> None:
        """Record a successfully displayed stroke."""
        self._history.setdefault(action.mask_index, []).append(action)
        self._redo.setdefault(action.mask_index, []).clear()

    def undo(self, mask_index: int) -> StrokeAction:
        """Move and return the latest stroke from history to redo."""
        history = self._history.setdefault(mask_index, [])
        if not history:
            raise ValueError(f"Mask {mask_index} has no oracle history to undo")
        action = history.pop()
        self._redo.setdefault(mask_index, []).append(action)
        return action

    def redo(self, mask_index: int) -> StrokeAction:
        """Restore and return the latest undone stroke."""
        redo = self._redo.setdefault(mask_index, [])
        if not redo:
            raise ValueError(f"Mask {mask_index} has no oracle history to redo")
        action = redo.pop()
        self._history.setdefault(mask_index, []).append(action)
        return action

    def expected_tinted_points(
        self,
        provisional: StrokeAction | None = None,
    ) -> tuple[QPoint, ...]:
        """Return deduplicated committed and optional provisional center samples."""
        points: dict[tuple[int, int], QPoint] = {}
        for action in self.committed_strokes():
            for point in self.sample_action(action):
                points[(point.x(), point.y())] = point
        if provisional is not None:
            for point in self.sample_action(provisional):
                points[(point.x(), point.y())] = point
        return tuple(points.values())

    def exposed_points_after_removal(
        self,
        removed: StrokeAction,
    ) -> tuple[QPoint, ...]:
        """Return removed center samples safely outside all remaining strokes."""
        remaining = self.committed_strokes()
        exposed: list[QPoint] = []
        for point in self.sample_action(removed):
            if all(not self._safely_covered(point, action) for action in remaining):
                exposed.append(point)
        return tuple(exposed)

    def committed_strokes(self) -> tuple[StrokeAction, ...]:
        """Return all committed strokes across masks."""
        return tuple(action for history in self._history.values() for action in history)

    def sample_action(self, action: StrokeAction) -> tuple[QPoint, ...]:
        """Sample a stroke centerline independently from production rendering."""
        points = tuple(point.to_qpoint() for point in action.points)
        if len(points) == 1:
            return points
        samples: list[QPoint] = [points[0]]
        for start, end in itertools.pairwise(points):
            distance = math.hypot(end.x() - start.x(), end.y() - start.y())
            steps = max(1, math.ceil(distance / self._sample_spacing))
            for step in range(1, steps + 1):
                ratio = step / steps
                samples.append(
                    QPoint(
                        round(start.x() + (end.x() - start.x()) * ratio),
                        round(start.y() + (end.y() - start.y()) * ratio),
                    )
                )
        return tuple(samples)

    def partial_action(self, action: StrokeAction, point_count: int) -> StrokeAction:
        """Return the prefix visible after ``point_count`` input samples."""
        return StrokeAction(
            device=action.device,
            points=action.points[:point_count],
            mask_index=action.mask_index,
            brush_size=action.brush_size,
            step_delay_ms=action.step_delay_ms,
            pressure=action.pressure,
        )

    @staticmethod
    def point_value(point: QPoint) -> HarnessPoint:
        """Convert a Qt point for serialization in failures."""
        return HarnessPoint(point.x(), point.y())

    def _safely_covered(self, point: QPoint, action: StrokeAction) -> bool:
        """Conservatively classify points well inside another brush stroke."""
        safe_radius = max(1.0, action.brush_size * 0.35)
        path = tuple(value.to_qpoint() for value in action.points)
        if len(path) == 1:
            return self._distance(point, path[0]) <= safe_radius
        return any(
            self._distance_to_segment(point, start, end) <= safe_radius
            for start, end in itertools.pairwise(path)
        )

    @staticmethod
    def _distance(first: QPoint, second: QPoint) -> float:
        """Return Euclidean distance between two widget points."""
        return math.hypot(first.x() - second.x(), first.y() - second.y())

    @staticmethod
    def _distance_to_segment(point: QPoint, start: QPoint, end: QPoint) -> float:
        """Return distance from ``point`` to a finite line segment."""
        delta_x = end.x() - start.x()
        delta_y = end.y() - start.y()
        length_squared = delta_x * delta_x + delta_y * delta_y
        if length_squared == 0:
            return StrokeVisualOracle._distance(point, start)
        projection = (
            (point.x() - start.x()) * delta_x + (point.y() - start.y()) * delta_y
        ) / length_squared
        projection = max(0.0, min(1.0, projection))
        projected_x = start.x() + projection * delta_x
        projected_y = start.y() + projection * delta_y
        return math.hypot(point.x() - projected_x, point.y() - projected_y)
