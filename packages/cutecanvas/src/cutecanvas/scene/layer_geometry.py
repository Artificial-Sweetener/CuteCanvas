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
"""Layer manipulation geometry policy and authoritative bounds resolution."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF

from qpane.sdk.scene import (
    BilinearLayerTransform,
    LayerDescriptor,
    PiecewiseLayerTransform,
    RasterBounds,
)

from ..composition.geometry_policy import LayerGeometryMode, LayerGeometryPolicy
from .source_capabilities import EditorSourceCapabilities


class LayerGeometryResolver:
    """Resolve one layer's manipulation bounds through explicit host policy."""

    def __init__(
        self,
        sources: EditorSourceCapabilities,
        policy_for: Callable[[LayerDescriptor], LayerGeometryPolicy],
    ) -> None:
        """Bind source geometry capabilities and host policy lookup."""
        self._sources = sources
        self._policy_for = policy_for

    def local_bounds(self, layer: LayerDescriptor) -> QRectF | None:
        """Return source-local manipulation bounds for ``layer``."""
        policy = self._policy_for(layer)
        mode = policy.mode
        if mode is LayerGeometryMode.CONTENT:
            return self._sources.content_bounds.content_bounds(layer.source)
        if mode is LayerGeometryMode.STORAGE:
            return self._sources.storage_bounds.storage_bounds(layer.source)
        if mode is LayerGeometryMode.AUTHORED:
            return self._sources.authored_bounds.authored_bounds(layer.source)
        if mode is LayerGeometryMode.CLIP:
            clip = layer.clip
            return (
                None
                if clip is None
                else QRectF(clip.x, clip.y, clip.width, clip.height)
            )
        if mode is LayerGeometryMode.CUSTOM:
            return _rectf(policy.custom_bounds)
        if mode is LayerGeometryMode.BOUNDARY:
            boundary = policy.boundary_points()
            return None if not boundary else _point_bounds(boundary)
        return _rectf(layer.raster_bounds)

    def resolved_local_bounds(self, layer: LayerDescriptor) -> QRectF | None:
        """Return policy bounds without inventing content for capable sources."""
        bounds = self.local_bounds(layer)
        if bounds is not None:
            return bounds
        policy = self._policy_for(layer)
        registry = {
            LayerGeometryMode.CONTENT: self._sources.content_bounds,
            LayerGeometryMode.STORAGE: self._sources.storage_bounds,
            LayerGeometryMode.AUTHORED: self._sources.authored_bounds,
        }.get(policy.mode)
        if registry is not None and registry.owner_for(layer.source) is not None:
            return None
        return _rectf(layer.raster_bounds)

    def resolved_scene_corners(
        self,
        layer: LayerDescriptor,
    ) -> tuple[QPointF, QPointF, QPointF, QPointF] | tuple[()]:
        """Return manipulation-bound corners mapped through the layer transform."""
        bounds = self.resolved_local_bounds(layer)
        transform = layer.transform
        if bounds is None or transform is None:
            return ()
        left = bounds.left()
        top = bounds.top()
        right = left + bounds.width()
        bottom = top + bounds.height()
        return (
            transform.map_point(QPointF(left, top)),
            transform.map_point(QPointF(right, top)),
            transform.map_point(QPointF(right, bottom)),
            transform.map_point(QPointF(left, bottom)),
        )

    def resolved_scene_boundary(
        self,
        layer: LayerDescriptor,
    ) -> tuple[QPointF, ...]:
        """Return the retained manipulation boundary in scene coordinates."""
        transform = layer.transform
        if isinstance(transform, (PiecewiseLayerTransform, BilinearLayerTransform)):
            return tuple(QPointF(point) for point in transform.target_boundary)
        policy = self._policy_for(layer)
        if transform is not None and policy.mode is LayerGeometryMode.BOUNDARY:
            return tuple(
                transform.map_point(point) for point in policy.boundary_points()
            )
        if transform is not None and policy.mode is LayerGeometryMode.CONTENT:
            boundary = self._sources.content_boundary.content_boundary(layer.source)
            if len(boundary) >= 3:
                return tuple(transform.map_point(point) for point in boundary)
        return self.resolved_scene_corners(layer)


def _rectf(bounds: RasterBounds | None) -> QRectF | None:
    """Detach integer raster geometry into the continuous editor domain."""
    return (
        None
        if bounds is None
        else QRectF(
            float(bounds.x),
            float(bounds.y),
            float(bounds.width),
            float(bounds.height),
        )
    )


def _point_bounds(points: tuple[QPointF, ...]) -> QRectF:
    """Return the finite bounding rectangle around polygon points."""
    xs = tuple(point.x() for point in points)
    ys = tuple(point.y() for point in points)
    return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
