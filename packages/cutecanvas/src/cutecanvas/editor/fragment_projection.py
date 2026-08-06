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
"""One-time projection of floating raster fragments between layer spaces."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtGui import QImage
from qpane.sdk.raster import (
    AffineImageResampler,
    numpy_to_qimage_argb32,
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_argb32,
    qimage_to_numpy_grayscale8,
)
from qpane.sdk.scene import LayerPlacement, LayerTransform, RasterBounds

from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.scene.pixel_fragments import RasterPixelFormat, RasterPixelFragment


class RasterFragmentProjector:
    """Project a fragment once when committing across layer transforms."""

    def __init__(self) -> None:
        """Create the shared affine image projection primitive."""
        self._images = AffineImageResampler()

    def project(
        self,
        fragment: RasterPixelFragment,
        *,
        source_transform: LayerTransform,
        fragment_transform: LayerTransform,
        destination_transform: LayerTransform,
    ) -> RasterPixelFragment | None:
        """Return destination-local samples covering the same scene geometry."""
        destination_inverse = destination_transform.inverted()
        if destination_inverse is None:
            return None
        source_to_destination = fragment_transform.followed_by(
            source_transform
        ).followed_by(destination_inverse)
        moved_bounds = fragment.bounds
        destination_bounds = _rasterized_bounds(
            source_to_destination.map_bounds(moved_bounds)
        )
        if destination_bounds is None:
            return None
        if _unit_integer_translation(source_to_destination) is not None:
            coverage = fragment.contribution_coverage.with_bounds(destination_bounds)
            return RasterPixelFragment._adopt_detached(
                destination_bounds,
                fragment.pixel_format,
                fragment.pixels,
                coverage,
            )
        if fragment.pixel_format is RasterPixelFormat.COVERAGE8:
            pixels = qimage_to_numpy_grayscale8(
                self._images.project(
                    numpy_to_qimage_grayscale8(fragment.pixels),
                    source_bounds=moved_bounds,
                    transform=source_to_destination,
                    destination_bounds=destination_bounds,
                    image_format=QImage.Format_Grayscale8,
                )
            )
        else:
            pixels = qimage_to_numpy_argb32(
                self._images.project(
                    numpy_to_qimage_argb32(fragment.pixels),
                    source_bounds=moved_bounds,
                    transform=source_to_destination,
                    destination_bounds=destination_bounds,
                    image_format=QImage.Format_ARGB32_Premultiplied,
                )
            )
        coverage_pixels = qimage_to_numpy_grayscale8(
            self._images.project(
                numpy_to_qimage_grayscale8(fragment.contribution_coverage.pixels),
                source_bounds=moved_bounds,
                transform=source_to_destination,
                destination_bounds=destination_bounds,
                image_format=QImage.Format_Grayscale8,
            )
        )
        supported = pixels != 0 if pixels.ndim == 2 else pixels[:, :, 3] != 0
        if not bool(np.all(supported)):
            coverage_pixels = np.where(
                supported,
                coverage_pixels,
                np.uint8(0),
            )
        if not np.any(coverage_pixels):
            return None
        coverage = CoverageSnapshot(
            destination_bounds,
            fragment.contribution_coverage.extent_policy,
            coverage_pixels,
        )
        return RasterPixelFragment(
            destination_bounds,
            fragment.pixel_format,
            pixels,
            coverage,
        )


def _rasterized_bounds(placement: LayerPlacement) -> RasterBounds | None:
    """Return conservative integer bounds for a mapped placement."""
    left = math.floor(placement.x)
    top = math.floor(placement.y)
    right = math.ceil(placement.x + placement.width)
    bottom = math.ceil(placement.y + placement.height)
    if right <= left or bottom <= top:
        return None
    return RasterBounds(left, top, right - left, bottom - top)


def _unit_integer_translation(transform: LayerTransform) -> tuple[int, int] | None:
    """Return a lossless metadata-only projection when available."""
    rounded_x = round(transform.dx)
    rounded_y = round(transform.dy)
    if (
        transform.m11 != 1.0
        or transform.m12 != 0.0
        or transform.m21 != 0.0
        or transform.m22 != 1.0
        or not math.isclose(transform.dx, rounded_x, abs_tol=1e-9)
        or not math.isclose(transform.dy, rounded_y, abs_tol=1e-9)
    ):
        return None
    return rounded_x, rounded_y
