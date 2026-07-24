#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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

"""Helpers for constructing one-layer scene render plans in tests."""

from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import QImage, Qt, QTransform
from qpane.rendering.sdk import RasterSource
from qpane.scene.identity import (
    SceneLayerAssetKey,
    SceneLayerTileKey,
    SourceRenderAssetKey,
)
from qpane.scene.model import (
    LayerDescriptor,
    LayerKind,
    LayerPlacement,
    SceneDescriptor,
    SceneKind,
)
from qpane.scene.raster import RasterBounds
from qpane.scene.render_plan import (
    RasterLayerRenderItem,
    RenderStrategy,
    SceneContentSnapshot,
    SceneRenderPlan,
    TileRenderData,
)


def make_render_plan(
    qpane_rect: QRect,
    *,
    source_image: QImage | None = None,
    image_id: uuid.UUID | None = None,
    source_path: Path | None = None,
    pyramid_scale: float = 1.0,
    transform: QTransform | None = None,
    zoom: float = 1.0,
    strategy: RenderStrategy = RenderStrategy.DIRECT,
    render_hint_enabled: bool = False,
    debug_draw_tile_grid: bool = False,
    tiles_to_draw: tuple[TileRenderData, ...] = (),
    tile_size: int = 64,
    tile_overlap: int = 0,
    max_tile_cols: int = 1,
    max_tile_rows: int = 1,
    current_pan: QPointF | None = None,
    physical_viewport_rect: QRectF | None = None,
    visible_tile_range: tuple[int, int, int, int] | None = None,
) -> SceneRenderPlan:
    """Return a source-neutral one-layer render plan for renderer tests."""
    if source_image is None:
        source_image = QImage(qpane_rect.size(), QImage.Format_ARGB32_Premultiplied)
        source_image.fill(Qt.white)
    if image_id is None:
        image_id = uuid.uuid4()
    source = RasterSource.from_image(
        source_image,
        source_id=image_id,
        path=source_path,
        source_kind="test-raster",
    )
    scene_id = uuid.uuid5(image_id, "test-scene")
    placement = LayerPlacement(
        0.0,
        0.0,
        float(source_image.width()),
        float(source_image.height()),
    )
    layer = LayerDescriptor(
        scene_id=scene_id,
        layer_id=uuid.uuid5(image_id, "test-layer"),
        kind=LayerKind.IMAGE,
        source=source,
        placement=placement,
        source_revision=0,
        raster_bounds=RasterBounds(
            0,
            0,
            source_image.width(),
            source_image.height(),
        ),
    )
    scene = SceneDescriptor(
        scene_id=scene_id,
        kind=SceneKind.EXPLICIT,
        bounds=placement,
        layers=(layer,),
    )
    asset_key = SceneLayerAssetKey(
        scene_id=scene.scene_id,
        layer_id=layer.layer_id,
        source_id=image_id,
        source_kind=source.source_kind,
        source_revision=0,
        source_path=source_path,
    )
    item = RasterLayerRenderItem(
        descriptor=layer,
        source_image=source_image,
        asset_key=asset_key,
        pyramid_asset_key=SourceRenderAssetKey(
            source_id=image_id,
            source_kind=source.source_kind,
            source_revision=0,
            source_path=source_path,
        ),
        pyramid_scale=pyramid_scale,
        transform=transform if transform is not None else QTransform(),
        placement=layer.placement,
        clip=layer.clip,
        strategy=strategy,
        render_hint_enabled=render_hint_enabled,
        debug_draw_tile_grid=debug_draw_tile_grid,
        tiles_to_draw=tiles_to_draw,
        tile_size=tile_size,
        tile_overlap=tile_overlap,
        max_tile_cols=max_tile_cols,
        max_tile_rows=max_tile_rows,
        visible_tile_range=visible_tile_range,
        is_base_raster=True,
    )
    return SceneRenderPlan(
        scene_id=scene.scene_id,
        scene_bounds=scene.bounds,
        content_bounds=scene.bounds,
        content_snapshot=SceneContentSnapshot(
            scene_id=scene.scene_id,
            base_asset_key=asset_key,
            base_image_size=source_image.size(),
            scene_bounds=scene.bounds,
            active_content_bounds=scene.bounds,
            current_path=source_path,
        ),
        zoom=zoom,
        current_pan=QPointF(current_pan or QPointF(0.0, 0.0)),
        qpane_rect=qpane_rect,
        physical_viewport_rect=QRectF(physical_viewport_rect or QRectF(qpane_rect)),
        render_items=(item,),
        hit_test_items=(),
    )


def make_tile_key(
    image_id: uuid.UUID | None = None,
    source_path: Path | None = None,
    pyramid_scale: float = 1.0,
    row: int = 0,
    col: int = 0,
    *,
    revision: int = 0,
) -> SceneLayerTileKey:
    """Return a source-neutral tile key for tests."""
    if image_id is None:
        image_id = uuid.uuid4()
    scene_id = uuid.uuid5(image_id, "test-scene")
    asset_key = SceneLayerAssetKey(
        scene_id=scene_id,
        layer_id=uuid.uuid5(image_id, "test-layer"),
        source_id=image_id,
        source_kind="test-raster",
        source_revision=revision,
        source_path=source_path,
    )
    return SceneLayerTileKey(
        asset_key=asset_key,
        pyramid_asset_key=SourceRenderAssetKey(
            source_id=image_id,
            source_kind="test-raster",
            source_revision=revision,
            source_path=source_path,
        ),
        pyramid_scale=pyramid_scale,
        row=row,
        col=col,
    )


def make_source_key(
    source_id: uuid.UUID | None = None,
    source_path: Path | None = None,
    *,
    revision: int = 0,
) -> SourceRenderAssetKey:
    """Return one reusable source-product key for renderer tests."""
    return SourceRenderAssetKey(
        source_id=source_id or uuid.uuid4(),
        source_kind="test-raster",
        source_revision=revision,
        source_path=source_path,
    )
