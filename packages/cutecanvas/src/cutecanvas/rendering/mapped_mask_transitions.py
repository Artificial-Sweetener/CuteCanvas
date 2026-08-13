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
"""Rebase live mask patches onto a continuity-retained finite mapping."""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.coverage.bilinear_resampling import (
    project_scene_coverage_to_bilinear_layer,
)
from cutecanvas.coverage.piecewise_resampling import (
    project_scene_coverage_to_piecewise_layer,
)
from cutecanvas.types import RasterExtentPolicy
from PySide6.QtCore import QRectF
from qpane.sdk.scene import (
    BilinearLayerTransform,
    LayerDescriptor,
    LayerTransform,
    PiecewiseLayerTransform,
    RasterBounds,
)

from ..masks.live_preview_raster import LiveMaskPreviewPatches
from ..scene.pixel_transitions import RasterPixelTransition

_FiniteMapping = BilinearLayerTransform | PiecewiseLayerTransform
_Snapshot = Callable[[RasterBounds], CoverageSnapshot | None]
_SAMPLING_BLEED_PX = 4


def transition_for_retained_mapping(
    *,
    current: LayerDescriptor,
    retained: LayerDescriptor,
    preview: LiveMaskPreviewPatches,
    snapshot: _Snapshot,
) -> RasterPixelTransition | None:
    """Project one current-authority preview through a retained finite mapping."""
    mapping = retained.transform
    retained_surface = retained.raster_bounds
    preview_bounds = preview.content_bounds
    if (
        not isinstance(mapping, (BilinearLayerTransform, PiecewiseLayerTransform))
        or current.transform != LayerTransform()
        or retained_surface is None
        or preview_bounds is None
    ):
        return None
    retained_patch = _retained_patch_bounds(
        mapping,
        preview_bounds,
        retained_surface,
    )
    if retained_patch is None:
        return None
    scene_support = _scene_support_bounds(mapping, retained_patch)
    current_surface = current.raster_bounds
    if current_surface is None:
        return None
    scene_support = scene_support.intersection(current_surface)
    if scene_support is None:
        return None
    authoritative = snapshot(scene_support)
    if authoritative is None or authoritative.bounds != scene_support:
        return None
    before_scene = authoritative.pixels
    after_scene = np.array(before_scene, copy=True, order="C")
    preview.apply_to(scene_support, after_scene)
    before = _project_to_retained(
        CoverageSnapshot(
            scene_support,
            RasterExtentPolicy.EXPAND_ON_WRITE,
            before_scene,
        ),
        mapping,
        retained_patch,
    )
    after = _project_to_retained(
        CoverageSnapshot(
            scene_support,
            RasterExtentPolicy.EXPAND_ON_WRITE,
            after_scene,
        ),
        mapping,
        retained_patch,
    )
    if before is None or after is None:
        return None
    return RasterPixelTransition(
        retained_patch,
        retained_surface,
        retained_surface,
        before.pixels,
        after.pixels,
    )


def _retained_patch_bounds(
    mapping: _FiniteMapping,
    scene_bounds: RasterBounds,
    surface_bounds: RasterBounds,
) -> RasterBounds | None:
    """Return a bleed-safe local patch covering one scene-space transition."""
    mapped = mapping.inverse_map_rect(QRectF(scene_bounds.to_qrect()))
    if mapped.isEmpty():
        return None
    bleed = _SAMPLING_BLEED_PX
    candidate = RasterBounds(
        math.floor(mapped.left()) - bleed,
        math.floor(mapped.top()) - bleed,
        math.ceil(mapped.right()) - math.floor(mapped.left()) + bleed * 2,
        math.ceil(mapped.bottom()) - math.floor(mapped.top()) + bleed * 2,
    )
    return candidate.intersection(surface_bounds)


def _scene_support_bounds(
    mapping: _FiniteMapping,
    retained_bounds: RasterBounds,
) -> RasterBounds:
    """Return scene pixels needed to reproject one retained local patch exactly."""
    mapped = mapping.map_rect(QRectF(retained_bounds.to_qrect()))
    bleed = _SAMPLING_BLEED_PX
    left = math.floor(mapped.left()) - bleed
    top = math.floor(mapped.top()) - bleed
    right = math.ceil(mapped.right()) + bleed
    bottom = math.ceil(mapped.bottom()) + bleed
    return RasterBounds(left, top, max(1, right - left), max(1, bottom - top))


def _project_to_retained(
    snapshot: CoverageSnapshot,
    mapping: _FiniteMapping,
    destination: RasterBounds,
) -> CoverageSnapshot | None:
    """Sample scene coverage onto one bounded region of the retained source."""
    if isinstance(mapping, BilinearLayerTransform):
        return project_scene_coverage_to_bilinear_layer(
            snapshot,
            mapping,
            layer_bounds=destination,
            extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
        )
    return project_scene_coverage_to_piecewise_layer(
        snapshot,
        mapping,
        layer_bounds=destination,
        extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
    )


__all__ = ["transition_for_retained_mapping"]
