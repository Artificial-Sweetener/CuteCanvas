#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Track conservative panel damage from actual floating render products."""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF

from ..scene.model import LayerPlacement
from ..scene.raster import RasterBounds
from ..scene.render_plan import (
    FloatingPixelResolvedContribution,
    FloatingPixelTransformContribution,
    RasterLayerRenderItem,
    SceneRenderPlan,
)

_FILTER_FRINGE_PX = 4.0


def floating_pixel_transition_damage(
    previous: SceneRenderPlan | None,
    current: SceneRenderPlan,
) -> QRectF | None:
    """Return the union touched by previous and current floating products."""
    rectangles = tuple(
        rect
        for plan in (previous, current)
        if plan is not None
        if (rect := _floating_product_bounds(plan)) is not None
    )
    if not rectangles:
        return None
    damage = QRectF(rectangles[0])
    for rectangle in rectangles[1:]:
        damage = damage.united(rectangle)
    return damage.adjusted(
        -_FILTER_FRINGE_PX,
        -_FILTER_FRINGE_PX,
        _FILTER_FRINGE_PX,
        _FILTER_FRINGE_PX,
    )


def _floating_product_bounds(plan: SceneRenderPlan) -> QRectF | None:
    """Project one plan's concrete floating contribution into panel space."""
    preview = plan.floating_pixels
    if preview is None:
        return None
    item = next(
        (
            candidate
            for candidate in plan.render_items
            if isinstance(candidate, RasterLayerRenderItem)
            and candidate.descriptor.scene_id == preview.scene_id
            and candidate.descriptor.layer_id == preview.layer_id
        ),
        None,
    )
    if item is None:
        return None
    if isinstance(preview, FloatingPixelResolvedContribution):
        return _map_local_bounds(item, preview.source_bounds)
    if not isinstance(preview, FloatingPixelTransformContribution):
        return None
    local_bounds: list[RasterBounds] = []
    if preview.source_patch is not None:
        _append_visible_bounds(
            local_bounds,
            preview.source_bounds,
            preview.extent_clip_bounds,
        )
    mapped = preview.fragment_transform.map_bounds(preview.fragment_bounds)
    _append_visible_placement(local_bounds, mapped, preview.extent_clip_bounds)
    if not local_bounds:
        return None
    rectangles = tuple(_map_local_bounds(item, bounds) for bounds in local_bounds)
    damage = QRectF(rectangles[0])
    for rectangle in rectangles[1:]:
        damage = damage.united(rectangle)
    return damage


def _append_visible_bounds(
    destination: list[RasterBounds],
    bounds: RasterBounds,
    clip_bounds: RasterBounds | None,
) -> None:
    """Append the visible local portion of one transient product."""
    visible = bounds if clip_bounds is None else bounds.intersection(clip_bounds)
    if visible is not None:
        destination.append(visible)


def _append_visible_placement(
    destination: list[RasterBounds],
    placement: LayerPlacement,
    clip_bounds: RasterBounds | None,
) -> None:
    """Append conservative integer bounds for one affine local placement."""
    bounds = RasterBounds(
        math.floor(placement.x),
        math.floor(placement.y),
        max(1, math.ceil(placement.x + placement.width) - math.floor(placement.x)),
        max(1, math.ceil(placement.y + placement.height) - math.floor(placement.y)),
    )
    _append_visible_bounds(destination, bounds, clip_bounds)


def _map_local_bounds(
    item: RasterLayerRenderItem,
    bounds: RasterBounds,
) -> QRectF:
    """Map authoritative raster-local bounds through the current source product."""
    raster_bounds = item.descriptor.raster_bounds
    if raster_bounds is None or raster_bounds.width <= 0 or raster_bounds.height <= 0:
        return QRectF()
    scale_x = item.source_image.width() / raster_bounds.width
    scale_y = item.source_image.height() / raster_bounds.height
    product_rect = QRectF(
        (bounds.x - raster_bounds.x) * scale_x,
        (bounds.y - raster_bounds.y) * scale_y,
        bounds.width * scale_x,
        bounds.height * scale_y,
    )
    return item.transform.mapRect(product_rect)
