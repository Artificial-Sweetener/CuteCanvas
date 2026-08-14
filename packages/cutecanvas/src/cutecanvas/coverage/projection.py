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
"""Source-neutral affine projection of grayscale coverage snapshots."""

from __future__ import annotations

import math

import numpy as np

from cutecanvas.ferrastra import NativeCoverageProjector
from cutecanvas.types import RasterExtentPolicy
from qpane.sdk.execution import CancellationToken
from qpane.sdk.scene import LayerTransform, RasterBounds

from .surface import CoverageSnapshot


class AffineCoverageResampler:
    """Resample coverage between coordinate spaces using one affine mapping."""

    def __init__(self) -> None:
        """Create the canonical scalar affine projection adapter."""
        self._projector = NativeCoverageProjector()

    def project(
        self,
        snapshot: CoverageSnapshot,
        transform: LayerTransform,
        destination_bounds: RasterBounds,
        *,
        extent_policy: RasterExtentPolicy,
        smooth: bool = True,
        cancellation: CancellationToken | None = None,
    ) -> CoverageSnapshot:
        """Project source-coordinate pixels into explicit destination bounds."""
        source_bounds = snapshot.bounds
        if source_bounds is None:
            pixels = np.zeros(
                (destination_bounds.height, destination_bounds.width),
                dtype=np.uint8,
            )
        else:
            pixels = self._projector.project(
                snapshot.pixels,
                source_bounds=source_bounds,
                transform=transform,
                destination_bounds=destination_bounds,
                linear=smooth,
                filter_mode=_coverage_filter(transform, smooth=smooth),
                edge_mode=_coverage_edge_mode(
                    transform,
                    source_bounds,
                    destination_bounds,
                ),
                cancellation=cancellation,
            )
        return CoverageSnapshot(
            destination_bounds,
            extent_policy,
            pixels,
        )


def _coverage_filter(transform: LayerTransform, *, smooth: bool) -> str | None:
    """Choose area integration for axis-aligned coverage minification."""
    if (
        smooth
        and transform.m12 == 0.0
        and transform.m21 == 0.0
        and (abs(transform.m11) < 1.0 or abs(transform.m22) < 1.0)
    ):
        return "area"
    return None


def _coverage_edge_mode(
    transform: LayerTransform,
    source_bounds: RasterBounds,
    destination_bounds: RasterBounds,
) -> str:
    """Clamp only when an axis-aligned destination exactly covers the source."""
    if transform.m12 != 0.0 or transform.m21 != 0.0:
        return "transparent"
    mapped = transform.map_bounds(source_bounds)
    destination = (
        float(destination_bounds.x),
        float(destination_bounds.y),
        float(destination_bounds.width),
        float(destination_bounds.height),
    )
    actual = (mapped.x, mapped.y, mapped.width, mapped.height)
    return (
        "clamp"
        if all(
            math.isclose(value, expected, rel_tol=0.0, abs_tol=1e-9)
            for value, expected in zip(actual, destination, strict=True)
        )
        else "transparent"
    )
