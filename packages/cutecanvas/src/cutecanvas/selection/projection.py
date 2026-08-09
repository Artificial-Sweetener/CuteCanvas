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
"""Projection of layer-local coverage into composition scene coordinates."""

from __future__ import annotations

import math

from qpane.sdk.scene import (
    BilinearLayerTransform,
    LayerMapping,
    LayerPlacement,
    LayerTransform,
    PiecewiseLayerTransform,
    RasterBounds,
)

from cutecanvas.coverage import AffineCoverageResampler, CoverageSnapshot
from cutecanvas.coverage.bilinear_resampling import (
    project_bilinear_coverage,
    project_scene_coverage_to_bilinear_layer,
)
from cutecanvas.coverage.piecewise_resampling import (
    project_piecewise_coverage,
    project_scene_coverage_to_piecewise_layer,
)
from cutecanvas.types import RasterExtentPolicy

from .compositor import trim_selection_coverage


class LayerCoverageProjector:
    """Map source coverage through affine layer geometry into minimal storage."""

    def __init__(self) -> None:
        """Create the source-neutral affine resampling collaborator."""
        self._resampler = AffineCoverageResampler()

    def project(
        self,
        coverage: CoverageSnapshot,
        transform: LayerMapping,
    ) -> CoverageSnapshot | None:
        """Return antialiased scene coverage for one layer-local snapshot."""
        source_bounds = coverage.bounds
        if source_bounds is None:
            return None
        if isinstance(transform, BilinearLayerTransform):
            scene_bounds = _rasterize_placement(transform.map_bounds(source_bounds))
            if scene_bounds is None:
                return None
            projected = project_bilinear_coverage(
                coverage,
                transform,
                canvas_x=float(scene_bounds.x),
                canvas_y=float(scene_bounds.y),
                canvas_width=scene_bounds.width,
                canvas_height=scene_bounds.height,
            )
            return trim_selection_coverage(
                CoverageSnapshot(
                    scene_bounds,
                    RasterExtentPolicy.EXPAND_ON_WRITE,
                    projected,
                )
            )
        if isinstance(transform, PiecewiseLayerTransform):
            scene_bounds = _rasterize_placement(transform.map_bounds(source_bounds))
            if scene_bounds is None:
                return None
            return trim_selection_coverage(
                project_piecewise_coverage(coverage, transform, scene_bounds)
            )
        integer_translation = _unit_integer_translation(transform)
        if integer_translation is not None:
            return coverage.with_bounds(
                source_bounds.translated(*integer_translation),
                extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
            )
        scene_bounds = _rasterize_placement(transform.map_bounds(source_bounds))
        if scene_bounds is None:
            return None
        return trim_selection_coverage(
            self._resampler.project(
                coverage,
                transform,
                scene_bounds,
                extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
            )
        )

    def project_to_layer(
        self,
        coverage: CoverageSnapshot,
        transform: LayerMapping,
        layer_bounds: RasterBounds | None = None,
    ) -> CoverageSnapshot | None:
        """Project scene coverage into bounded or unbounded layer coordinates."""
        scene_bounds = coverage.bounds
        if scene_bounds is None:
            return None
        unbounded = layer_bounds is None
        if isinstance(transform, BilinearLayerTransform):
            projected = project_scene_coverage_to_bilinear_layer(
                coverage,
                transform,
                layer_bounds=layer_bounds,
                extent_policy=(
                    RasterExtentPolicy.EXPAND_ON_WRITE
                    if unbounded
                    else RasterExtentPolicy.FIXED
                ),
            )
            return None if projected is None else trim_selection_coverage(projected)
        if isinstance(transform, PiecewiseLayerTransform):
            projected = project_scene_coverage_to_piecewise_layer(
                coverage,
                transform,
                layer_bounds=layer_bounds,
                extent_policy=(
                    RasterExtentPolicy.EXPAND_ON_WRITE
                    if unbounded
                    else RasterExtentPolicy.FIXED
                ),
            )
            return None if projected is None else trim_selection_coverage(projected)
        integer_translation = _unit_integer_translation(transform)
        if integer_translation is not None:
            return _project_integer_translation_to_layer(
                coverage,
                integer_translation,
                layer_bounds,
                unbounded=unbounded,
            )
        inverse = transform.inverted()
        if inverse is None:
            return None
        requested_bounds = _rasterize_placement(inverse.map_bounds(scene_bounds))
        if requested_bounds is None:
            return None
        destination_bounds = (
            requested_bounds
            if layer_bounds is None
            else requested_bounds.intersection(layer_bounds)
        )
        if destination_bounds is None:
            return None
        return trim_selection_coverage(
            self._resampler.project(
                coverage,
                inverse,
                destination_bounds,
                extent_policy=(
                    RasterExtentPolicy.EXPAND_ON_WRITE
                    if unbounded
                    else RasterExtentPolicy.FIXED
                ),
            )
        )


def _unit_integer_translation(transform: LayerTransform) -> tuple[int, int] | None:
    """Return integral translation for the lossless unit-scale projection path."""
    translate_x = round(transform.dx)
    translate_y = round(transform.dy)
    if (
        transform.m11 != 1.0
        or transform.m12 != 0.0
        or transform.m21 != 0.0
        or transform.m22 != 1.0
        or not math.isclose(transform.dx, translate_x, abs_tol=1e-9)
        or not math.isclose(transform.dy, translate_y, abs_tol=1e-9)
    ):
        return None
    return translate_x, translate_y


def _rasterize_placement(placement: LayerPlacement) -> RasterBounds | None:
    """Return integer half-open storage conservatively covering a placement."""
    left = math.floor(placement.x)
    top = math.floor(placement.y)
    right = math.ceil(placement.x + placement.width)
    bottom = math.ceil(placement.y + placement.height)
    if right <= left or bottom <= top:
        return None
    return RasterBounds(left, top, right - left, bottom - top)


def _project_integer_translation_to_layer(
    coverage: CoverageSnapshot,
    translation: tuple[int, int],
    layer_bounds: RasterBounds | None,
    *,
    unbounded: bool,
) -> CoverageSnapshot | None:
    """Map unit-scale coverage by metadata and crop only when bounds require it."""
    scene_bounds = coverage.bounds
    if scene_bounds is None:
        return None
    local_bounds = scene_bounds.translated(-translation[0], -translation[1])
    destination = (
        local_bounds
        if layer_bounds is None
        else local_bounds.intersection(layer_bounds)
    )
    if destination is None:
        return None
    policy = (
        RasterExtentPolicy.EXPAND_ON_WRITE if unbounded else RasterExtentPolicy.FIXED
    )
    if destination == local_bounds:
        return coverage.with_bounds(destination, extent_policy=policy)
    source_local = destination.translated(*translation)
    source_x = source_local.x - scene_bounds.x
    source_y = source_local.y - scene_bounds.y
    return trim_selection_coverage(
        CoverageSnapshot(
            destination,
            policy,
            coverage.pixels[
                source_y : source_y + destination.height,
                source_x : source_x + destination.width,
            ],
        )
    )
