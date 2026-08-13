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

"""Own immutable intermediate products emitted by raster frame planning."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QImage

from ..scene.identity import SceneLayerAssetKey, SceneLayerTileKey, SourceRenderAssetKey
from ..scene.model import LayerClip, LayerPlacement
from ..scene.render_plan import (
    RasterLayerRenderItem,
    SampledLayerRenderItem,
    TileRenderData,
)
from .panel_mapping import PanelLayerMapping, detached_panel_mapping


@dataclass(frozen=True, slots=True)
class RasterLayerGeometry:
    """Geometry mapping one layer's render-source pixels into the panel."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    asset_key: SceneLayerAssetKey
    pyramid_asset_key: SourceRenderAssetKey
    pyramid_scale: float
    transform: PanelLayerMapping
    placement: LayerPlacement
    clip: LayerClip | None
    source_size: QSize
    tile_size: int
    tile_overlap: int
    visible_source_rect: QRectF

    def __post_init__(self) -> None:
        """Detach mutable Qt geometry from planner-owned frame values."""
        object.__setattr__(self, "transform", detached_panel_mapping(self.transform))
        object.__setattr__(self, "source_size", QSize(self.source_size))
        object.__setattr__(
            self,
            "visible_source_rect",
            QRectF(self.visible_source_rect),
        )


@dataclass(frozen=True, slots=True)
class RasterPlanningResult:
    """Carry one raster primitive and tile requests through frame adoption."""

    item: RasterLayerRenderItem | SampledLayerRenderItem
    visible_tile_keys: frozenset[SceneLayerTileKey]
    exact_eligible: bool = False
    exact_ready: bool = False


@dataclass(frozen=True, slots=True)
class RasterSourceProduct:
    """Carry one resolved raster sample and its shared-product eligibility."""

    image: QImage
    scale: float
    cacheable: bool


@dataclass(frozen=True, slots=True)
class RasterTilePlan:
    """Carry tile payloads and worker-cancellation keys for one raster layer."""

    tiles_to_draw: tuple[TileRenderData, ...]
    visible_keys: frozenset[SceneLayerTileKey]
    max_tile_cols: int
    max_tile_rows: int
    visible_tile_range: tuple[int, int, int, int] | None


__all__ = [
    "RasterLayerGeometry",
    "RasterPlanningResult",
    "RasterSourceProduct",
    "RasterTilePlan",
]
