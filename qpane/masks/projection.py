#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Viewport-independent projection of mask authoring surfaces onto canvases."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import numpy as np
from PySide6.QtGui import QImage

from ..catalog.image_utils import numpy_to_qimage_grayscale8
from ..scene.model import LayerDescriptor, SceneDescriptor
from ..scene.raster import RasterBounds, RasterExtentPolicy
from ..scene.sources import MaskLayerSource
from .image_ops import resize_mask_nearest
from .mask import MaskAssetStore
from .surface import (
    MaskSurfaceSnapshot,
    normalize_mask_array,
    reframe_mask_snapshot,
)


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
        surface = asset.surface

        def project() -> QImage:
            """Snapshot and project the captured source using current pixels."""
            projected = project_mask_snapshot(
                surface.snapshot(),
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
    ) -> MaskSurfaceSnapshot | None:
        """Map a canvas-sized generated mask into source-local authoring storage."""
        scene = self._active_scene()
        layer = self._layer_for_mask(scene, mask_id)
        asset = self._assets.get_layer(mask_id)
        if scene is None or layer is None or asset is None or layer.transform is None:
            return None
        canvas_width = round(scene.bounds.width)
        canvas_height = round(scene.bounds.height)
        incoming = normalize_mask_array(incoming_mask)
        if incoming.shape != (canvas_height, canvas_width):
            incoming = resize_mask_nearest(
                incoming,
                (canvas_height, canvas_width),
            )
        snapshot = asset.surface.snapshot()
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
        if bounds is None or transform.scale_x <= 0.0 or transform.scale_y <= 0.0:
            return None
        local_x = bounds.x + np.arange(bounds.width, dtype=np.float64) + 0.5
        local_y = bounds.y + np.arange(bounds.height, dtype=np.float64) + 0.5
        canvas_x = np.floor(
            local_x * transform.scale_x + transform.translate_x - scene.bounds.x
        ).astype(np.int64)
        canvas_y = np.floor(
            local_y * transform.scale_y + transform.translate_y - scene.bounds.y
        ).astype(np.int64)
        valid_x = (canvas_x >= 0) & (canvas_x < canvas_width)
        valid_y = (canvas_y >= 0) & (canvas_y < canvas_height)
        mapped = np.zeros_like(target.pixels)
        rows = np.flatnonzero(valid_y)
        columns = np.flatnonzero(valid_x)
        if rows.size and columns.size:
            mapped[np.ix_(rows, columns)] = incoming[
                np.ix_(canvas_y[valid_y], canvas_x[valid_x])
            ]
        combined = (
            np.bitwise_and(target.pixels, np.bitwise_not(mapped))
            if erase
            else np.bitwise_or(target.pixels, mapped)
        )
        if target.bounds == snapshot.bounds and np.array_equal(
            combined, snapshot.pixels
        ):
            return None
        return MaskSurfaceSnapshot(
            bounds=target.bounds,
            extent_policy=target.extent_policy,
            pixels=combined,
        )

    @staticmethod
    def _expanded_generated_target(
        snapshot: MaskSurfaceSnapshot,
        layer: LayerDescriptor,
        incoming: np.ndarray,
        *,
        canvas_x: float,
        canvas_y: float,
        erase: bool,
    ) -> MaskSurfaceSnapshot:
        """Expand an authoring snapshot to generated foreground when policy permits."""
        bounds = snapshot.bounds
        transform = layer.transform
        if (
            erase
            or bounds is None
            or transform is None
            or snapshot.extent_policy is RasterExtentPolicy.FIXED
            or transform.scale_x <= 0.0
            or transform.scale_y <= 0.0
        ):
            return snapshot
        foreground_y, foreground_x = np.nonzero(incoming)
        if foreground_x.size == 0:
            return snapshot
        left = int(foreground_x.min())
        top = int(foreground_y.min())
        right = int(foreground_x.max()) + 1
        bottom = int(foreground_y.max()) + 1
        local_left = int(
            np.floor((canvas_x + left - transform.translate_x) / transform.scale_x)
        )
        local_top = int(
            np.floor((canvas_y + top - transform.translate_y) / transform.scale_y)
        )
        local_right = int(
            np.ceil((canvas_x + right - transform.translate_x) / transform.scale_x)
        )
        local_bottom = int(
            np.ceil((canvas_y + bottom - transform.translate_y) / transform.scale_y)
        )
        requested = RasterBounds(
            local_left,
            local_top,
            max(1, local_right - local_left),
            max(1, local_bottom - local_top),
        )
        if bounds.contains(requested):
            return snapshot
        return reframe_mask_snapshot(snapshot, bounds.united(requested))

    @staticmethod
    def _layer_for_mask(
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
                if isinstance(layer.source, MaskLayerSource)
                and layer.source.mask_id == mask_id
            ),
            None,
        )


def project_mask_snapshot(
    snapshot: MaskSurfaceSnapshot,
    *,
    layer: LayerDescriptor,
    canvas_x: float,
    canvas_y: float,
    canvas_width: int,
    canvas_height: int,
) -> np.ndarray:
    """Nearest-sample one axis-aligned mask transform into canvas pixels."""
    output = np.zeros((canvas_height, canvas_width), dtype=np.uint8)
    bounds = snapshot.bounds
    transform = layer.transform
    if (
        bounds is None
        or transform is None
        or transform.scale_x <= 0.0
        or transform.scale_y <= 0.0
    ):
        return output
    scene_x = canvas_x + np.arange(canvas_width, dtype=np.float64) + 0.5
    scene_y = canvas_y + np.arange(canvas_height, dtype=np.float64) + 0.5
    source_x = np.floor((scene_x - transform.translate_x) / transform.scale_x).astype(
        np.int64
    )
    source_y = np.floor((scene_y - transform.translate_y) / transform.scale_y).astype(
        np.int64
    )
    storage_x = source_x - bounds.x
    storage_y = source_y - bounds.y
    valid_x = (storage_x >= 0) & (storage_x < bounds.width)
    valid_y = (storage_y >= 0) & (storage_y < bounds.height)
    output_rows = np.flatnonzero(valid_y)
    output_columns = np.flatnonzero(valid_x)
    if output_rows.size == 0 or output_columns.size == 0:
        return output
    output[np.ix_(output_rows, output_columns)] = snapshot.pixels[
        np.ix_(storage_y[valid_y], storage_x[valid_x])
    ]
    return output
