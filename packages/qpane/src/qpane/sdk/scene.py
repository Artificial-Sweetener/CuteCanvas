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
"""Supported immutable scene, source, transform, and render-plan contracts."""

from ..scene.affine import LayerTransform
from ..scene.effects import LayerEffectReference, LayerEffectRenderRegistry
from ..scene.identity import SceneLayerAssetKey
from ..scene.model import (
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
from ..scene.providers import SceneContribution
from ..scene.raster import RasterBounds
from ..scene.registry import SceneProviderRegistry
from ..scene.render_plan import (
    RasterLayerRenderItem,
    SampledLayerRenderItem,
    SampledTileRenderData,
    SceneLayerHitTestResult,
    SceneRenderItem,
    TransientRasterContribution,
    TransientRasterResolvedContribution,
    TransientRasterTransformContribution,
    TransientSampledResolvedContribution,
)
from ..scene.source_capabilities import (
    LayerSourceCapabilities,
    RasterPresentation,
    RasterProductPolicy,
    RasterSourcePatch,
    SourceCapabilityRegistry,
)
from ..scene.source_references import LayerSourceReference
from ..scene.transform_geometry import (
    AffineTransformGeometry,
    TransformHandle,
    TransformLocalBounds,
    TransformModifiers,
    TransformOperation,
    TransformOperationKind,
)

__all__ = (
    "AffineTransformGeometry",
    "BlendMode",
    "ClipCoordinateSpace",
    "LayerClip",
    "LayerContentCapabilities",
    "LayerDescriptor",
    "LayerEffectReference",
    "LayerEffectRenderRegistry",
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
    "RasterProductPolicy",
    "RasterSourcePatch",
    "SampledLayerRenderItem",
    "SampledTileRenderData",
    "SceneContribution",
    "SceneDescriptor",
    "SceneKind",
    "SceneLayerAssetKey",
    "SceneLayerHitTestResult",
    "SceneProviderRegistry",
    "SceneRenderItem",
    "SourceCapabilityRegistry",
    "TransformHandle",
    "TransformLocalBounds",
    "TransformModifiers",
    "TransformOperation",
    "TransformOperationKind",
    "TransientRasterContribution",
    "TransientRasterResolvedContribution",
    "TransientRasterTransformContribution",
    "TransientSampledResolvedContribution",
)
