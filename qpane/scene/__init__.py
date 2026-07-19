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

"""Internal scene and layer descriptors used to plan future composition."""

from __future__ import annotations

from .default_scene import DefaultCatalogSceneProvider, build_default_catalog_scene
from .identity import (
    SceneLayerAssetKey,
    SceneLayerTileKey,
    base_image_layer_id,
    compare_layer_id,
    default_scene_id,
    mask_layer_asset_key,
    mask_layer_id,
    placeholder_layer_id,
    placeholder_scene_id,
    placeholder_source_id,
    scene_image_asset_key,
)
from .layer_assembly import CompositionLayerSceneAssembler
from .layer_selection import SceneLayerSelection, SceneLayerSelectionController
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
from .movement import LayerMoveSession, SceneLayerMovementController
from .mutations import (
    BaseSceneMutationOwner,
    SceneMutationCoordinator,
    SceneMutationOwner,
    SceneMutationResult,
    SceneMutationStatus,
)
from .placeholder_scene import build_placeholder_scene
from .placement_edit import LayerPlacementEdit
from .placement_preview import LayerPlacementPreview, SceneLayerPlacementPreview
from .providers import SceneContribution, SceneProvider, SceneResolver
from .registry import (
    CatalogLayerSourceResolver,
    LayerSourceResolver,
    LayerSourceResolverRegistry,
    SceneContributionProvider,
    ScenePostProcessor,
    SceneProviderRegistry,
    SceneReplacementProvider,
)
from .render_plan import (
    MaskLayerRenderItem,
    RasterLayerRenderItem,
    RenderStrategy,
    SceneHitTestItem,
    SceneLayerHitTestResult,
    SceneRenderItem,
    SceneRenderPlan,
    TileRenderData,
)
from .sources import (
    CatalogImageSource,
    LayerSource,
    MaskLayerSource,
    PlaceholderImageSource,
)

__all__ = [
    "BaseSceneMutationOwner",
    "BlendMode",
    "CatalogImageSource",
    "CatalogLayerSourceResolver",
    "ClipCoordinateSpace",
    "CompositionLayerSceneAssembler",
    "DefaultCatalogSceneProvider",
    "LayerClip",
    "LayerContentCapabilities",
    "LayerDescriptor",
    "LayerHitTest",
    "LayerInteractionPolicy",
    "LayerKind",
    "LayerMoveSession",
    "LayerPlacement",
    "LayerPlacementEdit",
    "LayerPlacementPreview",
    "LayerSource",
    "LayerSourceResolver",
    "LayerSourceResolverRegistry",
    "MaskLayerRenderItem",
    "MaskLayerSource",
    "PlaceholderImageSource",
    "RasterLayerRenderItem",
    "RenderStrategy",
    "SceneContribution",
    "SceneContributionProvider",
    "SceneDescriptor",
    "SceneHitTestItem",
    "SceneKind",
    "SceneLayerAssetKey",
    "SceneLayerHitTestResult",
    "SceneLayerMovementController",
    "SceneLayerPlacementPreview",
    "SceneLayerSelection",
    "SceneLayerSelectionController",
    "SceneLayerTileKey",
    "SceneMutationCoordinator",
    "SceneMutationOwner",
    "SceneMutationResult",
    "SceneMutationStatus",
    "ScenePostProcessor",
    "SceneProvider",
    "SceneProviderRegistry",
    "SceneRenderItem",
    "SceneRenderPlan",
    "SceneReplacementProvider",
    "SceneResolver",
    "TileRenderData",
    "base_image_layer_id",
    "build_default_catalog_scene",
    "build_placeholder_scene",
    "compare_layer_id",
    "default_scene_id",
    "mask_layer_asset_key",
    "mask_layer_id",
    "placeholder_layer_id",
    "placeholder_scene_id",
    "placeholder_source_id",
    "scene_image_asset_key",
]
