#    CuteCanvas - High-performance layered image editor
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
"""Sample nested composition resources through QPane's shared tile renderer."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize
from PySide6.QtGui import QImage, QTransform

from qpane.sdk.rendering import (
    RenderTileProduct,
    RenderTileRequest,
    SceneRegionRasterizer,
)
from qpane.sdk.scene import (
    BlendMode,
    LayerContentCapabilities,
    LayerDescriptor,
    LayerHitTest,
    LayerKind,
    LayerPlacement,
    LayerSourceReference,
    RasterBounds,
    RasterPresentation,
    RasterProductPolicy,
    SceneDescriptor,
    SceneKind,
)

from ..composition.layers import CompositionLayerInstance
from ..composition.service import CompositionService
from ..scene.layer_assembly import CompositionLayerSceneAssembler
from .model import (
    ProjectResourceKind,
    ProjectResourceRecord,
    ProjectResourceReference,
)
from .store import ProjectResourceStore


@dataclass(frozen=True, slots=True)
class CompositionRenderTileSource:
    """Render one immutable composition revision on QPane's sampled tile grid."""

    resource_id: uuid.UUID
    resource_revision: int
    canvas_bounds: QRectF
    scene: SceneDescriptor
    rasterizer: SceneRegionRasterizer

    def __post_init__(self) -> None:
        """Detach mutable geometry and reject inconsistent source snapshots."""
        canvas_bounds = QRectF(self.canvas_bounds)
        if canvas_bounds.width() <= 0.0 or canvas_bounds.height() <= 0.0:
            raise ValueError("composition render bounds must be positive")
        if self.scene.scene_id != self.resource_id:
            raise ValueError(
                "composition render scene identity must match its resource"
            )
        object.__setattr__(self, "canvas_bounds", canvas_bounds)

    @property
    def source_kind(self) -> str:
        """Return the stable sampled-cache namespace."""
        return "composition"

    @property
    def source_id(self) -> uuid.UUID:
        """Return the reusable composition resource identity."""
        return self.resource_id

    @property
    def revision_key(self) -> Hashable:
        """Return the immutable dependency-aware resource revision."""
        return self.resource_revision

    @property
    def fallback_key(self) -> Hashable:
        """Return exact composition content fallback identity."""
        bounds = self.canvas_bounds
        return (
            bounds.x(),
            bounds.y(),
            bounds.width(),
            bounds.height(),
            self.resource_revision,
        )

    @property
    def bounds(self) -> RasterBounds:
        """Return finite zero-origin source-local sampling bounds."""
        return _raster_bounds(self.canvas_bounds)

    def sample(self, source_rect: QRectF, pixel_size: QSize) -> QImage:
        """Sample a source-local region through the nested scene descriptor."""
        if source_rect.isEmpty() or pixel_size.isEmpty():
            return QImage()
        scale_x = pixel_size.width() / source_rect.width()
        scale_y = pixel_size.height() / source_rect.height()
        canvas = self.canvas_bounds
        scene_to_pixels = QTransform(
            scale_x,
            0.0,
            0.0,
            scale_y,
            -(canvas.x() + source_rect.x()) * scale_x,
            -(canvas.y() + source_rect.y()) * scale_y,
        )
        return self.rasterizer.rasterize(
            self.scene,
            QSize(pixel_size),
            scene_to_pixels,
        )

    def render_tiles(
        self,
        requests: tuple[RenderTileRequest, ...],
        is_cancelled: Callable[[], bool],
    ) -> tuple[RenderTileProduct, ...]:
        """Render one complete request batch with one shared scene evaluation."""
        if not requests or is_cancelled():
            return ()
        scale = requests[0].key.scale
        batch_rect = QRectF(requests[0].paint_rect)
        for request in requests[1:]:
            if request.key.scale != scale:
                raise ValueError("composition tile batches must use one sample scale")
            batch_rect = batch_rect.united(request.paint_rect)
        sampled = self.sample(batch_rect, _sample_size(batch_rect, scale))
        if sampled.isNull() or is_cancelled():
            return ()
        products: list[RenderTileProduct] = []
        for request in requests:
            if is_cancelled():
                return ()
            paint_rect = request.paint_rect
            sample_rect = _pixel_rect(paint_rect, batch_rect, scale)
            image = sampled.copy(sample_rect.toAlignedRect())
            image_source_rect = _pixel_rect(
                request.source_rect,
                paint_rect,
                scale,
            )
            products.append(
                RenderTileProduct(
                    request.key,
                    request.source_rect,
                    image,
                    image_source_rect,
                )
            )
        return tuple(products)


