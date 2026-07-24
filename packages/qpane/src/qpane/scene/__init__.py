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
"""Source-neutral scene values and rendering capability boundaries."""

from __future__ import annotations

from .affine import LayerTransform
from .identity import (
    SceneLayerAssetKey,
    SceneLayerTileKey,
    SourceRenderAssetKey,
    placeholder_layer_id,
    placeholder_scene_id,
    placeholder_source_id,
    scene_image_asset_key,
    source_render_asset_key,
)
from .model import (
    BlendMode,
    ClipCoordinateSpace,
    LayerClip,
    LayerContentCapabilities,
    LayerDescriptor,
    LayerHitTest,
    LayerInteractionPolicy,
    LayerKind,
    LayerPlacement,
    SceneDescriptor,
    SceneKind,
)
from .providers import SceneContribution, SceneProvider, SceneResolver
from .raster import RasterBounds
from .registry import (
    SceneContributionProvider,
    ScenePostProcessor,
    SceneProviderRegistry,
    SceneReplacementProvider,
)
from .render_plan import (
    RasterLayerRenderItem,
    RenderStrategy,
    SceneHitTestItem,
    SceneLayerHitTestResult,
    SceneRenderItem,
    SceneRenderPlan,
    TileRenderData,
)
from .source_capabilities import (
    LayerSourceCapabilities,
    RasterPresentation,
    RasterPresentationRegistry,
    SourceHitTestRegistry,
    SourceMetadataRegistry,
)
from .source_references import LayerSourceReference

__all__ = [
    "BlendMode",
    "ClipCoordinateSpace",
    "LayerClip",
    "LayerContentCapabilities",
    "LayerDescriptor",
    "LayerHitTest",
    "LayerInteractionPolicy",
    "LayerKind",
    "LayerPlacement",
    "LayerSourceCapabilities",
    "LayerSourceReference",
    "LayerTransform",
    "RasterBounds",
    "RasterLayerRenderItem",
    "RasterPresentation",
    "RasterPresentationRegistry",
    "RenderStrategy",
    "SceneContribution",
    "SceneContributionProvider",
    "SceneDescriptor",
    "SceneHitTestItem",
    "SceneKind",
    "SceneLayerAssetKey",
    "SceneLayerHitTestResult",
    "SceneLayerTileKey",
    "ScenePostProcessor",
    "SceneProvider",
    "SceneProviderRegistry",
    "SceneRenderItem",
    "SceneRenderPlan",
    "SceneReplacementProvider",
    "SceneResolver",
    "SourceHitTestRegistry",
    "SourceMetadataRegistry",
    "SourceRenderAssetKey",
    "TileRenderData",
    "placeholder_layer_id",
    "placeholder_scene_id",
    "placeholder_source_id",
    "scene_image_asset_key",
    "source_render_asset_key",
]
