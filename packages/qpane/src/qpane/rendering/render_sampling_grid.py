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

"""Immutable identities for exact render-product sampling grids."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AxisAlignedSamplingGrid:
    """Identify one source-space grid aligned to physical output pixels."""

    scale_x: float
    scale_y: float
    phase_x: float
    phase_y: float

    def __post_init__(self) -> None:
        """Require finite positive density and finite source-grid phase."""
        values = (self.scale_x, self.scale_y, self.phase_x, self.phase_y)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("sampling grid values must be finite")
        if self.scale_x <= 0.0 or self.scale_y <= 0.0:
            raise ValueError("sampling grid scales must be positive")

    @property
    def step_x(self) -> float:
        """Return source-space distance between horizontal output samples."""
        return 1.0 / self.scale_x

    @property
    def step_y(self) -> float:
        """Return source-space distance between vertical output samples."""
        return 1.0 / self.scale_y


@dataclass(frozen=True, slots=True)
class AffineSamplingGrid:
    """Identify a panel-physical grid mapped into source sample coordinates."""

    source_m11: float
    source_m12: float
    source_m21: float
    source_m22: float
    source_tx: float
    source_ty: float
    device_pixel_ratio: float

    def __post_init__(self) -> None:
        """Require a finite invertible affine map and positive physical density."""
        values = (
            self.source_m11,
            self.source_m12,
            self.source_m21,
            self.source_m22,
            self.source_tx,
            self.source_ty,
            self.device_pixel_ratio,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("affine sampling grid values must be finite")
        if self.device_pixel_ratio <= 0.0:
            raise ValueError("device_pixel_ratio must be positive")
        determinant = (
            self.source_m11 * self.source_m22 - self.source_m12 * self.source_m21
        )
        if math.isclose(determinant, 0.0, abs_tol=1e-15):
            raise ValueError("affine sampling grid must be invertible")


ExactSamplingGrid = AxisAlignedSamplingGrid | AffineSamplingGrid


__all__ = ["AffineSamplingGrid", "AxisAlignedSamplingGrid", "ExactSamplingGrid"]
