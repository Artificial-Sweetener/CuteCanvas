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
"""Immutable lifted raster content shared by editable pixel domains."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from qpane.sdk.scene import RasterBounds

from ..coverage import CoverageSnapshot
from .pixel_transitions import RasterPixelTransition


class RasterPixelFormat(str, Enum):
    """Storage formats accepted by floating raster destinations."""

    COVERAGE8 = "coverage8"
    PREMULTIPLIED_ARGB32 = "premultiplied-argb32"


@dataclass(frozen=True, slots=True)
class RasterPixelFragment:
    """Retain source samples and content-filtered contribution coverage."""

    bounds: RasterBounds
    pixel_format: RasterPixelFormat
    pixels: np.ndarray
    contribution_coverage: CoverageSnapshot

    def __post_init__(self) -> None:
        """Detach arrays and validate source-local geometry."""
        expected = (self.bounds.height, self.bounds.width)
        pixels = np.array(self.pixels, copy=True, order="C")
        if self.pixel_format is RasterPixelFormat.COVERAGE8:
            valid_shape = pixels.shape == expected
        else:
            valid_shape = pixels.shape == (*expected, 4)
        if pixels.dtype != np.uint8 or not valid_shape:
            raise ValueError("fragment pixels do not match their raster format")
        if (
            self.contribution_coverage.bounds != self.bounds
            or self.contribution_coverage.pixels.shape != expected
        ):
            raise ValueError("fragment contribution coverage must match its bounds")
        pixels.flags.writeable = False
        object.__setattr__(self, "pixels", pixels)

    @classmethod
    def _adopt_detached(
        cls,
        bounds: RasterBounds,
        pixel_format: RasterPixelFormat,
        pixels: np.ndarray,
        contribution_coverage: CoverageSnapshot,
    ) -> RasterPixelFragment:
        """Adopt validated immutable source samples without another full copy."""
        expected = (bounds.height, bounds.width)
        valid_shape = (
            pixels.shape == expected
            if pixel_format is RasterPixelFormat.COVERAGE8
            else pixels.shape == (*expected, 4)
        )
        if (
            pixels.dtype != np.uint8
            or not pixels.flags.c_contiguous
            or not valid_shape
            or contribution_coverage.bounds != bounds
        ):
            raise ValueError("adopted fragment storage is invalid")
        pixels.flags.writeable = False
        fragment = object.__new__(cls)
        object.__setattr__(fragment, "bounds", bounds)
        object.__setattr__(fragment, "pixel_format", pixel_format)
        object.__setattr__(fragment, "pixels", pixels)
        object.__setattr__(
            fragment,
            "contribution_coverage",
            contribution_coverage,
        )
        return fragment

    @property
    def retained_bytes(self) -> int:
        """Return immutable pixel and coverage storage retained by the fragment."""
        return int(self.pixels.nbytes + self.contribution_coverage.pixels.nbytes)

    def materialized_pixels(self) -> np.ndarray:
        """Return selected source contribution over an empty destination."""
        if bool(np.all(self.contribution_coverage.pixels == 255)):
            return self.pixels
        selection = self.contribution_coverage.pixels.astype(np.uint16)
        if self.pixels.ndim == 3:
            selection = selection[:, :, np.newaxis]
        return np.ascontiguousarray(
            ((self.pixels.astype(np.uint16) * selection + 127) // 255).astype(np.uint8)
        )


@dataclass(frozen=True, slots=True)
class RasterPixelLift:
    """Retain one reversible source extraction and its floating payload."""

    fragment: RasterPixelFragment
    source_transition: RasterPixelTransition

    @property
    def retained_bytes(self) -> int:
        """Return bytes retained for payload and exact source restoration."""
        return int(
            self.source_transition.retained_bytes
            + self.fragment.contribution_coverage.pixels.nbytes
        )
