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

"""Composite transient effects from the same resolved layer render products."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from ..raster.image_conversion import (
    qimage_to_numpy_const_view_argb32,
    qimage_to_numpy_view_argb32,
)
from ..scene.presentation_effects import (
    LayerPresentationEffect,
    LayerPresentationEffectKind,
    LayerPresentationStyle,
)
from ..scene.render_plan import SceneRenderItem, SceneRenderPlan
from .storage_allocation import checked_argb_image, checked_painter, require_image

DrawLayerItems = Callable[
    [QPainter, SceneRenderPlan, tuple[SceneRenderItem, ...]], None
]
ItemBounds = Callable[[SceneRenderItem], QRect]


@dataclass(frozen=True, slots=True)
class _CoverageProduct:
    """Carry one visible-layer coverage image and its panel-space placement."""

    image: QImage
    panel_bounds: QRect


class LayerPresentationEffectCompositor:
    """Draw ordered transient treatments over resolved scene content."""

    def draw(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        *,
        draw_layer_items: DrawLayerItems,
        item_bounds: ItemBounds,
    ) -> None:
        """Draw all plan effects without reading or re-resolving source domains."""
        if not plan.presentation_effects:
            return
        items_by_layer = _visible_items_by_layer(plan.render_items)
        effects_by_layer = _effects_by_layer(plan.presentation_effects)
        coverage_products: dict[uuid.UUID, _CoverageProduct | None] = {}
        for effect in plan.presentation_effects:
            items = items_by_layer.get(effect.layer_id)
            if not items:
                continue
            if effect.style.kind is LayerPresentationEffectKind.BOUNDS:
                self._draw_bounds(painter, items, effect.style, item_bounds)
                continue
            if effect.layer_id not in coverage_products:
                padding = max(
                    candidate.style.panel_padding
                    for candidate in effects_by_layer[effect.layer_id]
                )
                coverage_products[effect.layer_id] = self._render_coverage(
                    painter,
                    plan,
                    items,
                    padding=padding,
                    draw_layer_items=draw_layer_items,
                    item_bounds=item_bounds,
                )
            product = coverage_products[effect.layer_id]
            if product is not None:
                self._draw_content_effect(painter, product, effect.style)

    @staticmethod
    def _render_coverage(
        painter: QPainter,
        plan: SceneRenderPlan,
        items: tuple[SceneRenderItem, ...],
        *,
        padding: float,
        draw_layer_items: DrawLayerItems,
        item_bounds: ItemBounds,
    ) -> _CoverageProduct | None:
        """Rasterize one visible layer group into a tightly bounded panel product."""
        panel_bounds = _combined_bounds(items, item_bounds)
        if panel_bounds.isEmpty():
            return None
        extent = max(1, math.ceil(padding))
        panel_bounds = panel_bounds.adjusted(-extent, -extent, extent, extent)
        panel_bounds = panel_bounds.intersected(
            plan.qpane_rect.adjusted(-extent, -extent, extent, extent)
        )
        if painter.hasClipping():
            panel_bounds = panel_bounds.intersected(
                painter.clipBoundingRect()
                .toAlignedRect()
                .adjusted(
                    -extent,
                    -extent,
                    extent,
                    extent,
                )
            )
        if panel_bounds.isEmpty():
            return None
        device = painter.device()
        dpr = max(1.0, float(device.devicePixelRatioF()))
        physical_size = QSize(
            max(1, math.ceil(panel_bounds.width() * dpr)),
            max(1, math.ceil(panel_bounds.height() * dpr)),
        )
        coverage = checked_argb_image(physical_size, device_pixel_ratio=dpr)
        coverage.fill(Qt.GlobalColor.transparent)
        coverage_painter = checked_painter(coverage, "effect coverage")
        try:
            coverage_painter.translate(-panel_bounds.left(), -panel_bounds.top())
            draw_layer_items(coverage_painter, plan, items)
        finally:
            coverage_painter.end()
        return _CoverageProduct(coverage, panel_bounds)

    @staticmethod
    def _draw_content_effect(
        painter: QPainter,
        product: _CoverageProduct,
        style: LayerPresentationStyle,
    ) -> None:
        """Colorize and draw one coverage-aware effect product."""
        silhouette = _colorized_silhouette(product.image, style.color)
        kind = style.kind
        if kind is LayerPresentationEffectKind.CONTENT_TINT:
            painter.save()
            try:
                painter.setOpacity(style.opacity)
                painter.drawImage(product.panel_bounds.topLeft(), silhouette)
            finally:
                painter.restore()
            return
        if kind is LayerPresentationEffectKind.CONTENT_OUTLINE:
            effect_image = _outer_outline(
                silhouette,
                product.image,
                style.width,
                style.opacity,
            )
        elif kind is LayerPresentationEffectKind.CONTENT_GLOW:
            effect_image = _outer_glow(
                silhouette,
                product.image,
                style.radius,
                style.opacity,
            )
        else:
            return
        painter.drawImage(product.panel_bounds.topLeft(), effect_image)

    @staticmethod
    def _draw_bounds(
        painter: QPainter,
        items: tuple[SceneRenderItem, ...],
        style: LayerPresentationStyle,
        item_bounds: ItemBounds,
    ) -> None:
        """Draw one cosmetic rectangle around the target's rendered products."""
        bounds = _combined_bounds(items, item_bounds)
        if bounds.isEmpty():
            return
        color = QColor(style.color)
        color.setAlphaF(color.alphaF() * style.opacity)
        pen = QPen(color, style.width)
        pen.setCosmetic(True)
        painter.save()
        try:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(pen)
            inset = style.width * 0.5
            painter.drawRect(QRectF(bounds).adjusted(inset, inset, -inset, -inset))
        finally:
            painter.restore()


