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
"""Translate stable render products for guard-covered viewport navigation."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPoint, QPointF, QRectF

from ..scene.render_plan import (
    RasterLayerRenderItem,
    SampledLayerRenderItem,
    SceneRenderItem,
    SceneRenderPlan,
    VectorLayerRenderItem,
)
from .navigation_mapping import retained_mapping_delta, translate_render_item
from .rectangle_coverage import rectangles_cover

_RETAINED_RASTER_ITEM_TYPES = (RasterLayerRenderItem, SampledLayerRenderItem)


def translated_navigation_plan(
    plan: SceneRenderPlan,
    target_pan: QPointF,
    *,
    device_pixel_ratio: float,
) -> SceneRenderPlan:
    """Project stable frame products to a guard-covered pan position."""

    dpr = device_pixel_ratio if device_pixel_ratio > 0.0 else 1.0
    delta = (QPointF(target_pan) - plan.current_pan) / dpr
    items = tuple(translate_render_item(item, delta) for item in plan.render_items)
    return replace(
        plan,
        current_pan=QPointF(target_pan),
        render_items=items,
    )


def sampled_navigation_plan_covers_panel_rect(
    plan: SceneRenderPlan,
    panel_rect: QRectF,
) -> bool:
    """Return whether retained sampled products cover one panel rectangle."""
    return all(
        _sampled_item_covers_panel_rect(item, panel_rect)
        for item in plan.render_items
        if item.descriptor.visible and isinstance(item, SampledLayerRenderItem)
    )


def navigation_products_match(
    first: SceneRenderPlan,
    second: SceneRenderPlan,
) -> bool:
    """Return whether two navigation plans resolve to identical source products."""
    first_visible = tuple(
        item for item in first.render_items if item.descriptor.visible
    )
    second_visible = tuple(
        item for item in second.render_items if item.descriptor.visible
    )
    if len(first_visible) != len(second_visible):
        return False
    return all(
        _product_identity(first_item) == _product_identity(second_item)
        for first_item, second_item in zip(first_visible, second_visible, strict=True)
    )


def navigation_repair_sources_match(
    first: SceneRenderPlan,
    second: SceneRenderPlan,
) -> bool:
    """Return whether spatially different products share current source pixels."""
    first_visible = tuple(
        item for item in first.render_items if item.descriptor.visible
    )
    second_visible = tuple(
        item for item in second.render_items if item.descriptor.visible
    )
    if len(first_visible) != len(second_visible):
        return False
    for first_item, second_item in zip(first_visible, second_visible, strict=True):
        first_identity = _repair_source_identity(first_item)
        if first_identity is None or first_identity != _repair_source_identity(
            second_item
        ):
            return False
    return True


def retained_raster_navigation_delta(
    first: SceneRenderPlan,
    second: SceneRenderPlan,
    *,
    device_pixel_ratio: float,
) -> QPoint | None:
    """Return one exact physical translation shared by all retained raster items."""
    if device_pixel_ratio <= 0.0:
        raise ValueError("device_pixel_ratio must be positive")
    first_visible = tuple(
        item for item in first.render_items if item.descriptor.visible
    )
    second_visible = tuple(
        item for item in second.render_items if item.descriptor.visible
    )
    if len(first_visible) != len(second_visible) or not first_visible:
        return None
    shared_delta: QPoint | None = None
    for first_item, second_item in zip(
        first_visible,
        second_visible,
        strict=True,
    ):
        if (
            type(first_item) is not type(second_item)
            or not isinstance(first_item, _RETAINED_RASTER_ITEM_TYPES)
            or first_item.descriptor != second_item.descriptor
            or retained_mapping_delta(
                first_item.transform,
                second_item.transform,
                device_pixel_ratio=device_pixel_ratio,
            )
            is None
        ):
            return None
        item_delta = retained_mapping_delta(
            first_item.transform,
            second_item.transform,
            device_pixel_ratio=device_pixel_ratio,
        )
        assert item_delta is not None
        if shared_delta is None:
            shared_delta = item_delta
        elif item_delta != shared_delta:
            return None
    return shared_delta


def _sampled_item_covers_panel_rect(
    item: SampledLayerRenderItem,
    panel_rect: QRectF,
) -> bool:
    """Return whether one sampled item can paint its visible panel coverage."""
    panel_to_source, invertible = item.transform.inverted()
    if not invertible:
        return True
    source_bounds = QRectF(
        0.0,
        0.0,
        float(item.source_size.width()),
        float(item.source_size.height()),
    )
    required = panel_to_source.mapRect(panel_rect).intersected(source_bounds)
    if required.isEmpty():
        return True
    return rectangles_cover(required, tuple(tile.source_rect for tile in item.tiles))


def _product_identity(item: SceneRenderItem) -> tuple[object, ...]:
    """Return immutable resolved-pixel identity independent of viewport placement."""
    common = (type(item), item.descriptor, item.placement, item.clip)
    if isinstance(item, RasterLayerRenderItem):
        return (
            *common,
            item.asset_key,
            item.pyramid_asset_key,
            item.pyramid_scale,
            item.strategy,
            item.source_image.cacheKey(),
            tuple(
                (
                    tile.image.cacheKey(),
                    tile.draw_pos.x(),
                    tile.draw_pos.y(),
                )
                for tile in item.tiles_to_draw
            ),
        )
    if isinstance(item, SampledLayerRenderItem):
        return (
            *common,
            None if item.source_bounds is None else _rect_identity(item.source_bounds),
            tuple(
                (
                    tile.image.cacheKey(),
                    _rect_identity(tile.source_rect),
                    _rect_identity(tile.image_source_rect),
                    (
                        None
                        if tile.source_clip_rect is None
                        else _rect_identity(tile.source_clip_rect)
                    ),
                    tile.integer_origin_sampling,
                )
                for tile in item.tiles
            ),
        )
    if isinstance(item, VectorLayerRenderItem):
        return (
            *common,
            bytes(item.picture.data() or b""),
            tuple(
                (
                    tile.image.cacheKey(),
                    _rect_identity(tile.source_rect),
                    _rect_identity(tile.image_source_rect),
                )
                for tile in item.refined_tiles
            ),
        )
    raise TypeError(f"Unsupported render item: {type(item)!r}")


def _repair_source_identity(item: SceneRenderItem) -> tuple[object, ...] | None:
    """Return stable source identity independent of spatial tile selection."""
    common = (
        type(item),
        item.descriptor,
        item.placement,
        item.clip,
        item.source_size,
        item.render_hint_enabled,
    )
    if isinstance(item, RasterLayerRenderItem):
        return (
            *common,
            item.asset_key,
            item.pyramid_asset_key,
            item.pyramid_scale,
            item.strategy,
            item.source_image.cacheKey(),
        )
    if isinstance(item, SampledLayerRenderItem):
        return common
    return None


def _rect_identity(rect: QRectF) -> tuple[float, float, float, float]:
    """Return stable scalar geometry for one detached floating rectangle."""
    return (rect.x(), rect.y(), rect.width(), rect.height())


__all__ = [
    "navigation_products_match",
    "navigation_repair_sources_match",
    "retained_raster_navigation_delta",
    "sampled_navigation_plan_covers_panel_rect",
    "translated_navigation_plan",
]
