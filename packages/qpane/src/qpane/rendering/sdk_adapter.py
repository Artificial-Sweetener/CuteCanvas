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
"""Adapt the public rendering SDK to QPane's sole internal render pipeline."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QImage

from ..scene.model import (
    LayerContentCapabilities,
    LayerDescriptor,
    LayerHitTest,
    LayerKind,
    LayerPlacement,
    SceneDescriptor,
    SceneKind,
)
from ..scene.providers import SceneContribution
from ..scene.raster import RasterBounds
from ..scene.source_capabilities import (
    LayerSourceCapabilities,
    RasterPresentation,
    RasterProductPolicy,
    RasterSourcePatch,
)
from ..scene.source_references import LayerSourceReference
from ..vector.snapshot import VectorPresentationSnapshot
from .sdk import (
    HybridSource,
    RasterHitTestProvider,
    RasterSource,
    RenderScene,
    SparseRasterSourceProvider,
    VectorSource,
)


class RenderSdkSourceCapabilities:
    """Present public SDK sources through focused internal capabilities."""

    @property
    def presentation(self) -> RasterPresentation:
        """Return the ordinary raster primitive used by SDK raster sources."""
        return RasterPresentation.IMAGE

    def source_size(self, source: LayerSourceReference) -> QSize | None:
        """Return intrinsic dimensions for a public render source."""
        return (
            source.size
            if isinstance(source, (RasterSource, VectorSource, HybridSource))
            else None
        )

    def source_path(self, source: LayerSourceReference) -> Path | None:
        """Return optional raster provenance metadata."""
        return source.path if isinstance(source, RasterSource) else None

    def product_policy(self, source: LayerSourceReference) -> RasterProductPolicy:
        """Return the raster source's derived-product policy."""
        return (
            source.product_policy
            if isinstance(source, RasterSource)
            else RasterProductPolicy.CACHEABLE
        )

    def source_image(
        self,
        source: LayerSourceReference,
        *,
        scale: float | None = None,
    ) -> QImage | None:
        """Return pixels through the source-carried provider."""
        if not isinstance(source, RasterSource):
            return None
        image = source.provider.image(scale)
        return None if image is None else QImage(image)

    def source_patches(
        self,
        source: LayerSourceReference,
        visible_bounds: RasterBounds,
    ) -> tuple[RasterSourcePatch, ...] | None:
        """Return sparse patches when the source provider supports them."""
        if not isinstance(source, RasterSource):
            return None
        provider = source.provider
        if not isinstance(provider, SparseRasterSourceProvider):
            return None
        return provider.patches(visible_bounds)

    def contains(self, source: LayerSourceReference, point: QPointF) -> bool:
        """Hit test provider content or intrinsic source bounds."""
        if isinstance(source, RasterSource):
            provider = source.provider
            if isinstance(provider, RasterHitTestProvider):
                return provider.contains(point)
            bounds = source.bounds
        elif isinstance(source, (VectorSource, HybridSource)):
            bounds = source.bounds
        else:
            return False
        return (
            bounds.x <= point.x() < bounds.right
            and bounds.y <= point.y() < bounds.bottom
        )

    def vector_document(
        self,
        source: LayerSourceReference,
    ) -> VectorPresentationSnapshot | None:
        """Return one semantic vector presentation snapshot."""
        if not isinstance(source, VectorSource):
            return None
        document = source.document
        return VectorPresentationSnapshot(
            document,
            (
                document.vector_id,
                document.revision,
                source.presentation_revision,
            ),
            source.preview_object_id,
        )

    def hybrid_document(self, source: LayerSourceReference) -> HybridSource | None:
        """Return one immutable hybrid presentation snapshot."""
        return source if isinstance(source, HybridSource) else None


class RenderSceneController:
    """Own the currently submitted public render scene and its adaptation."""

    def __init__(self, capabilities: LayerSourceCapabilities) -> None:
        """Register one adapter for public raster and vector source handles."""
        self._scene: RenderScene | None = None
        self._revision = 0
        self._sources = RenderSdkSourceCapabilities()
        capabilities.metadata.register(RasterSource, self._sources)
        capabilities.rasters.register(RasterSource, self._sources)
        capabilities.raster_patches.register(RasterSource, self._sources)
        capabilities.hit_tests.register(RasterSource, self._sources)
        capabilities.metadata.register(VectorSource, self._sources)
        capabilities.vectors.register(VectorSource, self._sources)
        capabilities.hit_tests.register(VectorSource, self._sources)
        capabilities.metadata.register(HybridSource, self._sources)
        capabilities.hybrids.register(HybridSource, self._sources)
        capabilities.hit_tests.register(HybridSource, self._sources)

    @property
    def scene(self) -> RenderScene | None:
        """Return the immutable scene currently submitted by the host."""
        return self._scene

    def set_scene(self, scene: RenderScene | None) -> bool:
        """Replace or clear the submitted scene and publish a new revision."""
        if scene is not None and not isinstance(scene, RenderScene):
            raise TypeError("scene must be RenderScene or None")
        if scene == self._scene:
            return False
        self._scene = scene
        self._revision += 1
        return True

    def revision(self) -> int:
        """Return the scene replacement generation."""
        return self._revision

    def scene_contribution(self) -> SceneContribution | None:
        """Return the current SDK scene with priority over viewer adapters."""
        scene = self._scene
        if scene is None:
            return None
        return SceneContribution(self._descriptor(scene), order=-10_000)

    def scene_descriptor(self) -> SceneDescriptor | None:
        """Return the current scene in QPane's sole internal scene format."""
        scene = self._scene
        return None if scene is None else self._descriptor(scene)

    @staticmethod
    def _descriptor(scene: RenderScene) -> SceneDescriptor:
        """Project public scene values into the sole internal scene primitive."""
        canvas = scene.canvas
        bounds = LayerPlacement(
            canvas.x(),
            canvas.y(),
            canvas.width(),
            canvas.height(),
        )
        layers = tuple(
            LayerDescriptor(
                scene_id=scene.scene_id,
                layer_id=layer.layer_id,
                kind=(
                    LayerKind.IMAGE
                    if isinstance(layer.source, RasterSource)
                    else (
                        LayerKind.VECTOR
                        if isinstance(layer.source, VectorSource)
                        else LayerKind.HYBRID
                    )
                ),
                source=layer.source,
                placement=layer.transform.map_bounds(layer.source.bounds),
                visible=layer.visible,
                opacity=layer.opacity,
                blend_mode=layer.blend_mode,
                clip=layer.clip,
                hit_test=LayerHitTest(enabled=layer.hit_test, role=layer.role),
                capabilities=LayerContentCapabilities(),
                source_revision=layer.source.revision,
                raster_bounds=layer.source.bounds,
                transform=layer.transform,
                label=layer.label,
            )
            for layer in scene.layers
        )
        return SceneDescriptor(
            scene_id=scene.scene_id,
            kind=SceneKind.EXPLICIT,
            bounds=bounds,
            layers=layers,
        )
