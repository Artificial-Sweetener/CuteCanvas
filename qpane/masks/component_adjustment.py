#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Reusable connected-component adjustment for mask editing tools."""

from __future__ import annotations

import logging
import uuid

from PySide6.QtCore import QPoint

from ..coverage import CoverageSnapshot, reframe_coverage_snapshot
from ..scene.raster import RasterBounds, RasterExtentPolicy
from .image_ops import adjust_connected_component, connected_component_extent
from .mask import MaskAssetStore

logger = logging.getLogger(__name__)


class MaskComponentAdjustmentTool:
    """Grow or shrink the connected mask component under a point."""

    def __init__(self, assets: MaskAssetStore) -> None:
        """Bind authoritative mask surfaces without depending on SAM."""
        self._assets = assets

    def adjusted_surface(
        self,
        mask_id: uuid.UUID,
        point: QPoint,
        *,
        grow: bool,
    ) -> CoverageSnapshot | None:
        """Return a policy-aware component edit without committing it."""
        layer = self._assets.get_layer(mask_id)
        if layer is None:
            logger.warning("Cannot adjust mask %s: no mask data available.", mask_id)
            return None
        snapshot = layer.surface.snapshot()
        bounds = snapshot.bounds
        if bounds is None:
            return None
        local_x = int(point.x())
        local_y = int(point.y())
        x = local_x - bounds.x
        y = local_y - bounds.y
        if x < 0 or y < 0 or x >= bounds.width or y >= bounds.height:
            logger.warning(
                "Ignoring component adjustment at (%s, %s): outside mask bounds %sx%s for mask %s.",
                local_x,
                local_y,
                bounds.width,
                bounds.height,
                mask_id,
            )
            return None
        if grow and snapshot.extent_policy is RasterExtentPolicy.EXPAND_ON_WRITE:
            extent = connected_component_extent(snapshot.pixels, x=x, y=y)
            if extent is not None:
                snapshot = self._expand_touched_edges(snapshot, extent)
                bounds = snapshot.bounds
                if (
                    bounds is None
                ):  # pragma: no cover - positive source remains positive
                    return None
                x = local_x - bounds.x
                y = local_y - bounds.y
        adjusted = adjust_connected_component(snapshot.pixels, x=x, y=y, grow=grow)
        if adjusted is None:
            return None
        return CoverageSnapshot(
            bounds=snapshot.bounds,
            extent_policy=snapshot.extent_policy,
            pixels=adjusted,
        )

    @staticmethod
    def _expand_touched_edges(
        snapshot: CoverageSnapshot,
        extent: tuple[int, int, int, int],
    ) -> CoverageSnapshot:
        """Grow storage only across edges touched by the selected component."""
        bounds = snapshot.bounds
        if bounds is None:
            return snapshot
        left, top, right, bottom = extent
        grow_left = left == 0
        grow_top = top == 0
        grow_right = right == bounds.width
        grow_bottom = bottom == bounds.height
        if not (grow_left or grow_top or grow_right or grow_bottom):
            return snapshot
        expanded = RasterBounds(
            bounds.x - int(grow_left),
            bounds.y - int(grow_top),
            bounds.width + int(grow_left) + int(grow_right),
            bounds.height + int(grow_top) + int(grow_bottom),
        )
        return reframe_coverage_snapshot(snapshot, expanded)
