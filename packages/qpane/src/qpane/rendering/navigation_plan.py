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
from PySide6.QtGui import QTransform

from ..scene.render_plan import (
    RasterLayerRenderItem,
    SampledLayerRenderItem,
    SceneRenderItem,
    SceneRenderPlan,
    VectorLayerRenderItem,
)
from .raster_sampling import device_aligned_raster_transform

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
    items = tuple(_translate_item(item, delta) for item in plan.render_items)
    return replace(
        plan,
        current_pan=QPointF(target_pan),
        render_items=items,
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
            or not _linear_transform_matches(
                first_item.transform, second_item.transform
            )
        ):
            return None
        first_transform = device_aligned_raster_transform(
            first_item.transform,
            device_pixel_ratio,
        )
        second_transform = device_aligned_raster_transform(
            second_item.transform,
            device_pixel_ratio,
        )
        item_delta = QPoint(
            round(
                (second_transform.m31() - first_transform.m31()) * device_pixel_ratio
            ),
            round(
                (second_transform.m32() - first_transform.m32()) * device_pixel_ratio
            ),
        )
        if shared_delta is None:
            shared_delta = item_delta
        elif item_delta != shared_delta:
            return None
    return shared_delta


def _translate_item(item: SceneRenderItem, delta: QPointF) -> SceneRenderItem:
    """Translate one immutable item in logical painter coordinates."""

    transform = item.transform
    translated = QTransform(
        transform.m11(),
        transform.m12(),
        transform.m13(),
        transform.m21(),
        transform.m22(),
        transform.m23(),
        transform.dx() + delta.x(),
        transform.dy() + delta.y(),
        transform.m33(),
    )
    return replace(item, transform=translated)


def _linear_transform_matches(first: QTransform, second: QTransform) -> bool:
    """Return whether two affine transforms differ only in translation."""
    return (
        first.m11() == second.m11()
        and first.m12() == second.m12()
        and first.m13() == second.m13()
        and first.m21() == second.m21()
        and first.m22() == second.m22()
        and first.m23() == second.m23()
        and first.m33() == second.m33()
    )


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


def _rect_identity(rect: QRectF) -> tuple[float, float, float, float]:
    """Return stable scalar geometry for one detached floating rectangle."""
    return (rect.x(), rect.y(), rect.width(), rect.height())


__all__ = [
    "navigation_products_match",
    "retained_raster_navigation_delta",
    "translated_navigation_plan",
]
