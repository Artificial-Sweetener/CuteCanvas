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
"""Source-neutral offscreen sampling of bounded scene regions."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPainter, QTransform

from ..hybrid.evaluation import HybridDocumentEvaluator
from ..hybrid.presentation import present_hybrid_coverage
from ..rendering.render_tile_types import RegionSampleSource
from ..rendering.sdk import HybridSource
from ..scene.affine import LayerTransform
from ..scene.effects import LayerEffectRenderRegistry
from ..scene.model import (
    ClipCoordinateSpace,
    LayerClip,
    LayerDescriptor,
    SceneDescriptor,
)
from ..scene.raster import RasterBounds
from ..scene.source_capabilities import LayerSourceCapabilities
from ..vector.drawing import draw_vector_document
from ..vector.snapshot import VectorPresentationSnapshot


@runtime_checkable
class RasterLayerRegionOverride(Protocol):
    """Override pixels for selected raster layers during one scene sample."""

    def sample(
        self,
        layer: LayerDescriptor,
        local_bounds: RasterBounds,
    ) -> QImage | None:
        """Return exact pixels for ``local_bounds`` or defer to the source owner."""
        ...


@dataclass(frozen=True, slots=True)
class SceneLayerRenderScope:
    """Select scene layers for one offscreen render while preserving stack order."""

    layer_ids: frozenset[uuid.UUID] | None = None

    def __post_init__(self) -> None:
        """Normalize an optional layer-ID collection into an immutable set."""
        if self.layer_ids is None:
            return
        normalized = frozenset(self.layer_ids)
        if not all(isinstance(layer_id, uuid.UUID) for layer_id in normalized):
            raise TypeError("scene render scope layer IDs must be UUIDs")
        object.__setattr__(self, "layer_ids", normalized)

    def includes(self, layer_id: uuid.UUID) -> bool:
        """Return whether one layer participates in this render."""
        return self.layer_ids is None or layer_id in self.layer_ids


class SceneRegionRasterizer:
    """Render one transformed scene window without materializing full layers."""

    def __init__(
        self,
        source_capabilities: LayerSourceCapabilities,
        *,
        layer_effects: LayerEffectRenderRegistry | None = None,
    ) -> None:
        """Bind source presentation and optional generic effect owners."""
        self._sources = source_capabilities
        self._layer_effects = layer_effects
        self._hybrid_evaluator = HybridDocumentEvaluator()

    def rasterize(
        self,
        scene: SceneDescriptor,
        pixel_size: QSize,
        scene_to_pixels: QTransform,
        *,
        layer_scope: SceneLayerRenderScope | None = None,
        raster_override: RasterLayerRegionOverride | None = None,
    ) -> QImage:
        """Return a premultiplied sample through the scene's exact layer geometry.

        Args:
            scene: Immutable source scene.
            pixel_size: Positive output dimensions.
            scene_to_pixels: Affine mapping from scene coordinates to output pixels.
            layer_scope: Optional subset rendered in the scene's existing stack order.
            raster_override: Optional revision-stable raster source override.

        Returns:
            Transparent premultiplied pixels matching ``pixel_size``.

        Raises:
            ValueError: If the output or transform cannot be sampled.
            MemoryError: If Qt cannot allocate the output image.
            RuntimeError: If Qt cannot activate the output painter.
        """
        if pixel_size.isEmpty():
            raise ValueError("scene sample size must be positive")
        if not scene_to_pixels.isAffine():
            raise ValueError("scene sample transform must be affine")
        _, invertible = scene_to_pixels.inverted()
        if not invertible:
            raise ValueError("scene sample transform must be invertible")
        output = QImage(pixel_size, QImage.Format.Format_ARGB32_Premultiplied)
        if output.isNull():
            raise MemoryError("scene sample image could not be allocated")
        output.fill(0)
        painter = QPainter(output)
        if not painter.isActive():
            raise RuntimeError("scene sample painter could not be activated")
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            for layer in scene.layers:
                if (
                    layer.visible
                    and layer.opacity > 0.0
                    and (layer_scope is None or layer_scope.includes(layer.layer_id))
                ):
                    self._draw_layer(
                        painter,
                        scene,
                        layer,
                        pixel_size,
                        scene_to_pixels,
                        raster_override,
                    )
        finally:
            painter.end()
        return output

    def _draw_layer(
        self,
        painter: QPainter,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        pixel_size: QSize,
        scene_to_pixels: QTransform,
        raster_override: RasterLayerRegionOverride | None,
    ) -> None:
        """Draw one source through its registered closed presentation."""
        local_to_scene = layer.transform
        if local_to_scene is None or not local_to_scene.is_invertible:
            return
        visible_local = _visible_local_bounds(
            scene,
            layer,
            pixel_size,
            scene_to_pixels,
        )
        if visible_local is None:
            return
        local_to_pixels = local_to_scene.followed_by(
            LayerTransform.from_qtransform(scene_to_pixels)
        ).to_qtransform()
        painter.save()
        try:
            _apply_layer_clip(
                painter,
                scene,
                layer.clip,
                pixel_size,
                scene_to_pixels,
            )
            painter.setWorldTransform(local_to_pixels)
            self._apply_layer_effects(painter, layer)
            painter.setOpacity(layer.opacity)
            vector = self._sources.vectors.vector_document(layer.source)
            if isinstance(vector, VectorPresentationSnapshot):
                draw_vector_document(painter, vector.document)
                return
            hybrid = self._sources.hybrids.hybrid_document(layer.source)
            if isinstance(hybrid, HybridSource):
                self._draw_hybrid(painter, hybrid, visible_local, local_to_pixels)
                return
            sampled = self._sources.sampled.sampled_source(layer.source)
            if isinstance(sampled, RegionSampleSource):
                self._draw_sampled(painter, sampled, visible_local, local_to_pixels)
                return
            self._draw_raster(
                painter,
                layer,
                visible_local,
                raster_override,
            )
        finally:
            painter.restore()

    def _draw_raster(
        self,
        painter: QPainter,
        layer: LayerDescriptor,
        visible_local: RasterBounds,
        raster_override: RasterLayerRegionOverride | None,
    ) -> None:
        """Draw override, sparse, or dense raster pixels in that order."""
        if raster_override is not None:
            overridden = raster_override.sample(layer, visible_local)
            if overridden is not None:
                _draw_exact_region(painter, visible_local, overridden)
                return
        patch_owner = self._sources.raster_patches.owner_for(layer.source)
        if patch_owner is not None:
            patches = patch_owner.source_patches(layer.source, visible_local)
            if patches is not None:
                for patch in patches:
                    sample_bounds = patch.sample_bounds
                    if sample_bounds is None or patch.image.isNull():
                        continue
                    painter.save()
                    try:
                        painter.setClipRect(
                            _rectf(patch.bounds),
                            Qt.ClipOperation.IntersectClip,
                        )
                        painter.drawImage(
                            _rectf(sample_bounds),
                            patch.image,
                            QRectF(patch.image.rect()),
                        )
                    finally:
                        painter.restore()
                return
        image = self._sources.rasters.source_image(layer.source)
        bounds = layer.raster_bounds
        if image is not None and not image.isNull() and bounds is not None:
            painter.drawImage(_rectf(bounds), image, QRectF(image.rect()))

    def _draw_hybrid(
        self,
        painter: QPainter,
        source: HybridSource,
        visible_local: RasterBounds,
        local_to_pixels: QTransform,
    ) -> None:
        """Sample one hybrid document only at the required output density."""
        source_rect = _rectf(visible_local)
        scale_x = math.hypot(local_to_pixels.m11(), local_to_pixels.m12())
        scale_y = math.hypot(local_to_pixels.m21(), local_to_pixels.m22())
        sample_size = QSize(
            max(1, math.ceil(source_rect.width() * scale_x)),
            max(1, math.ceil(source_rect.height() * scale_y)),
        )
        coverage = self._hybrid_evaluator.evaluate(
            source.document,
            source_rect,
            sample_size,
        )
        presented = present_hybrid_coverage(coverage, source.style)
        painter.drawImage(source_rect, presented, QRectF(presented.rect()))

    @staticmethod
    def _draw_sampled(
        painter: QPainter,
        source: RegionSampleSource,
        visible_local: RasterBounds,
        local_to_pixels: QTransform,
    ) -> None:
        """Sample one procedural source only at the required output density."""
        source_rect = _rectf(visible_local)
        scale_x = math.hypot(local_to_pixels.m11(), local_to_pixels.m12())
        scale_y = math.hypot(local_to_pixels.m21(), local_to_pixels.m22())
        sample_size = QSize(
            max(1, math.ceil(source_rect.width() * scale_x)),
            max(1, math.ceil(source_rect.height() * scale_y)),
        )
        image = source.sample(source_rect, sample_size)
        if not image.isNull():
            painter.drawImage(source_rect, image, QRectF(image.rect()))

    def _apply_layer_effects(
        self,
        painter: QPainter,
        layer: LayerDescriptor,
    ) -> None:
        """Apply generic target-local effect geometry when registered."""
        if self._layer_effects is None:
            return
        clip = self._layer_effects.combined_clip(
            layer.effects,
            layer.raster_bounds,
        )
        if clip is not None:
            painter.setClipPath(clip, Qt.ClipOperation.IntersectClip)


def _visible_local_bounds(
    scene: SceneDescriptor,
    layer: LayerDescriptor,
    pixel_size: QSize,
    scene_to_pixels: QTransform,
) -> RasterBounds | None:
    """Return the conservative local integer region contributing to output."""
    pixels_to_scene, invertible = scene_to_pixels.inverted()
    if not invertible or layer.transform is None:
        return None
    scene_rect = pixels_to_scene.mapRect(
        QRectF(0.0, 0.0, pixel_size.width(), pixel_size.height())
    )
    canvas = QRectF(
        scene.bounds.x,
        scene.bounds.y,
        scene.bounds.width,
        scene.bounds.height,
    )
    scene_rect = scene_rect.intersected(canvas)
    inverse = layer.transform.inverted()
    bounds = layer.raster_bounds
    if scene_rect.isEmpty() or inverse is None or bounds is None:
        return None
    local_rect = inverse.map_rect(scene_rect).toAlignedRect()
    if local_rect.isEmpty():
        return None
    return bounds.intersection(RasterBounds.from_qrect(local_rect))


def _apply_layer_clip(
    painter: QPainter,
    scene: SceneDescriptor,
    clip: LayerClip | None,
    pixel_size: QSize,
    scene_to_pixels: QTransform,
) -> None:
    """Intersect the painter with one clip in its declared coordinate space."""
    if clip is None:
        return
    painter.setWorldTransform(QTransform())
    if clip.coordinate_space is ClipCoordinateSpace.SCENE:
        rectangle = scene_to_pixels.mapRect(
            QRectF(clip.x, clip.y, clip.width, clip.height)
        )
    elif clip.coordinate_space is ClipCoordinateSpace.NORMALIZED_SCENE:
        rectangle = scene_to_pixels.mapRect(
            QRectF(
                scene.bounds.x + clip.x * scene.bounds.width,
                scene.bounds.y + clip.y * scene.bounds.height,
                clip.width * scene.bounds.width,
                clip.height * scene.bounds.height,
            )
        )
    elif clip.coordinate_space is ClipCoordinateSpace.NORMALIZED_VIEWPORT:
        rectangle = QRectF(
            clip.x * pixel_size.width(),
            clip.y * pixel_size.height(),
            clip.width * pixel_size.width(),
            clip.height * pixel_size.height(),
        )
    else:
        rectangle = QRectF(clip.x, clip.y, clip.width, clip.height)
    painter.setClipRect(rectangle, Qt.ClipOperation.IntersectClip)


def _draw_exact_region(
    painter: QPainter,
    bounds: RasterBounds,
    image: QImage,
) -> None:
    """Draw an override only when it exactly satisfies the requested bounds."""
    if image.isNull() or image.size() != QSize(bounds.width, bounds.height):
        raise ValueError("raster override must match requested local bounds")
    painter.drawImage(_rectf(bounds), image, QRectF(image.rect()))


def _rectf(bounds: RasterBounds) -> QRectF:
    """Return continuous geometry for one integer raster bound."""
    return QRectF(bounds.x, bounds.y, bounds.width, bounds.height)
