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

"""Hit-test compiled render items through their exact frame geometry."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF

from ..scene.model import ClipCoordinateSpace
from ..scene.render_plan import (
    RasterLayerRenderItem,
    SampledLayerRenderItem,
    SceneLayerHitTestResult,
    SceneRenderItem,
    SceneRenderPlan,
    VectorLayerRenderItem,
)


class SceneRenderHitTester:
    """Own render-item hit testing and clip-coordinate projection."""

    def hit_test(
        self,
        plan: SceneRenderPlan,
        item: SceneRenderItem,
        panel_point: QPointF,
    ) -> SceneLayerHitTestResult | None:
        """Return layer hit metadata when a panel point intersects an item."""
        descriptor = item.descriptor
        if (
            not descriptor.visible
            or not descriptor.hit_test.enabled
            or descriptor.source is None
        ):
            return None
        inverse, invertible = item.transform.inverted()
        if not invertible:
            return None
        try:
            source_point = inverse.map(panel_point)
        except ValueError:
            return None
        source_width, source_height = self._source_size(item)
        source_rect = QRectF(0.0, 0.0, float(source_width), float(source_height))
        if not source_rect.contains(source_point):
            return None
        if not self._source_point_inside_clip(plan, item, source_point):
            return None
        if item.effect_clip_path is not None and not item.effect_clip_path.contains(
            source_point
        ):
            return None
        scene_point = self._scene_point_for_render_source(item, source_point)
        if scene_point is None:
            return None
        return SceneLayerHitTestResult(
            scene_id=descriptor.scene_id,
            layer_id=descriptor.layer_id,
            role=descriptor.hit_test.role,
            source=descriptor.source,
            panel_point=QPointF(panel_point),
            scene_point=scene_point,
            source_point=self._descriptor_source_point(item, source_point),
            selectable=descriptor.interaction.selectable,
        )

    def _source_point_inside_clip(
        self,
        plan: SceneRenderPlan,
        item: SceneRenderItem,
        source_point: QPointF,
    ) -> bool:
        """Return whether a source point is inside the item's layer clip."""
        clip = item.clip
        if clip is None:
            return True
        if clip.coordinate_space == ClipCoordinateSpace.NORMALIZED_SCENE:
            clip_rect = QRectF(
                plan.scene_bounds.x + clip.x * plan.scene_bounds.width,
                plan.scene_bounds.y + clip.y * plan.scene_bounds.height,
                clip.width * plan.scene_bounds.width,
                clip.height * plan.scene_bounds.height,
            )
            point = self._scene_point_for_render_source(item, source_point)
        elif clip.coordinate_space == ClipCoordinateSpace.SCENE:
            clip_rect = QRectF(clip.x, clip.y, clip.width, clip.height)
            point = self._scene_point_for_render_source(item, source_point)
        elif clip.coordinate_space == ClipCoordinateSpace.NORMALIZED_VIEWPORT:
            clip_rect = QRectF(
                plan.qpane_rect.x() + clip.x * plan.qpane_rect.width(),
                plan.qpane_rect.y() + clip.y * plan.qpane_rect.height(),
                clip.width * plan.qpane_rect.width(),
                clip.height * plan.qpane_rect.height(),
            )
            point = item.transform.map(source_point)
        elif clip.coordinate_space == ClipCoordinateSpace.VIEWPORT:
            clip_rect = QRectF(clip.x, clip.y, clip.width, clip.height)
            point = item.transform.map(source_point)
        else:
            return True
        return point is not None and clip_rect.contains(point)

    @classmethod
    def _authoritative_source_point(
        cls,
        item: SceneRenderItem,
        render_source_point: QPointF,
    ) -> QPointF:
        """Convert best-fit coordinates to authoritative source coordinates."""
        scale = cls._source_scale(item)
        return QPointF(
            render_source_point.x() / scale,
            render_source_point.y() / scale,
        )

    @staticmethod
    def _source_scale(item: SceneRenderItem) -> float:
        """Return render-source pixels per authoritative source pixel."""
        if isinstance(item, RasterLayerRenderItem):
            scale = item.pyramid_scale
        else:
            scale = 1.0
        return scale if scale > 0.0 else 1.0

    @classmethod
    def _descriptor_source_point(
        cls,
        item: SceneRenderItem,
        render_source_point: QPointF,
    ) -> QPointF:
        """Return coordinates in the descriptor's complete source-local space."""
        local_point = cls._authoritative_source_point(item, render_source_point)
        raster_bounds = item.descriptor.raster_bounds
        if raster_bounds is not None:
            local_point += QPointF(float(raster_bounds.x), float(raster_bounds.y))
        return local_point

    @staticmethod
    def _source_size(item: SceneRenderItem) -> tuple[int, int]:
        """Return render-item source dimensions."""
        if isinstance(item, RasterLayerRenderItem):
            return item.source_image.width(), item.source_image.height()
        if isinstance(item, VectorLayerRenderItem):
            return item.source_size.width(), item.source_size.height()
        if isinstance(item, SampledLayerRenderItem):
            return item.source_size.width(), item.source_size.height()
        return 0, 0

    @classmethod
    def _scene_point_for_render_source(
        cls,
        item: SceneRenderItem,
        render_source_point: QPointF,
    ) -> QPointF | None:
        """Map one rendered source sample through authoritative layer geometry."""
        transform = item.descriptor.transform
        if transform is None:
            return None
        local_point = cls._descriptor_source_point(item, render_source_point)
        return transform.map_point(local_point)
