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
"""Project declarative layer clips onto exact render-source geometry."""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainterPath, QTransform

from ..scene.affine import LayerTransform
from ..scene.model import ClipCoordinateSpace, LayerClip
from ..scene.render_plan import SceneRenderItem, SceneRenderPlan


def source_clip_path(
    plan: SceneRenderPlan,
    item: SceneRenderItem,
) -> QPainterPath | None:
    """Return one exact source-space path for the item's declared clip."""
    clip = item.clip
    if clip is None:
        return None
    if clip.coordinate_space in {
        ClipCoordinateSpace.NORMALIZED_SCENE,
        ClipCoordinateSpace.SCENE,
    }:
        scene_rect = scene_clip_rect(plan, clip)
        inverse = scene_to_source_transform(item)
    elif clip.coordinate_space in {
        ClipCoordinateSpace.NORMALIZED_VIEWPORT,
        ClipCoordinateSpace.VIEWPORT,
    }:
        scene_rect = viewport_clip_rect(plan, clip)
        inverse, invertible = item.transform.inverted()
        if not invertible:
            inverse = None
    else:
        return None
    path = QPainterPath()
    if scene_rect is None or inverse is None:
        return path
    path.addRect(scene_rect)
    return inverse.map(path)


def scene_clip_rect(
    plan: SceneRenderPlan,
    clip: LayerClip,
) -> QRectF | None:
    """Resolve one scene-relative clip declaration into scene coordinates."""
    if clip.coordinate_space is ClipCoordinateSpace.NORMALIZED_SCENE:
        return QRectF(
            plan.scene_bounds.x + clip.x * plan.scene_bounds.width,
            plan.scene_bounds.y + clip.y * plan.scene_bounds.height,
            clip.width * plan.scene_bounds.width,
            clip.height * plan.scene_bounds.height,
        )
    if clip.coordinate_space is ClipCoordinateSpace.SCENE:
        return QRectF(clip.x, clip.y, clip.width, clip.height)
    return None


def viewport_clip_rect(
    plan: SceneRenderPlan,
    clip: LayerClip,
) -> QRectF | None:
    """Resolve one viewport-relative clip declaration into panel coordinates."""
    if clip.coordinate_space is ClipCoordinateSpace.NORMALIZED_VIEWPORT:
        return QRectF(
            plan.qpane_rect.x() + clip.x * plan.qpane_rect.width(),
            plan.qpane_rect.y() + clip.y * plan.qpane_rect.height(),
            clip.width * plan.qpane_rect.width(),
            clip.height * plan.qpane_rect.height(),
        )
    if clip.coordinate_space is ClipCoordinateSpace.VIEWPORT:
        return QRectF(clip.x, clip.y, clip.width, clip.height)
    return None


def scene_to_source_transform(item: SceneRenderItem) -> QTransform | None:
    """Return the exact scene-to-product transform for one render item."""
    source_size = item.source_size
    source_width = source_size.width()
    source_height = source_size.height()
    if source_width <= 0 or source_height <= 0:
        return None
    descriptor_transform = item.descriptor.transform
    raster_bounds = item.descriptor.raster_bounds
    if descriptor_transform is not None:
        source_to_local = (
            LayerTransform()
            if raster_bounds is None
            else LayerTransform(
                m11=raster_bounds.width / source_width,
                m22=raster_bounds.height / source_height,
                dx=float(raster_bounds.x),
                dy=float(raster_bounds.y),
            )
        )
        source_to_scene = source_to_local.followed_by(descriptor_transform)
    else:
        placement = item.placement
        if placement.width <= 0.0 or placement.height <= 0.0:
            return None
        source_to_scene = LayerTransform(
            m11=placement.width / source_width,
            m22=placement.height / source_height,
            dx=placement.x,
            dy=placement.y,
        )
    inverse = source_to_scene.inverted()
    return None if inverse is None else inverse.to_qtransform()


__all__ = [
    "scene_clip_rect",
    "scene_to_source_transform",
    "source_clip_path",
    "viewport_clip_rect",
]
