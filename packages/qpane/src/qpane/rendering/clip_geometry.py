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

"""Project clipped render-item boundaries into widget coordinates."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from PySide6.QtCore import QLineF, QPointF, QRectF

from ..scene.model import ClipCoordinateSpace, LayerPlacement
from ..scene.render_plan import SceneRenderItem, SceneRenderPlan
from ..types import ComparisonOrientation
from .layer_clip_projection import scene_clip_rect, scene_to_source_transform


@dataclass(frozen=True, slots=True)
class ProjectedClipBoundary:
    """Projected comparison clip boundary owned by render geometry."""

    orientation: ComparisonOrientation
    item: SceneRenderItem
    scene_bounds: LayerPlacement
    full_segment: QLineF
    visible_segment: QLineF | None
    scene_position: float
    hit_width: float
    viewport_rect: QRectF | None = None

    def contains(self, point: QPointF) -> bool:
        """Return whether ``point`` is within hit tolerance of the visible segment."""
        segment = self.visible_segment
        if segment is None:
            return False
        return _distance_to_segment(point, segment) <= self.hit_width / 2.0

    def split_for_widget_point(self, point: QPointF) -> float | None:
        """Return the normalized split represented by a widget point."""
        if self.viewport_rect is not None:
            if self.orientation == ComparisonOrientation.HORIZONTAL:
                origin = self.viewport_rect.top()
                denominator = self.viewport_rect.height()
                value = point.y()
            else:
                origin = self.viewport_rect.left()
                denominator = self.viewport_rect.width()
                value = point.x()
            if denominator <= 0.0:
                return None
            return min(1.0, max(0.0, (value - origin) / denominator))
        inverse, invertible = self.item.transform.inverted()
        if not invertible:
            return None
        source_point = inverse.map(point)
        source_width = self.item.source_size.width()
        source_height = self.item.source_size.height()
        placement = self.item.placement
        if (
            source_width <= 0
            or source_height <= 0
            or placement.width <= 0.0
            or placement.height <= 0.0
        ):
            return None
        if self.orientation == ComparisonOrientation.HORIZONTAL:
            scene_value = (
                placement.y + source_point.y() * placement.height / source_height
            )
            denominator = self.scene_bounds.height
            origin = self.scene_bounds.y
        else:
            scene_value = (
                placement.x + source_point.x() * placement.width / source_width
            )
            denominator = self.scene_bounds.width
            origin = self.scene_bounds.x
        if denominator <= 0.0:
            return None
        return min(1.0, max(0.0, (scene_value - origin) / denominator))


def projected_comparison_boundary(
    plan: SceneRenderPlan,
    *,
    orientation: ComparisonOrientation,
    hit_width: float,
    source_id: object | None = None,
    split_position: float | None = None,
) -> ProjectedClipBoundary | None:
    """Return the projected boundary for the active comparison render item."""
    item = _comparison_item(plan, source_id=source_id)
    if item is None or item.clip is None:
        return None
    viewport_boundary = _viewport_comparison_boundary(
        plan,
        item,
        orientation=orientation,
        hit_width=hit_width,
        split_position=split_position,
    )
    if viewport_boundary is not None:
        return viewport_boundary
    scene_clip = (
        _normalized_comparison_clip(
            plan,
            split_position,
            orientation=orientation,
        )
        if split_position is not None
        else scene_clip_rect(plan, item.clip)
    )
    if scene_clip is None:
        return None
    source_line = _scene_boundary_to_source_line(
        item,
        scene_clip,
        orientation=orientation,
    )
    if source_line is None:
        return None
    full_segment = QLineF(
        item.transform.map(source_line.p1()),
        item.transform.map(source_line.p2()),
    )
    visible_segment = _clip_segment_to_rect(full_segment, QRectF(plan.qpane_rect))
    scene_position = (
        scene_clip.top()
        if orientation == ComparisonOrientation.HORIZONTAL
        else scene_clip.left()
    )
    return ProjectedClipBoundary(
        orientation=orientation,
        item=item,
        scene_bounds=plan.scene_bounds,
        full_segment=full_segment,
        visible_segment=visible_segment,
        scene_position=scene_position,
        hit_width=hit_width,
    )


def _viewport_comparison_boundary(
    plan: SceneRenderPlan,
    item: SceneRenderItem,
    *,
    orientation: ComparisonOrientation,
    hit_width: float,
    split_position: float | None,
) -> ProjectedClipBoundary | None:
    """Return one divider fixed to viewport coordinates when declared there."""

    clip = item.clip
    if clip is None or clip.coordinate_space not in {
        ClipCoordinateSpace.NORMALIZED_VIEWPORT,
        ClipCoordinateSpace.VIEWPORT,
    }:
        return None
    viewport = QRectF(plan.qpane_rect)
    if viewport.isEmpty():
        return None
    if split_position is not None:
        normalized = min(1.0, max(0.0, float(split_position)))
    elif clip.coordinate_space is ClipCoordinateSpace.NORMALIZED_VIEWPORT:
        normalized = (
            clip.y if orientation is ComparisonOrientation.HORIZONTAL else clip.x
        )
    elif orientation is ComparisonOrientation.HORIZONTAL:
        normalized = (clip.y - viewport.top()) / viewport.height()
    else:
        normalized = (clip.x - viewport.left()) / viewport.width()
    normalized = min(1.0, max(0.0, normalized))
    if orientation is ComparisonOrientation.HORIZONTAL:
        position = viewport.top() + normalized * viewport.height()
        segment = QLineF(
            QPointF(viewport.left(), position),
            QPointF(viewport.right(), position),
        )
    else:
        position = viewport.left() + normalized * viewport.width()
        segment = QLineF(
            QPointF(position, viewport.top()),
            QPointF(position, viewport.bottom()),
        )
    return ProjectedClipBoundary(
        orientation=orientation,
        item=item,
        scene_bounds=plan.scene_bounds,
        full_segment=segment,
        visible_segment=QLineF(segment),
        scene_position=normalized,
        hit_width=hit_width,
        viewport_rect=viewport,
    )


def _comparison_item(
    plan: SceneRenderPlan,
    *,
    source_id: object | None,
) -> SceneRenderItem | None:
    """Return the active comparison item from ``plan``."""
    for item in plan.render_items:
        if item.clip is None or not item.descriptor.visible:
            continue
        if source_id is not None:
            if item.descriptor.source.resource_id == source_id:
                return item
            continue
        if item.descriptor.hit_test.role in {"comparison", "comparison-image"}:
            return item
    return None


def _normalized_comparison_clip(
    plan: SceneRenderPlan,
    split_position: float,
    *,
    orientation: ComparisonOrientation,
) -> QRectF:
    """Return one normalized comparison reveal in scene coordinates."""
    normalized = min(1.0, max(0.0, float(split_position)))
    if orientation == ComparisonOrientation.HORIZONTAL:
        return QRectF(
            plan.scene_bounds.x,
            plan.scene_bounds.y + normalized * plan.scene_bounds.height,
            plan.scene_bounds.width,
            (1.0 - normalized) * plan.scene_bounds.height,
        )
    return QRectF(
        plan.scene_bounds.x + normalized * plan.scene_bounds.width,
        plan.scene_bounds.y,
        (1.0 - normalized) * plan.scene_bounds.width,
        plan.scene_bounds.height,
    )


def _scene_boundary_to_source_line(
    item: SceneRenderItem,
    scene_clip: QRectF,
    *,
    orientation: ComparisonOrientation,
) -> QLineF | None:
    """Convert the comparison clip boundary from scene to source coordinates."""
    inverse = scene_to_source_transform(item)
    if inverse is None:
        return None
    if orientation == ComparisonOrientation.HORIZONTAL:
        scene_line = QLineF(scene_clip.topLeft(), scene_clip.topRight())
    else:
        scene_line = QLineF(scene_clip.topLeft(), scene_clip.bottomLeft())
    return QLineF(inverse.map(scene_line.p1()), inverse.map(scene_line.p2()))


def _clip_segment_to_rect(line: QLineF, rect: QRectF) -> QLineF | None:
    """Clip ``line`` to ``rect`` using Liang-Barsky clipping."""
    if rect.isEmpty():
        return None
    x0 = line.p1().x()
    y0 = line.p1().y()
    x1 = line.p2().x()
    y1 = line.p2().y()
    dx = x1 - x0
    dy = y1 - y0
    p_values = (-dx, dx, -dy, dy)
    q_values = (
        x0 - rect.left(),
        rect.right() - x0,
        y0 - rect.top(),
        rect.bottom() - y0,
    )
    start = 0.0
    end = 1.0
    for p_value, q_value in zip(p_values, q_values):
        if p_value == 0.0:
            if q_value < 0.0:
                return None
            continue
        ratio = q_value / p_value
        if p_value < 0.0:
            start = max(start, ratio)
        else:
            end = min(end, ratio)
        if start > end:
            return None
    return QLineF(
        QPointF(x0 + start * dx, y0 + start * dy),
        QPointF(x0 + end * dx, y0 + end * dy),
    )


def _distance_to_segment(point: QPointF, segment: QLineF) -> float:
    """Return the shortest distance from ``point`` to ``segment``."""
    x0 = point.x()
    y0 = point.y()
    x1 = segment.p1().x()
    y1 = segment.p1().y()
    x2 = segment.p2().x()
    y2 = segment.p2().y()
    dx = x2 - x1
    dy = y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq <= 0.0:
        return hypot(x0 - x1, y0 - y1)
    ratio = max(0.0, min(1.0, ((x0 - x1) * dx + (y0 - y1) * dy) / length_sq))
    projection_x = x1 + ratio * dx
    projection_y = y1 + ratio * dy
    return hypot(x0 - projection_x, y0 - projection_y)
