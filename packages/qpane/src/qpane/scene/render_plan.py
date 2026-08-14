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

"""Immutable render-plan snapshots resolved from internal scene descriptors."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

from PySide6.QtCore import QPointF, QRect, QRectF, QSize
from PySide6.QtGui import QImage, QPainterPath, QPicture, QTransform

from .affine import LayerTransform
from .identity import SceneLayerAssetKey, SourceRenderAssetKey
from .model import LayerClip, LayerDescriptor, LayerPlacement
from .presentation_effects import LayerPresentationEffect
from .raster import RasterBounds
from .raster_sampling import RasterExactSampling, RasterPresentationSampling
from .source_references import LayerSourceReference

if TYPE_CHECKING:
    from ..rendering.panel_mapping import PanelLayerMapping


class RenderStrategy(str, Enum):
    """Supported raster rendering strategies."""

    DIRECT = "direct"
    TILE = "tile"


@dataclass(frozen=True, slots=True)
class TileRenderData:
    """Rendered tile payload and source-space draw position."""

    image: QImage
    draw_pos: QPointF

    def __post_init__(self) -> None:
        """Detach mutable Qt values from the caller-owned render inputs."""
        object.__setattr__(self, "draw_pos", QPointF(self.draw_pos))


@dataclass(frozen=True, slots=True)
class SceneContentSnapshot:
    """Content geometry and identity for the active rendered scene."""

    scene_id: uuid.UUID
    base_asset_key: SceneLayerAssetKey
    base_image_size: QSize
    scene_bounds: LayerPlacement
    active_content_bounds: LayerPlacement
    current_path: Path | None

    def __post_init__(self) -> None:
        """Detach mutable Qt geometry values from caller-owned content state."""
        object.__setattr__(self, "base_image_size", QSize(self.base_image_size))


@dataclass(frozen=True, slots=True)
class RasterLayerRenderItem:
    """Render-ready raster layer snapshot consumed by the painting pipeline."""

    descriptor: LayerDescriptor
    source_image: QImage
    asset_key: SceneLayerAssetKey
    pyramid_asset_key: SourceRenderAssetKey
    pyramid_scale: float
    transform: PanelLayerMapping
    placement: LayerPlacement
    clip: LayerClip | None
    strategy: RenderStrategy
    presentation_sampling: RasterPresentationSampling
    debug_draw_tile_grid: bool
    tiles_to_draw: tuple[TileRenderData, ...]
    tile_size: int
    tile_overlap: int
    max_tile_cols: int
    max_tile_rows: int
    visible_tile_range: tuple[int, int, int, int] | None
    is_base_raster: bool = False
    effect_clip_path: QPainterPath | None = None
    mapping_clip_path: QPainterPath | None = None

    def __post_init__(self) -> None:
        """Validate stable raster planning values."""
        object.__setattr__(self, "transform", _detach_panel_mapping(self.transform))
        object.__setattr__(self, "tiles_to_draw", tuple(self.tiles_to_draw))
        if self.effect_clip_path is not None:
            object.__setattr__(
                self,
                "effect_clip_path",
                QPainterPath(self.effect_clip_path),
            )
        if self.mapping_clip_path is not None:
            object.__setattr__(
                self,
                "mapping_clip_path",
                QPainterPath(self.mapping_clip_path),
            )
        if self.pyramid_scale <= 0.0:
            raise ValueError("pyramid scale must be positive")
        if self.tile_size < 0 or self.tile_overlap < 0:
            raise ValueError("tile metadata must be non-negative")
        if self.max_tile_cols < 0 or self.max_tile_rows < 0:
            raise ValueError("tile grid dimensions must be non-negative")

    @property
    def source_size(self) -> QSize:
        """Return the raster source dimensions shared by render-item geometry."""
        return self.source_image.size()


@dataclass(frozen=True, slots=True)
class SampledTileRenderData:
    """Carry one sampled tile and its source-local draw rectangles."""

    image: QImage
    source_rect: QRectF
    image_source_rect: QRectF
    source_clip_rect: QRectF | None = None
    integer_origin_sampling: bool = False
    exact_sampling: RasterExactSampling | None = None

    def __post_init__(self) -> None:
        """Detach mutable Qt values from the cache-owned product."""
        object.__setattr__(self, "image", QImage(self.image))
        object.__setattr__(self, "source_rect", QRectF(self.source_rect))
        object.__setattr__(
            self,
            "image_source_rect",
            QRectF(self.image_source_rect),
        )
        if self.source_clip_rect is not None:
            object.__setattr__(
                self,
                "source_clip_rect",
                QRectF(self.source_clip_rect),
            )

    @property
    def product_key(self) -> SampledTileProductKey:
        """Return cheap immutable identity for this exact sampled product."""
        return SampledTileProductKey(
            image_cache_key=self.image.cacheKey(),
            geometry=self.geometry_key,
        )

    @property
    def geometry_key(self) -> SampledTileGeometryKey:
        """Return the source-local sampling geometry without reading pixels."""
        return SampledTileGeometryKey(
            image_size=(self.image.width(), self.image.height()),
            source_rect=_rect_key(self.source_rect),
            image_source_rect=_rect_key(self.image_source_rect),
            source_clip_rect=(
                None
                if self.source_clip_rect is None
                else _rect_key(self.source_clip_rect)
            ),
            integer_origin_sampling=self.integer_origin_sampling,
            exact_sampling=self.exact_sampling,
        )


@dataclass(frozen=True, slots=True)
class SampledTileGeometryKey:
    """Identify one sampled tile's complete draw and clipping geometry."""

    image_size: tuple[int, int]
    source_rect: tuple[float, float, float, float]
    image_source_rect: tuple[float, float, float, float]
    source_clip_rect: tuple[float, float, float, float] | None
    integer_origin_sampling: bool
    exact_sampling: RasterExactSampling | None


