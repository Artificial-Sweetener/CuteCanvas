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

"""Resolve source-backed scenes into stable renderer-facing metadata."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage

from ..catalog.source_reference import CatalogImageReference
from ..scene.affine import LayerTransform
from ..scene.assembly import SceneAssembly
from ..scene.identity import (
    SceneLayerAssetKey,
    SourceRenderAssetKey,
    default_catalog_asset_key,
    scene_image_asset_key,
    source_render_asset_key,
)
from ..scene.model import LayerDescriptor, SceneDescriptor, SceneKind
from ..scene.placeholder_scene import build_placeholder_scene
from ..scene.registry import SceneProviderRegistry
from ..scene.render_plan import SceneContentSnapshot
from ..scene.source_capabilities import (
    RasterPresentation,
    RasterPresentationRegistry,
    SourceMetadataRegistry,
    VectorPresentationRegistry,
)
from .compiled_scene import (
    CompiledRenderLayer,
    CompiledRenderScene,
    hit_test_items_for_scene,
)


class SceneCompilerCatalog(Protocol):
    """Catalog operations required while resolving render content."""

    def getCurrentId(self) -> uuid.UUID | None:
        """Return the selected catalog image ID."""

    def getCurrentImage(self) -> QImage | None:
        """Return the selected catalog image."""

    def getCurrentPath(self) -> Path | None:
        """Return the selected catalog source path."""

    def getRevision(self, image_id: uuid.UUID) -> int | None:
        """Return the content revision for an image."""

    def defaultAssetKeyForImage(
        self, image_id: uuid.UUID
    ) -> SourceRenderAssetKey | None:
        """Return the catalog pyramid identity for an image."""


@dataclass(frozen=True, slots=True)
class _ActiveSceneContent:
    """Resolved scene content used as the authoritative compile source."""

    scene: SceneDescriptor
    base_size: QSize
    image_id: uuid.UUID | None
    source_path: Path | None
    source_revision: int
    asset_key: SceneLayerAssetKey
    pyramid_asset_key: SourceRenderAssetKey


class SceneRenderCompiler:
    """Own active-scene resolution, source adaptation, and compile caching."""

    def __init__(
        self,
        *,
        catalog: SceneCompilerCatalog,
        scene_providers: SceneProviderRegistry,
        source_metadata: SourceMetadataRegistry,
        raster_sources: RasterPresentationRegistry,
        vector_sources: VectorPresentationRegistry,
    ) -> None:
        """Capture authoritative scene and source-resolution collaborators."""
        self._catalog = catalog
        self._scene_providers = scene_providers
        self._scene_assembly = SceneAssembly(scene_providers)
        self._source_metadata = source_metadata
        self._raster_sources = raster_sources
        self._vector_sources = vector_sources
        self._placeholder_content_provider: Callable[[], object | None] | None = None
        self._cached_key: tuple[object, ...] | None = None
        self._cached_scene: CompiledRenderScene | None = None

    def set_placeholder_content_provider(
        self, provider: Callable[[], object | None]
    ) -> None:
        """Install the catalog-owned placeholder content provider."""
        self._placeholder_content_provider = provider
        self.invalidate()

    def compiled_scene(self) -> CompiledRenderScene | None:
        """Return cached renderer-facing metadata for the active scene."""
        cache_key = self._cache_key()
        if cache_key == self._cached_key and self._cached_scene is not None:
            return self._cached_scene
        active_content = self._resolve_active_content()
        compiled = self._compile(active_content) if active_content is not None else None
        self._cached_key = cache_key
        self._cached_scene = compiled
        return compiled

    def cached_scene(self) -> CompiledRenderScene | None:
        """Return already compiled metadata without resolving new inputs."""
        return self._cached_scene

    def invalidate(self) -> None:
        """Drop cached active-scene and source metadata."""
        self._cached_key = None
        self._cached_scene = None

    def _resolve_active_content(self) -> _ActiveSceneContent | None:
        """Resolve replacement, catalog, or placeholder content in priority order."""
        replacement_content = self._resolve_replacement_content()
        if replacement_content is not None:
            return replacement_content
        current_id = self._catalog.getCurrentId()
        current_image = self._catalog.getCurrentImage()
        if (
            current_id is not None
            and current_image is not None
            and not current_image.isNull()
        ):
            return self._resolve_catalog_content(current_id, current_image)
        return self._resolve_placeholder_content()

    def _resolve_catalog_content(
        self, image_id: uuid.UUID, image: QImage
    ) -> _ActiveSceneContent | None:
        """Resolve the selected catalog image through the default scene assembly."""
        source_path = self._catalog.getCurrentPath()
        source_revision = self._catalog_revision(image_id)
        scene = self._scene_assembly.resolve_catalog_image(
            image_id=image_id,
            image_size=image.size(),
            source_path=source_path,
            source_revision=source_revision,
        )
        if scene is None:
            return None
        layer = self._first_image_layer(scene)
        if layer is None:
            return None
        asset_key = self._render_asset_key(scene, layer, source_path=source_path)
        pyramid_asset_key = self._pyramid_asset_key(scene, layer)
        if pyramid_asset_key is None:
            return None
        return _ActiveSceneContent(
            scene=scene,
            base_size=image.size(),
            image_id=image_id,
            source_path=source_path,
            source_revision=source_revision,
            asset_key=asset_key,
            pyramid_asset_key=pyramid_asset_key,
        )

    def _resolve_placeholder_content(self) -> _ActiveSceneContent | None:
        """Resolve catalog-owned placeholder pixels into an internal scene."""
        placeholder = self._placeholder_content()
        if placeholder is None:
            return None
        image = getattr(placeholder, "image", None)
        if image is None or image.isNull():
            return None
        source_path = getattr(placeholder, "source_path", None)
        source_revision = max(0, int(getattr(placeholder, "revision", 0) or 0))
        scene = build_placeholder_scene(
            image_size=image.size(),
            source_path=source_path,
            revision=source_revision,
        )
        layer = self._first_image_layer(scene)
        if layer is None:
            return None
        asset_key = self._render_asset_key(scene, layer, source_path=source_path)
        pyramid_asset_key = self._pyramid_asset_key(scene, layer)
        if pyramid_asset_key is None:
            return None
        return _ActiveSceneContent(
            scene=scene,
            base_size=image.size(),
            image_id=None,
            source_path=source_path,
            source_revision=source_revision,
            asset_key=asset_key,
            pyramid_asset_key=pyramid_asset_key,
        )

    def _resolve_replacement_content(self) -> _ActiveSceneContent | None:
        """Resolve an active replacement scene without catalog selection."""
        scene = self._scene_assembly.resolve_replacement()
        if scene is None:
            return None
        layer = self._first_image_layer(scene)
        if layer is None:
            layer = next(
                (
                    candidate
                    for candidate in scene.layers
                    if candidate.visible
                    and (
                        self._raster_sources.presentation_for(candidate.source)
                        is not None
                        or self._vector_sources.owner_for(candidate.source) is not None
                    )
                ),
                None,
            )
        source_size = (
            None if layer is None else self._source_metadata.source_size(layer.source)
        )
        if layer is None:
            canvas_size = QSize(
                max(1, round(scene.bounds.width)),
                max(1, round(scene.bounds.height)),
            )
            canvas_key = scene_image_asset_key(
                scene_id=scene.scene_id,
                layer_id=scene.scene_id,
                source_id=scene.scene_id,
                source_kind="composition-canvas",
                revision=0,
                source_path=None,
            )
            return _ActiveSceneContent(
                scene=scene,
                base_size=canvas_size,
                image_id=None,
                source_path=None,
                source_revision=0,
                asset_key=canvas_key,
                pyramid_asset_key=source_render_asset_key(
                    source_id=scene.scene_id,
                    source_kind="composition-canvas",
                    revision=0,
                    source_path=None,
                ),
            )
        if source_size is None or source_size.isEmpty():
            return None
        if self._raster_sources.presentation_for(layer.source) is not None:
            asset_key = self._render_asset_key(scene, layer)
            pyramid_asset_key = self._pyramid_asset_key(scene, layer)
        else:
            asset_key = scene_image_asset_key(
                scene_id=scene.scene_id,
                layer_id=layer.layer_id,
                source_id=layer.source.resource_id,
                source_kind=layer.source.kind,
                revision=layer.source_revision,
                source_path=self._source_metadata.source_path(layer.source),
            )
            pyramid_asset_key = source_render_asset_key(
                source_id=layer.source.resource_id,
                source_kind=layer.source.kind,
                revision=layer.source_revision,
                source_path=self._source_metadata.source_path(layer.source),
            )
        if pyramid_asset_key is None:
            return None
        image_id = (
            layer.source.image_id
            if isinstance(layer.source, CatalogImageReference)
            else None
        )
        return _ActiveSceneContent(
            scene=scene,
            base_size=source_size,
            image_id=image_id,
            source_path=self._source_metadata.source_path(layer.source),
            source_revision=layer.source_revision,
            asset_key=asset_key,
            pyramid_asset_key=pyramid_asset_key,
        )

    def _compile(
        self, active_content: _ActiveSceneContent
    ) -> CompiledRenderScene | None:
        """Compile stable scene graph metadata for viewport planning."""
        content_snapshot = self._content_snapshot(active_content)
        base_layer = self._first_image_layer(active_content.scene)
        raster_layers: list[CompiledRenderLayer] = []
        vector_layers: list[LayerDescriptor] = []
        for layer in active_content.scene.layers:
            if not layer.visible:
                continue
            presentation = self._raster_sources.presentation_for(layer.source)
            if self._vector_sources.owner_for(layer.source) is not None:
                vector_layers.append(layer)
                continue
            if presentation not in (
                RasterPresentation.IMAGE,
                RasterPresentation.OVERLAY,
            ):
                continue
            compiled_layer = self._compile_raster_layer(
                active_content=active_content,
                base_layer=base_layer,
                layer=layer,
            )
            if compiled_layer is not None:
                raster_layers.append(compiled_layer)
        return CompiledRenderScene(
            scene=active_content.scene,
            content_snapshot=content_snapshot,
            layers=tuple(raster_layers),
            vector_layers=tuple(vector_layers),
            hit_test_items=hit_test_items_for_scene(active_content.scene),
        )

    def _compile_raster_layer(
        self,
        *,
        active_content: _ActiveSceneContent,
        base_layer: LayerDescriptor | None,
        layer: LayerDescriptor,
    ) -> CompiledRenderLayer | None:
        """Compile one raster layer into stable render-facing metadata."""
        is_base_raster = (
            base_layer is not None and layer.layer_id == base_layer.layer_id
        )
        source_size = (
            active_content.base_size
            if is_base_raster
            else self._source_metadata.source_size(layer.source)
        )
        if source_size is None or source_size.isEmpty():
            return None
        asset_key = (
            active_content.asset_key
            if is_base_raster
            else self._render_asset_key(active_content.scene, layer)
        )
        pyramid_asset_key = (
            active_content.pyramid_asset_key
            if is_base_raster
            else self._pyramid_asset_key(active_content.scene, layer)
        )
        if pyramid_asset_key is None:
            return None
        source_path = (
            active_content.source_path
            if is_base_raster
            else self._source_metadata.source_path(layer.source)
        )
        return CompiledRenderLayer(
            descriptor=layer,
            asset_key=asset_key,
            pyramid_asset_key=pyramid_asset_key,
            source_size=source_size,
            presentation=self._raster_sources.presentation_for(layer.source),
            source_path=source_path,
            source_revision=layer.source_revision,
            is_base_raster=is_base_raster,
            uses_default_base_tile_math=(
                is_base_raster
                and self._uses_default_base_tile_math(
                    scene=active_content.scene,
                    layer=layer,
                    source_size=source_size,
                )
            ),
        )

    def _render_asset_key(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        *,
        source_path: Path | None = None,
    ) -> SceneLayerAssetKey:
        """Return the render-cache identity for a resolved image layer."""
        if isinstance(layer.source, CatalogImageReference):
            if scene.kind is SceneKind.DEFAULT_CATALOG_IMAGE:
                return default_catalog_asset_key(
                    layer.source.image_id,
                    revision=layer.source_revision,
                    source_path=source_path,
                )
            return scene_image_asset_key(
                scene_id=scene.scene_id,
                layer_id=layer.layer_id,
                source_id=layer.source.resource_id,
                source_kind=layer.source.kind,
                revision=layer.source_revision,
                source_path=source_path,
            )
        if self._raster_sources.presentation_for(layer.source) is not None:
            return scene_image_asset_key(
                scene_id=scene.scene_id,
                layer_id=layer.layer_id,
                source_id=layer.source.resource_id,
                source_kind=layer.source.kind,
                revision=layer.source_revision,
                source_path=source_path,
            )
        raise TypeError("raster image render items require an image source")

    def _pyramid_asset_key(
        self, scene: SceneDescriptor, layer: LayerDescriptor
    ) -> SourceRenderAssetKey | None:
        """Return the source/pyramid identity for a resolved image layer."""
        if isinstance(layer.source, CatalogImageReference):
            return self._catalog.defaultAssetKeyForImage(layer.source.image_id)
        if self._raster_sources.presentation_for(layer.source) is not None:
            return source_render_asset_key(
                source_id=layer.source.resource_id,
                source_kind=layer.source.kind,
                revision=layer.source_revision,
                source_path=self._source_metadata.source_path(layer.source),
            )
        raise TypeError("raster image render items require an image source")

    def _cache_key(self) -> tuple[object, ...]:
        """Return authoritative revision values affecting compiled metadata."""
        current_id = self._catalog.getCurrentId()
        source_path = self._catalog.getCurrentPath() if current_id is not None else None
        placeholder = self._placeholder_content()
        placeholder_revision = (
            0
            if placeholder is None
            else max(0, int(getattr(placeholder, "revision", 0) or 0))
        )
        return (
            current_id,
            source_path,
            self._catalog_revision(current_id),
            placeholder_revision,
            self._scene_providers.revision(),
        )

    @staticmethod
    def _content_snapshot(active_content: _ActiveSceneContent) -> SceneContentSnapshot:
        """Project resolved content into geometry consumed by view helpers."""
        base_image_size = QSize(active_content.base_size)
        scene_size = QSize(
            max(1, round(active_content.scene.bounds.width)),
            max(1, round(active_content.scene.bounds.height)),
        )
        if (
            active_content.scene.kind == SceneKind.EXPLICIT
            or base_image_size != scene_size
        ):
            base_image_size = QSize(scene_size)
        return SceneContentSnapshot(
            scene_id=active_content.scene.scene_id,
            base_asset_key=active_content.asset_key,
            base_image_size=base_image_size,
            scene_bounds=active_content.scene.bounds,
            active_content_bounds=active_content.scene.bounds,
            current_path=active_content.source_path,
        )

    def _placeholder_content(self) -> object | None:
        """Return placeholder content when a provider is installed."""
        provider = self._placeholder_content_provider
        return provider() if provider is not None else None

    def _first_image_layer(self, scene: SceneDescriptor) -> LayerDescriptor | None:
        """Return the first visible image layer in scene order."""
        return next(
            (
                candidate
                for candidate in scene.layers
                if candidate.visible
                and self._raster_sources.presentation_for(candidate.source)
                is RasterPresentation.IMAGE
            ),
            None,
        )

    def _catalog_revision(self, image_id: uuid.UUID | None) -> int:
        """Return the catalog revision for an image when available."""
        if image_id is None:
            return 0
        revision = self._catalog.getRevision(image_id)
        return max(0, int(revision or 0))

    @staticmethod
    def _uses_default_base_tile_math(
        *,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        source_size: QSize,
    ) -> bool:
        """Return whether direct legacy base-image viewport math applies."""
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