def _visible_items_by_layer(
    items: tuple[SceneRenderItem, ...],
) -> dict[uuid.UUID, tuple[SceneRenderItem, ...]]:
    """Group visible render products by layer while preserving plan order."""
    grouped: dict[uuid.UUID, list[SceneRenderItem]] = {}
    for item in items:
        if item.descriptor.visible and item.descriptor.opacity > 0.0:
            grouped.setdefault(item.descriptor.layer_id, []).append(item)
    return {layer_id: tuple(values) for layer_id, values in grouped.items()}


def _effects_by_layer(
    effects: tuple[LayerPresentationEffect, ...],
) -> dict[uuid.UUID, tuple[LayerPresentationEffect, ...]]:
    """Group effects by target while retaining registration order."""
    grouped: dict[uuid.UUID, list[LayerPresentationEffect]] = {}
    for effect in effects:
        grouped.setdefault(effect.layer_id, []).append(effect)
    return {layer_id: tuple(values) for layer_id, values in grouped.items()}


def _combined_bounds(
    items: tuple[SceneRenderItem, ...],
    item_bounds: ItemBounds,
) -> QRect:
    """Return the conservative panel union for one resolved layer group."""
    combined = QRect()
    for item in items:
        bounds = item_bounds(item)
        combined = QRect(bounds) if combined.isEmpty() else combined.united(bounds)
    return combined


def _colorized_silhouette(image: QImage, color: QColor) -> QImage:
    """Replace RGB content while preserving the source product's exact alpha."""
    result = QImage(image)
    painter = checked_painter(result, "effect composition")
    try:
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(result.rect(), QColor(color))
    finally:
        painter.end()
    return result


def _outer_outline(
    silhouette: QImage,
    coverage: QImage,
    width: float,
    opacity: float,
) -> QImage:
    """Build an outer coverage outline with bounded Qt-native offset draws."""
    radius = max(1, math.ceil(width))
    offsets = tuple(
        QPointF(float(x), float(y))
        for y in range(-radius, radius + 1)
        for x in range(-radius, radius + 1)
        if x * x + y * y <= radius * radius
    )
    return _offset_effect(silhouette, coverage, ((offsets, opacity),))


def _outer_glow(
    silhouette: QImage,
    coverage: QImage,
    radius: float,
    opacity: float,
) -> QImage:
    """Build a restrained multi-ring halo around visible coverage."""
    if max(silhouette.width(), silhouette.height()) > 320 and radius >= 4.0:
        scale = min(1.0, 320.0 / max(silhouette.width(), silhouette.height()))
        small_size = QSize(
            max(1, round(silhouette.width() * scale)),
            max(1, round(silhouette.height() * scale)),
        )
        small_silhouette = require_image(
            silhouette.scaled(
                small_size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ),
            "presentation effect silhouette downscale",
        )
        small_coverage = require_image(
            coverage.scaled(
                small_size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ),
            "presentation effect coverage downscale",
        )
        small = _outer_glow(
            small_silhouette,
            small_coverage,
            max(1.0, radius * scale),
            opacity,
        )
        expanded = require_image(
            small.scaled(
                silhouette.size(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ),
            "presentation effect expansion",
        )
        expanded.setDevicePixelRatio(silhouette.devicePixelRatioF())
        painter = checked_painter(expanded, "effect expansion")
        try:
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_DestinationOut
            )
            painter.drawImage(QPointF(), coverage)
        finally:
            painter.end()
        return expanded
    rings: list[tuple[tuple[QPointF, ...], float]] = []
    for fraction in (0.25, 0.5, 0.75, 1.0):
        distance = max(1.0, radius * fraction)
        count = max(8, min(24, math.ceil(math.tau * distance)))
        offsets = tuple(
            QPointF(
                math.cos(math.tau * index / count) * distance,
                math.sin(math.tau * index / count) * distance,
            )
            for index in range(count)
        )
        rings.append((offsets, opacity * (1.0 - 0.68 * fraction)))
    return _offset_effect(silhouette, coverage, tuple(rings))


def _offset_effect(
    silhouette: QImage,
    coverage: QImage,
    groups: tuple[tuple[tuple[QPointF, ...], float], ...],
) -> QImage:
    """Draw offset silhouettes and subtract original coverage from the result."""
    result = checked_argb_image(
        silhouette.size(),
        device_pixel_ratio=silhouette.devicePixelRatioF(),
    )
    result.fill(Qt.GlobalColor.transparent)
    painter = checked_painter(result, "effect colorization")
    try:
        for offsets, opacity in groups:
            painter.setOpacity(max(0.0, min(1.0, opacity)))
            for offset in offsets:
                painter.drawImage(offset, silhouette)
        painter.setOpacity(1.0)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_DestinationOut
        )
        painter.drawImage(QPointF(), _opaque_support(coverage))
    finally:
        painter.end()
    return result


def _opaque_support(coverage: QImage) -> QImage:
    """Return full alpha wherever rendered layer coverage is nonzero."""
    coverage_pixels, coverage_backing = qimage_to_numpy_const_view_argb32(coverage)
    support = checked_argb_image(
        coverage_backing.size(),
        device_pixel_ratio=coverage_backing.devicePixelRatioF(),
    )
    support.fill(Qt.GlobalColor.transparent)
    support_pixels, support_backing = qimage_to_numpy_view_argb32(support)
    support_pixels[coverage_pixels[..., 3] != 0] = 255
    return support_backing
