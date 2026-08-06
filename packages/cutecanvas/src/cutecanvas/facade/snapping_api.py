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

"""Public editor snapping configuration controls."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QPointF

from ..snapping import SnapPolicy


class SnappingApiMixin:
    """Expose host snapping policy without owning gesture state."""

    def snapPolicy(self) -> SnapPolicy:
        """Return the immutable current snapping policy."""
        return self.snapConfiguration().policy

    def configureSnapping(
        self,
        *,
        enabled: bool | None = None,
        canvas: bool | None = None,
        layers: bool | None = None,
        selections: bool | None = None,
        guides: bool | None = None,
        grid: bool | None = None,
        threshold_device_pixels: float | None = None,
        release_device_pixels: float | None = None,
    ) -> bool:
        """Configure shared move, transform, and geometric-authoring snapping."""
        changes = {
            name: value
            for name, value in {
                "enabled": enabled,
                "canvas": canvas,
                "layers": layers,
                "selections": selections,
                "guides": guides,
                "grid": grid,
                "threshold_device_pixels": threshold_device_pixels,
                "release_device_pixels": release_device_pixels,
            }.items()
            if value is not None
        }
        return self.snapConfiguration().configure(**changes)

    def setSnapGuides(
        self,
        *,
        vertical: Iterable[float] = (),
        horizontal: Iterable[float] = (),
    ) -> bool:
        """Replace scene-coordinate guide lines used by future gestures."""
        return self.snapConfiguration().set_guides(
            vertical=tuple(vertical),
            horizontal=tuple(horizontal),
        )

    def setSnapGrid(self, origin: QPointF, spacing: QPointF) -> bool:
        """Replace the infinite scene-coordinate snapping grid."""
        return self.snapConfiguration().set_grid(origin, spacing)
