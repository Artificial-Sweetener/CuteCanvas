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
"""Viewport-independent projection of mask authoring surfaces onto canvases."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable

import numpy as np
from cutecanvas.coverage import (
    AffineCoverageResampler,
    CoverageCombineMode,
    CoverageSnapshot,
    combine_coverage,
    normalize_coverage_array,
    reframe_coverage_snapshot,
)
from cutecanvas.coverage.bilinear_resampling import (
    project_bilinear_coverage,
    project_scene_coverage_to_bilinear_layer,
)
from cutecanvas.coverage.content_bounds import occupied_coverage_bounds
from cutecanvas.coverage.piecewise_resampling import (
    project_piecewise_coverage,
    project_scene_coverage_to_piecewise_layer,
)
from cutecanvas.types import RasterExtentPolicy
from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage
from qpane.sdk.raster import numpy_to_qimage_grayscale8
from qpane.sdk.scene import (
    BilinearLayerTransform,
    LayerDescriptor,
    LayerTransform,
    PiecewiseLayerTransform,
    RasterBounds,
    SceneDescriptor,
)

from ..resources import ProjectResourceReference
from .image_ops import resize_mask_nearest
from .mask import MaskAssetStore


class MaskCanvasProjectionService:
    """Resolve mask instances and clip their authoring pixels to scene bounds."""

    def __init__(
        self,
        *,
        assets: MaskAssetStore,
        active_scene: Callable[[], SceneDescriptor | None],
    ) -> None:
        """Bind mask assets and the active resolved scene provider."""
        self._assets = assets
        self._active_scene = active_scene
        self._resampler = AffineCoverageResampler()

    def project(self, mask_id: uuid.UUID) -> QImage | None:
        """Return an image-sized mask containing only pixels inside the canvas."""
        deferred = self.deferred(mask_id)
        return None if deferred is None else deferred()

    def deferred(self, mask_id: uuid.UUID) -> Callable[[], QImage] | None:
        """Capture lightweight geometry for projection on a worker thread."""
        scene = self._active_scene()
        layer = self._layer_for_mask(scene, mask_id)
        asset = self._assets.get_layer(mask_id)
        if scene is None or layer is None or asset is None or layer.transform is None:
            return None
        width = round(scene.bounds.width)
        height = round(scene.bounds.height)
        if width <= 0 or height <= 0:
            return None
        canvas_x = scene.bounds.x
        canvas_y = scene.bounds.y
        coverage = asset.coverage

        def project() -> QImage:
            """Snapshot and project the captured source using current pixels."""
            projected = project_mask_snapshot(
                coverage.snapshot(),
                layer=layer,
                canvas_x=canvas_x,
                canvas_y=canvas_y,
                canvas_width=width,
                canvas_height=height,
            )
            return numpy_to_qimage_grayscale8(projected)

        return project

    def combine_canvas_mask(
        self,
        mask_id: uuid.UUID,
        incoming_mask: np.ndarray,
        *,
        erase: bool,
    ) -> CoverageSnapshot | None:
        """Map a canvas-sized generated mask into source-local authoring storage."""
        scene = self._active_scene()
        layer = self._layer_for_mask(scene, mask_id)
        asset = self._assets.get_layer(mask_id)
        if scene is None or layer is None or asset is None or layer.transform is None:
            return None
        canvas_width = round(scene.bounds.width)
        canvas_height = round(scene.bounds.height)
        incoming = normalize_coverage_array(incoming_mask)
        if incoming.shape != (canvas_height, canvas_width):
            incoming = resize_mask_nearest(
                incoming,
                (canvas_height, canvas_width),
            )
        snapshot = asset.coverage.snapshot()
        if snapshot.bounds is None:
            return None
        target = self._expanded_generated_target(
            snapshot,
            layer,
            incoming,
            canvas_x=scene.bounds.x,
            canvas_y=scene.bounds.y,
            erase=erase,
        )
        bounds = target.bounds
        transform = layer.transform
        if bounds is not None and isinstance(
            transform,
            (BilinearLayerTransform, PiecewiseLayerTransform),
        ):
            canvas_left = math.floor(scene.bounds.x)
            canvas_top = math.floor(scene.bounds.y)
            scene_coverage = CoverageSnapshot(
                RasterBounds(canvas_left, canvas_top, canvas_width, canvas_height),
                RasterExtentPolicy.FIXED,
                incoming,
            )
            projected = (
                project_scene_coverage_to_bilinear_layer(
                    scene_coverage,
                    transform,
                    layer_bounds=bounds,
                    extent_policy=target.extent_policy,
                    scene_origin_x=scene.bounds.x,
                    scene_origin_y=scene.bounds.y,
                )
                if isinstance(transform, BilinearLayerTransform)
                else project_scene_coverage_to_piecewise_layer(
                    scene_coverage,
                    transform,
                    layer_bounds=bounds,
                    extent_policy=target.extent_policy,
                )
            )
            mapped = (
                np.zeros_like(target.pixels)
                if projected is None
                else reframe_coverage_snapshot(projected, bounds).pixels
            )
            combined = combine_coverage(
                target.pixels,
                mapped,
                CoverageCombineMode.SUBTRACT if erase else CoverageCombineMode.ADD,
            )
            if target.bounds == snapshot.bounds and np.array_equal(
                combined, snapshot.pixels
            ):
                return None
            return CoverageSnapshot(bounds, target.extent_policy, combined)
        inverse = transform.inverted()
        if bounds is None or inverse is None:
            return None
        canvas_to_local = LayerTransform(
            dx=scene.bounds.x,
            dy=scene.bounds.y,
        ).followed_by(inverse)
        mapped = self._resampler.project(
            CoverageSnapshot(
                RasterBounds(0, 0, canvas_width, canvas_height),
                RasterExtentPolicy.FIXED,
                incoming,
            ),
            canvas_to_local,
            bounds,
            extent_policy=target.extent_policy,
            smooth=False,
        ).pixels
        combined = combine_coverage(
            target.pixels,
            mapped,
            CoverageCombineMode.SUBTRACT if erase else CoverageCombineMode.ADD,
        )
        if target.bounds == snapshot.bounds and np.array_equal(
            combined, snapshot.pixels
        ):
            return None
        return CoverageSnapshot(
            bounds=target.bounds,
            extent_policy=target.extent_policy,
            pixels=combined,
        )

    @staticmethod
    def _expanded_generated_target(
        snapshot: CoverageSnapshot,
        layer: LayerDescriptor,
        incoming: np.ndarray,
        *,
        canvas_x: float,
        canvas_y: float,
        erase: bool,
    ) -> CoverageSnapshot:
        """Expand an authoring snapshot to generated foreground when policy permits."""
        bounds = snapshot.bounds
        transform = layer.transform
        if (
            erase
            or bounds is None
            or transform is None
            or snapshot.extent_policy is RasterExtentPolicy.FIXED
            or not transform.is_invertible
        ):
            return snapshot
        if isinstance(
            transform,
            (BilinearLayerTransform, PiecewiseLayerTransform),
        ):
            return snapshot
        foreground_y, foreground_x = np.nonzero(incoming)
        if foreground_x.size == 0:
            return snapshot
        left = int(foreground_x.min())
        top = int(foreground_y.min())
        right = int(foreground_x.max()) + 1
        bottom = int(foreground_y.max()) + 1
        inverse = transform.inverted()
        if inverse is None:
            return snapshot
        mapped_corners = (
            inverse.map_point(QPointF(canvas_x + left, canvas_y + top)),
            inverse.map_point(QPointF(canvas_x + right, canvas_y + top)),
            inverse.map_point(QPointF(canvas_x + right, canvas_y + bottom)),
            inverse.map_point(QPointF(canvas_x + left, canvas_y + bottom)),
        )
        local_left = math.floor(min(point.x() for point in mapped_corners))
        local_top = math.floor(min(point.y() for point in mapped_corners))
        local_right = math.ceil(max(point.x() for point in mapped_corners))
        local_bottom = math.ceil(max(point.y() for point in mapped_corners))
        requested = RasterBounds(
            local_left,
            local_top,
            max(1, local_right - local_left),
            max(1, local_bottom - local_top),
        )
        if bounds.contains(requested):
            return snapshot
        return reframe_coverage_snapshot(snapshot, bounds.united(requested))

    def _layer_for_mask(
        self,
        scene: SceneDescriptor | None,
        mask_id: uuid.UUID,
    ) -> LayerDescriptor | None:
        """Find one mask source instance in ``scene``."""
        if scene is None:
            return None
        return next(
            (
                layer
                for layer in scene.layers
                if isinstance(layer.source, ProjectResourceReference)
                and layer.source.resource_id == mask_id
                and self._assets.get_layer(mask_id) is not None
            ),
            None,
        )


def project_mask_snapshot(
    snapshot: CoverageSnapshot,
    *,
    layer: LayerDescriptor,
    canvas_x: float,
    canvas_y: float,
    canvas_width: int,
    canvas_height: int,
) -> np.ndarray:
    """Nearest-sample one affine mask transform into canvas pixels."""
    bounds = snapshot.bounds
    transform = layer.transform
    if bounds is None or transform is None or not transform.is_invertible:
        return np.zeros((canvas_height, canvas_width), dtype=np.uint8)
    if isinstance(transform, BilinearLayerTransform):
        return project_bilinear_coverage(
            snapshot,
            transform,
            canvas_x=canvas_x,
            canvas_y=canvas_y,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
        )
    if isinstance(transform, PiecewiseLayerTransform):
        return project_piecewise_coverage(
            snapshot,
            transform,
            RasterBounds(
                round(canvas_x),
                round(canvas_y),
                canvas_width,
                canvas_height,
            ),
        ).pixels
    local_to_canvas = transform.translated(-canvas_x, -canvas_y)
    return (
        AffineCoverageResampler()
        .project(
            snapshot,
            local_to_canvas,
            RasterBounds(0, 0, canvas_width, canvas_height),
            extent_policy=RasterExtentPolicy.FIXED,
            smooth=False,
        )
        .pixels
    )


def project_mask_coverage_to_scene(
    snapshot: CoverageSnapshot,
    transform: LayerTransform | BilinearLayerTransform | PiecewiseLayerTransform,
) -> CoverageSnapshot | None:
    """Bake one mask mapping into minimal scene-coordinate coverage."""
    source_bounds = snapshot.bounds
    if source_bounds is None or not transform.is_invertible:
        return None
    placement = transform.map_bounds(source_bounds)
    left = math.floor(placement.x)
    top = math.floor(placement.y)
    right = math.ceil(placement.x + placement.width)
    bottom = math.ceil(placement.y + placement.height)
    if right <= left or bottom <= top:
        return None
    destination = RasterBounds(left, top, right - left, bottom - top)
    if isinstance(transform, BilinearLayerTransform):
        projected = CoverageSnapshot(
            destination,
            RasterExtentPolicy.EXPAND_ON_WRITE,
            project_bilinear_coverage(
                snapshot,
                transform,
                canvas_x=float(destination.x),
                canvas_y=float(destination.y),
                canvas_width=destination.width,
                canvas_height=destination.height,
            ),
        )
    elif isinstance(transform, PiecewiseLayerTransform):
        projected = project_piecewise_coverage(snapshot, transform, destination)
    else:
        projected = AffineCoverageResampler().project(
            snapshot,
            transform,
            destination,
            extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
            smooth=False,
        )
    occupied = occupied_coverage_bounds(projected)
    return None if occupied is None else projected.clipped_to(occupied)


__all__ = [
    "MaskCanvasProjectionService",
    "project_mask_coverage_to_scene",
    "project_mask_snapshot",
]