class CompositionResourceRenderingOwner:
    """Own descriptors and immutable sampled snapshots for composition resources."""

    def __init__(
        self,
        *,
        resources: ProjectResourceStore,
        compositions: CompositionService,
        assembler: CompositionLayerSceneAssembler,
        rasterizer: SceneRegionRasterizer,
    ) -> None:
        """Bind authoritative document, graph, assembly, and sampling owners."""
        self._resources = resources
        self._compositions = compositions
        self._assembler = assembler
        self._rasterizer = rasterizer

    def descriptor(
        self,
        scene: SceneDescriptor,
        instance: CompositionLayerInstance,
        resource: ProjectResourceRecord,
    ) -> LayerDescriptor | None:
        """Resolve one nested composition as a non-raster-editable layer."""
        if (
            not isinstance(instance.source, ProjectResourceReference)
            or resource.kind is not ProjectResourceKind.COMPOSITION
        ):
            return None
        record = self._compositions.record(resource.resource_id)
        bounds = _raster_bounds(record.canvas_bounds)
        return LayerDescriptor(
            scene_id=scene.scene_id,
            layer_id=instance.layer_id,
            kind=LayerKind.IMAGE,
            source=instance.source,
            placement=instance.transform.map_bounds(bounds),
            visible=instance.visible,
            opacity=instance.opacity,
            blend_mode=BlendMode.NORMAL,
            clip=instance.clip,
            effects=instance.effects,
            hit_test=LayerHitTest(enabled=instance.hit_test, role=instance.role),
            interaction=instance.interaction,
            capabilities=LayerContentCapabilities(raster_editable=False),
            source_revision=resource.revision,
            raster_bounds=bounds,
            transform=instance.transform,
        )

    def sampled_source(
        self,
        source: LayerSourceReference,
    ) -> CompositionRenderTileSource | None:
        """Return one dependency-aware immutable nested-document snapshot."""
        resource = self._resource(source)
        if resource is None:
            return None
        record = self._compositions.record(resource.resource_id)
        document = SceneDescriptor(
            scene_id=record.composition_id,
            kind=SceneKind.EXPLICIT,
            bounds=LayerPlacement(
                record.canvas_bounds.x(),
                record.canvas_bounds.y(),
                record.canvas_bounds.width(),
                record.canvas_bounds.height(),
            ),
            layers=(),
        )
        return CompositionRenderTileSource(
            resource.resource_id,
            resource.revision,
            record.canvas_bounds,
            self._assembler.assemble(document),
            self._rasterizer,
        )

    def presentation_for(
        self,
        source: LayerSourceReference,
    ) -> RasterPresentation | None:
        """Return no dense raster primitive for a nested composition."""
        return None

    def product_policy(self, source: LayerSourceReference) -> RasterProductPolicy:
        """Return cacheable products keyed by dependency-aware revisions."""
        return RasterProductPolicy.CACHEABLE

    def source_image(
        self,
        source: LayerSourceReference,
        *,
        scale: float | None = None,
    ) -> QImage | None:
        """Return no eagerly materialized full-document image."""
        return None

    def source_size(self, source: LayerSourceReference) -> QSize | None:
        """Return finite intrinsic dimensions for a composition resource."""
        resource = self._resource(source)
        if resource is None:
            return None
        bounds = _raster_bounds(
            self._compositions.record(resource.resource_id).canvas_bounds
        )
        return QSize(bounds.width, bounds.height)

    def source_path(self, source: LayerSourceReference) -> Path | None:
        """Return no external path for an embedded composition resource."""
        return None

    def contains(self, source: LayerSourceReference, point: QPointF) -> bool:
        """Return whether a point lies inside the nested composition canvas."""
        bounds = self.storage_bounds(source)
        return bool(bounds is not None and bounds.contains(point))

    def content_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return the finite document envelope for generic geometry consumers."""
        return self.storage_bounds(source)

    def storage_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return zero-origin storage geometry for the nested composition."""
        size = self.source_size(source)
        return (
            None
            if size is None
            else QRectF(0.0, 0.0, float(size.width()), float(size.height()))
        )

    def authored_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return the document canvas as its explicit authored envelope."""
        return self.storage_bounds(source)

    def _resource(
        self,
        source: LayerSourceReference,
    ) -> ProjectResourceRecord | None:
        """Resolve only retained composition resources."""
        if not isinstance(source, ProjectResourceReference):
            return None
        resource = self._resources.resolve(source)
        return (
            resource
            if resource is not None and resource.kind is ProjectResourceKind.COMPOSITION
            else None
        )


def _raster_bounds(bounds: QRectF) -> RasterBounds:
    """Return zero-origin integer sampling bounds enclosing a canvas."""
    return RasterBounds(
        0,
        0,
        max(1, math.ceil(bounds.width())),
        max(1, math.ceil(bounds.height())),
    )


def _sample_size(rect: QRectF, scale: float) -> QSize:
    """Return positive sampled dimensions for one source-local rectangle."""
    return QSize(
        max(1, math.ceil(rect.width() * scale)),
        max(1, math.ceil(rect.height() * scale)),
    )


def _pixel_rect(rect: QRectF, origin: QRectF, scale: float) -> QRectF:
    """Map source-local geometry into one sampled batch image."""
    return QRectF(
        (rect.x() - origin.x()) * scale,
        (rect.y() - origin.y()) * scale,
        rect.width() * scale,
        rect.height() * scale,
    )
