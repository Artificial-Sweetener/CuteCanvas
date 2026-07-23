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
"""Compile source-neutral immutable scenes into stable render metadata."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize

from ..scene.affine import LayerTransform
from ..scene.identity import (
    SceneLayerAssetKey,
    SourceRenderAssetKey,
    scene_image_asset_key,
    source_render_asset_key,
)
from ..scene.model import LayerDescriptor, SceneDescriptor
from ..scene.render_plan import SceneContentSnapshot
from ..scene.source_capabilities import (
    HybridPresentationRegistry,
    RasterPresentation,
    RasterPresentationRegistry,
    SourceMetadataRegistry,
    VectorPresentationRegistry,
)
from .compiled_scene import (
    CompiledPresentationLayer,
    CompiledRenderLayer,
    CompiledRenderScene,
    hit_test_items_for_scene,
)


class SceneRenderCompiler:
    """Compile one externally selected scene without owning viewer policy."""

    def __init__(
        self,
        *,
        scene_provider: Callable[[], SceneDescriptor | None],
        revision_provider: Callable[[], object],
        source_metadata: SourceMetadataRegistry,
        raster_sources: RasterPresentationRegistry,
        vector_sources: VectorPresentationRegistry,
        hybrid_sources: HybridPresentationRegistry,
    ) -> None:
        """Capture the scene snapshot and focused source capabilities."""
        self._scene_provider = scene_provider
        self._revision_provider = revision_provider
        self._source_metadata = source_metadata
        self._raster_sources = raster_sources
        self._vector_sources = vector_sources
        self._hybrid_sources = hybrid_sources
        self._cached_key: object | None = None
        self._cached_scene: CompiledRenderScene | None = None
        self._has_cached_result = False

    def compiled_scene(self) -> CompiledRenderScene | None:
        """Return renderer-facing metadata for the current scene revision."""
        cache_key = self._revision_provider()
        if self._has_cached_result and cache_key == self._cached_key:
            return self._cached_scene
        scene = self._scene_provider()
        compiled = None if scene is None else self._compile(scene)
        self._cached_key = cache_key
        self._cached_scene = compiled
        self._has_cached_result = True
        return compiled

    def cached_scene(self) -> CompiledRenderScene | None:
        """Return already compiled metadata without resolving scene state."""
        return self._cached_scene

    def invalidate(self) -> None:
        """Drop cached scene metadata."""
        self._cached_key = None
        self._cached_scene = None
        self._has_cached_result = False

    def _compile(self, scene: SceneDescriptor) -> CompiledRenderScene:
        """Compile stable source and instance metadata for one scene."""
        base_layer = self._first_image_layer(scene)
        raster_layers: list[CompiledRenderLayer] = []
        vector_layers: list[CompiledPresentationLayer] = []
        hybrid_layers: list[CompiledPresentationLayer] = []
        for layer in scene.layers:
            if not layer.visible:
                continue
            vector_snapshot = self._vector_sources.vector_document(layer.source)
            if vector_snapshot is not None:
                vector_layers.append(CompiledPresentationLayer(layer, vector_snapshot))
                continue
            hybrid_snapshot = self._hybrid_sources.hybrid_document(layer.source)
            if hybrid_snapshot is not None:
                hybrid_layers.append(CompiledPresentationLayer(layer, hybrid_snapshot))
                continue
            presentation = self._raster_sources.presentation_for(layer.source)
            if presentation not in (
                RasterPresentation.IMAGE,
                RasterPresentation.OVERLAY,
            ):
                continue
            compiled_layer = self._compile_raster_layer(
                scene=scene,
                base_layer=base_layer,
                layer=layer,
            )
            if compiled_layer is not None:
                raster_layers.append(compiled_layer)
        return CompiledRenderScene(
            scene=scene,
            content_snapshot=self._content_snapshot(scene, base_layer),
            layers=tuple(raster_layers),
            vector_layers=tuple(vector_layers),
            hybrid_layers=tuple(hybrid_layers),
            hit_test_items=hit_test_items_for_scene(scene),
        )

    def _compile_raster_layer(
        self,
        *,
        scene: SceneDescriptor,
        base_layer: LayerDescriptor | None,
        layer: LayerDescriptor,
    ) -> CompiledRenderLayer | None:
        """Compile one raster source into stable render metadata."""
        source_size = self._source_metadata.source_size(layer.source)
        if source_size is None or source_size.isEmpty():
            return None
        source_path = self._source_metadata.source_path(layer.source)
        is_base_raster = (
            base_layer is not None and layer.layer_id == base_layer.layer_id
        )
        return CompiledRenderLayer(
            descriptor=layer,
            asset_key=self._render_asset_key(scene, layer, source_path),
            pyramid_asset_key=self._pyramid_asset_key(layer, source_path),
            source_size=source_size,
            presentation=self._raster_sources.presentation_for(layer.source),
            source_path=source_path,
            source_revision=layer.source_revision,
            is_base_raster=is_base_raster,
            uses_default_base_tile_math=(
                is_base_raster
                and self._uses_default_base_tile_math(
                    scene=scene,
                    layer=layer,
                    source_size=source_size,
                )
            ),
        )

    @staticmethod
    def _render_asset_key(
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        source_path: Path | None,
    ) -> SceneLayerAssetKey:
        """Return instance render identity independently of source products."""
        return scene_image_asset_key(
            scene_id=scene.scene_id,
            layer_id=layer.layer_id,
            source_id=layer.source.resource_id,
            source_kind=layer.source.kind,
            revision=layer.source_revision,
            source_path=source_path,
        )

    @staticmethod
    def _pyramid_asset_key(
        layer: LayerDescriptor,
        source_path: Path | None,
    ) -> SourceRenderAssetKey:
        """Return source-product identity independently of layer geometry."""
        return source_render_asset_key(
            source_id=layer.source.resource_id,
            source_kind=layer.source.kind,
            revision=layer.source_revision,
            source_path=source_path,
        )

    def _content_snapshot(
        self,
        scene: SceneDescriptor,
        base_layer: LayerDescriptor | None,
    ) -> SceneContentSnapshot:
        """Project scene geometry into viewport content metadata."""
        scene_size = QSize(
            max(1, round(scene.bounds.width)),
            max(1, round(scene.bounds.height)),
        )
        if base_layer is None:
            base_key = SceneLayerAssetKey(
                scene_id=scene.scene_id,
                layer_id=scene.scene_id,
                source_id=scene.scene_id,
                source_kind="scene-canvas",
                source_revision=0,
            )
            source_path = None
        else:
            source_path = self._source_metadata.source_path(base_layer.source)
            base_key = self._render_asset_key(scene, base_layer, source_path)
        return SceneContentSnapshot(
            scene_id=scene.scene_id,
            base_asset_key=base_key,
            base_image_size=scene_size,
            scene_bounds=scene.bounds,
            active_content_bounds=scene.bounds,
            current_path=source_path,
        )

    def _first_image_layer(self, scene: SceneDescriptor) -> LayerDescriptor | None:
        """Return the first visible dense raster presentation in scene order."""
        return next(
            (
                layer
                for layer in scene.layers
                if layer.visible
                and self._raster_sources.presentation_for(layer.source)
                is RasterPresentation.IMAGE
            ),
            None,
        )

    @staticmethod
    def _uses_default_base_tile_math(
        *,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        source_size: QSize,
    ) -> bool:
        """Return whether the direct full-canvas raster fast path applies."""
        scene_width = max(1, round(scene.bounds.width))
        scene_height = max(1, round(scene.bounds.height))
        raster_bounds = layer.raster_bounds
        return (
            layer.visible
            and layer.clip is None
            and raster_bounds is not None
            and layer.transform
            == LayerTransform.from_placement(raster_bounds, scene.bounds)
            and layer.placement == scene.bounds
            and source_size.width() == scene_width
            and source_size.height() == scene_height
        )
