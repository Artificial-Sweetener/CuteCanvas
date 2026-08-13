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

"""Typed sampling identities for raster presentation and exact products."""

from __future__ import annotations

from enum import Enum


class RasterPresentationSampling(str, Enum):
    """Name the interpolation used while Qt presents a raster product."""

    NEAREST = "nearest"
    BILINEAR = "bilinear"

    @property
    def uses_bilinear_interpolation(self) -> bool:
        """Return whether presentation enables Qt bilinear interpolation."""
        return self is RasterPresentationSampling.BILINEAR


class RasterExactSampling(str, Enum):
    """Identify the numerical operation used to produce an exact raster tile."""

    NEAREST = "nearest"
    LANCZOS3 = "lanczos3"
    AFFINE_BILINEAR = "affine-bilinear"


__all__ = ["RasterExactSampling", "RasterPresentationSampling"]
