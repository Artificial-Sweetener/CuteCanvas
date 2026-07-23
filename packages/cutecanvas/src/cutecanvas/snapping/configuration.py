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

"""Host-configurable snapping policy, guides, and grid authority."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from PySide6.QtCore import QPointF, QRectF

from .model import SnapAxis, SnapCandidate, SnapFeatureKind, SnapGrid


@dataclass(frozen=True, slots=True)
class SnapPolicy:
    """Choose candidate domains and device-pixel interaction thresholds."""

    enabled: bool = True
    canvas: bool = True
    layers: bool = True
    selections: bool = True
    guides: bool = True
    grid: bool = False
    threshold_device_pixels: float = 8.0
    release_device_pixels: float = 4.0

    def __post_init__(self) -> None:
        """Require usable snap and hysteresis distances."""
        if self.threshold_device_pixels <= 0.0:
            raise ValueError("snap threshold must be positive")
        if self.release_device_pixels < 0.0:
            raise ValueError("snap release distance must be non-negative")


class SnapConfiguration:
    """Own mutable host snapping preferences outside gesture sessions."""

    def __init__(self, changed: Callable[[], None] | None = None) -> None:
        """Initialize content-aware snapping defaults with no authored guides."""
        self._policy = SnapPolicy()
        self._vertical_guides: tuple[float, ...] = ()
        self._horizontal_guides: tuple[float, ...] = ()
        self._grid_origin = QPointF()
        self._grid_spacing = QPointF(32.0, 32.0)
        self._changed = changed

    @property
    def policy(self) -> SnapPolicy:
        """Return the immutable current candidate and threshold policy."""
        return self._policy

    @property
    def guides(self) -> tuple[tuple[float, ...], tuple[float, ...]]:
        """Return vertical and horizontal guide positions."""
        return self._vertical_guides, self._horizontal_guides

    @property
    def grid(self) -> tuple[QPointF, QPointF]:
        """Return detached grid origin and spacing values."""
        return QPointF(self._grid_origin), QPointF(self._grid_spacing)

    def configure(self, **changes: object) -> bool:
        """Replace named immutable policy fields and publish once."""
        policy = replace(self._policy, **changes)
        if policy == self._policy:
            return False
        self._policy = policy
        self._publish()
        return True

    def guide_candidates(self, span: QRectF) -> tuple[SnapCandidate, ...]:
        """Return explicit guide candidates spanning the active composition."""
        rectangle = QRectF(span).normalized()
        return (
            *(
                SnapCandidate(
                    f"guide:x:{index}",
                    SnapAxis.X,
                    position,
                    SnapFeatureKind.GUIDE,
                    rectangle.top(),
                    rectangle.bottom(),
                    30,
                )
                for index, position in enumerate(self._vertical_guides)
            ),
            *(
                SnapCandidate(
                    f"guide:y:{index}",
                    SnapAxis.Y,
                    position,
                    SnapFeatureKind.GUIDE,
                    rectangle.left(),
                    rectangle.right(),
                    30,
                )
                for index, position in enumerate(self._horizontal_guides)
            ),
        )

    def grid_model(self, span: QRectF) -> SnapGrid:
        """Return the current infinite grid with finite overlay span."""
        return SnapGrid(
            self._grid_origin,
            self._grid_spacing.x(),
            self._grid_spacing.y(),
            span,
        )

    def set_guides(
        self,
        *,
        vertical: tuple[float, ...] = (),
        horizontal: tuple[float, ...] = (),
    ) -> bool:
        """Replace explicit scene-coordinate guide lines."""
        normalized = (
            tuple(sorted({float(value) for value in vertical})),
            tuple(sorted({float(value) for value in horizontal})),
        )
        if normalized == self.guides:
            return False
        self._vertical_guides, self._horizontal_guides = normalized
        self._publish()
        return True

    def _publish(self) -> None:
        """Notify hosts after durable configuration changes."""
        if self._changed is not None:
            self._changed()

    def set_grid(self, origin: QPointF, spacing: QPointF) -> bool:
        """Replace the infinite grid geometry used by future gestures."""
        next_origin = QPointF(origin)
        next_spacing = QPointF(spacing)
        if next_spacing.x() <= 0.0 or next_spacing.y() <= 0.0:
            raise ValueError("grid spacing must be positive")
        if next_origin == self._grid_origin and next_spacing == self._grid_spacing:
            return False
        self._grid_origin = next_origin
        self._grid_spacing = next_spacing
        self._publish()
        return True