@dataclass(frozen=True, slots=True)
class SampledTileProductKey:
    """Identify one immutable sampled image and the geometry interpreting it."""

    image_cache_key: int
    geometry: SampledTileGeometryKey


SampledTileBatchKey: TypeAlias = tuple[SampledTileProductKey, ...]
SampledTileGeometryBatchKey: TypeAlias = tuple[SampledTileGeometryKey, ...]


@dataclass(frozen=True, slots=True)
class VectorLayerRenderItem:
    """Render-ready resolution-independent vector layer snapshot."""

    descriptor: LayerDescriptor
    picture: QPicture
    transform: PanelLayerMapping
    placement: LayerPlacement
    clip: LayerClip | None
    source_size: QSize
    presentation_sampling: RasterPresentationSampling
    effect_clip_path: QPainterPath | None = None
    preview_picture: QPicture | None = None
    trailing_picture: QPicture | None = None
    refined_tiles: tuple[SampledTileRenderData, ...] = ()
    mapping_clip_path: QPainterPath | None = None

    def __post_init__(self) -> None:
        """Detach mutable Qt drawing and geometry values."""
        object.__setattr__(self, "picture", QPicture(self.picture))
        object.__setattr__(self, "transform", _detach_panel_mapping(self.transform))
        object.__setattr__(self, "source_size", QSize(self.source_size))
        object.__setattr__(self, "refined_tiles", tuple(self.refined_tiles))
        if self.preview_picture is not None:
            object.__setattr__(self, "preview_picture", QPicture(self.preview_picture))
        if self.trailing_picture is not None:
            object.__setattr__(
                self,
                "trailing_picture",
                QPicture(self.trailing_picture),
            )
        if self.effect_clip_path is not None:
            object.__setattr__(
                self,
                "effect_clip_path",
                QPainterPath(self.effect_clip_path),
            )
        if self.mapping_clip_path is not None:
            object.__setattr__(
                self,
                "mapping_clip_path",
                QPainterPath(self.mapping_clip_path),
            )


@dataclass(frozen=True, slots=True)
class SampledLayerRenderItem:
    """Render one asynchronously sampled source from an atomic tile batch."""

    descriptor: LayerDescriptor
    transform: PanelLayerMapping
    placement: LayerPlacement
    clip: LayerClip | None
    source_size: QSize
    presentation_sampling: RasterPresentationSampling
    tiles: tuple[SampledTileRenderData, ...]
    effect_clip_path: QPainterPath | None = None
    source_bounds: QRectF | None = None
    mapping_clip_path: QPainterPath | None = None
    panel_space_products: bool = False

    def __post_init__(self) -> None:
        """Detach mutable Qt drawing and geometry values."""
        object.__setattr__(self, "transform", _detach_panel_mapping(self.transform))
        object.__setattr__(self, "source_size", QSize(self.source_size))
        object.__setattr__(self, "tiles", tuple(self.tiles))
        if self.source_bounds is not None:
            object.__setattr__(self, "source_bounds", QRectF(self.source_bounds))
        if self.effect_clip_path is not None:
            object.__setattr__(
                self,
                "effect_clip_path",
                QPainterPath(self.effect_clip_path),
            )
        if self.mapping_clip_path is not None:
            object.__setattr__(
                self,
                "mapping_clip_path",
                QPainterPath(self.mapping_clip_path),
            )

    @property
    def sample_batch_key(self) -> SampledTileBatchKey:
        """Return identity for the exact immutable sampled product batch."""
        return tuple(tile.product_key for tile in self.tiles)

    @property
    def sample_geometry_key(self) -> SampledTileGeometryBatchKey:
        """Return current sampled demand geometry independently of tile pixels."""
        return tuple(tile.geometry_key for tile in self.tiles)


SceneRenderItem: TypeAlias = (
    RasterLayerRenderItem | VectorLayerRenderItem | SampledLayerRenderItem
)


