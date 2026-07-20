#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Frame planning for resolution-independent vector render primitives."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize

from ..scene.render_plan import VectorLayerRenderItem, VectorTileRenderData
from ..scene.source_capabilities import VectorPresentationRegistry
from ..vector.model import VectorDocument
from ..vector.projection import VectorPresentationSnapshot
from ..vector.render_cache import VectorRenderCache
from ..vector.render_tiles import VectorRenderWorkCoordinator
from .compiled_scene import CompiledRenderScene
from .frame_geometry import RenderFrameGeometry
from .frame_projector import SceneFrameProjector


class VectorRenderPlanner:
    """Compile visible vector documents into ordered frame primitives."""

    def __init__(
        self,
        *,
        sources: VectorPresentationRegistry,
        projector: SceneFrameProjector,
        cache: VectorRenderCache,
        refinement: VectorRenderWorkCoordinator,
    ) -> None:
        """Bind vector snapshots, frame projection, and derived cache."""
        self._sources = sources
        self._projector = projector
        self._cache = cache
        self._refinement = refinement

    def build_frame_items(
        self,
        compiled: CompiledRenderScene,
        frame: RenderFrameGeometry,
    ) -> tuple[VectorLayerRenderItem, ...]:
        """Return vector primitives for every compiled vector layer."""
        items: list[VectorLayerRenderItem] = []
        for layer in compiled.vector_layers:
            snapshot = self._sources.vector_document(layer.source)
            if not isinstance(snapshot, VectorPresentationSnapshot):
                continue
            document = snapshot.document
            layer_to_panel = self._projector.layer_to_panel(
                scene=compiled.scene,
                layer=layer,
                source_size=QSize(
                    document.bounds.width,
                    document.bounds.height,
                ),
                frame=frame,
            )
            refined_tiles: tuple[VectorTileRenderData, ...] = ()
            if snapshot.preview_object_id is None:
                if _needs_refinement(document):
                    product = self._cache.empty_product(document.vector_id)
                    refinement = self._refinement.request(
                        document=document,
                        revision_key=snapshot.revision_key,
                        source_to_panel=layer_to_panel,
                        panel_rect=QRectF(frame.qpane_rect),
                        device_pixel_ratio=_device_pixel_ratio(frame),
                    )
                    if refinement.products is None and not refinement.pending:
                        product = self._cache.product(
                            document,
                            snapshot.revision_key,
                        )
                    else:
                        refined_tiles = tuple(
                            VectorTileRenderData(
                                product.image,
                                product.source_rect,
                                product.image_source_rect,
                            )
                            for product in (refinement.products or ())
                        )
                else:
                    product = self._cache.product(document, snapshot.revision_key)
                preview_picture = None
                trailing_picture = None
            else:
                product, preview, trailing = self._cache.preview_products(
                    document,
                    snapshot.preview_object_id,
                    snapshot.revision_key[1],
                )
                preview_picture = preview.picture
                trailing_picture = trailing.picture
            items.append(
                VectorLayerRenderItem(
                    descriptor=layer,
                    picture=product.picture,
                    transform=layer_to_panel,
                    placement=layer.placement,
                    clip=layer.clip,
                    source_size=QSize(
                        document.bounds.width,
                        document.bounds.height,
                    ),
                    preview_picture=preview_picture,
                    trailing_picture=trailing_picture,
                    refined_tiles=refined_tiles,
                )
            )
        return tuple(items)


def _needs_refinement(document: VectorDocument) -> bool:
    """Return whether semantic complexity warrants asynchronous tile rendering."""
    complexity = sum(
        max(
            1,
            len(item.path),
            0 if item.text is None else len(item.text.text) // 4,
        )
        for item in document.objects
    )
    return complexity >= 512


def _device_pixel_ratio(frame: RenderFrameGeometry) -> float:
    """Derive physical/logical scale from detached frame geometry."""
    logical_width = frame.qpane_rect.width()
    if logical_width <= 0:
        return 1.0
    return max(0.01, frame.physical_viewport_rect.width() / logical_width)