@dataclass(frozen=True, slots=True)
class TransientRasterTransformContribution:
    """Carry stable contribution products plus transient source-local geometry."""

    session_id: uuid.UUID
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    source_asset_key: SceneLayerAssetKey
    source_patch: QImage | None
    source_bounds: RasterBounds
    fragment_image: QImage
    fragment_bounds: RasterBounds
    destination_attenuation_mask: QImage | None
    fragment_transform: LayerTransform
    extent_clip_bounds: RasterBounds | None

    def __post_init__(self) -> None:
        """Detach mutable Qt resources from the compiling presenter."""
        if self.source_patch is not None:
            object.__setattr__(self, "source_patch", QImage(self.source_patch))
        object.__setattr__(self, "fragment_image", QImage(self.fragment_image))
        if self.destination_attenuation_mask is not None:
            object.__setattr__(
                self,
                "destination_attenuation_mask",
                QImage(self.destination_attenuation_mask),
            )


@dataclass(frozen=True, slots=True)
class TransientRasterResolvedContribution:
    """Carry one exact settled raster until durable presentation catches up."""

    session_id: uuid.UUID
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    source_asset_key: SceneLayerAssetKey
    source_image: QImage
    source_bounds: RasterBounds
    retain_until_durable: bool = True

    def __post_init__(self) -> None:
        """Detach mutable Qt resources from the compiling presenter."""
        object.__setattr__(self, "source_image", QImage(self.source_image))


@dataclass(frozen=True, slots=True)
class TransientSampledResolvedContribution:
    """Carry one settled edit through the sampled source's exact tile geometry."""

    session_id: uuid.UUID
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    source_asset_key: SceneLayerAssetKey
    source_bounds: RasterBounds
    tiles: tuple[SampledTileRenderData, ...]
    retain_until_durable: bool = True
    sampled_raster_bounds: RasterBounds | None = None
    sampled_source_size: QSize | None = None

    def __post_init__(self) -> None:
        """Detach the immutable sampled tile batch."""
        object.__setattr__(self, "tiles", tuple(self.tiles))
        if self.sampled_source_size is not None:
            object.__setattr__(
                self,
                "sampled_source_size",
                QSize(self.sampled_source_size),
            )

    @property
    def sample_geometry_key(self) -> SampledTileGeometryBatchKey:
        """Return the sampled demand geometry this replacement can cover."""
        return tuple(tile.geometry_key for tile in self.tiles)


TransientRasterContribution: TypeAlias = (
    TransientRasterTransformContribution
    | TransientRasterResolvedContribution
    | TransientSampledResolvedContribution
)


@dataclass(frozen=True, slots=True)
class SceneHitTestItem:
    """Render-plan hit-test metadata for a resolved scene layer."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    bounds: LayerPlacement
    enabled: bool
    selectable: bool
    role: str
    source: LayerSourceReference | None = None


@dataclass(frozen=True, slots=True)
class SceneLayerHitTestResult:
    """Internal hit-test result for a scene layer under a panel coordinate."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    role: str
    source: LayerSourceReference
    panel_point: QPointF
    scene_point: QPointF
    source_point: QPointF
    selectable: bool


@dataclass(frozen=True, slots=True)
class SceneRenderPlan:
    """Render-ready snapshot for one resolved scene frame."""

    scene_id: uuid.UUID
    scene_bounds: LayerPlacement
    content_bounds: LayerPlacement
    content_snapshot: SceneContentSnapshot
    zoom: float
    current_pan: QPointF
    qpane_rect: QRect
    physical_viewport_rect: QRectF
    render_items: tuple[SceneRenderItem, ...]
    hit_test_items: tuple[SceneHitTestItem, ...]
    transient_raster: TransientRasterContribution | None = None
    presentation_effects: tuple[LayerPresentationEffect, ...] = ()

    def __post_init__(self) -> None:
        """Detach mutable Qt geometry values from caller-owned frame state."""
        object.__setattr__(self, "current_pan", QPointF(self.current_pan))
        object.__setattr__(self, "qpane_rect", QRect(self.qpane_rect))
        object.__setattr__(
            self,
            "physical_viewport_rect",
            QRectF(self.physical_viewport_rect),
        )
        object.__setattr__(
            self,
            "presentation_effects",
            tuple(self.presentation_effects),
        )
        object.__setattr__(self, "render_items", tuple(self.render_items))
        object.__setattr__(self, "hit_test_items", tuple(self.hit_test_items))

    @property
    def base_raster_item(self) -> RasterLayerRenderItem | None:
        """Return the renderer-selected base raster item when one exists."""
        for item in self.render_items:
            if isinstance(item, RasterLayerRenderItem) and item.is_base_raster:
                return item
        return None


def _detach_panel_mapping(mapping: PanelLayerMapping) -> PanelLayerMapping:
    """Detach mutable Qt transforms while retaining immutable patch mappings."""
    return QTransform(mapping) if isinstance(mapping, QTransform) else mapping


def _rect_key(rect: QRectF) -> tuple[float, float, float, float]:
    """Return an immutable exact key for detached Qt rectangle geometry."""
    return rect.x(), rect.y(), rect.width(), rect.height()
