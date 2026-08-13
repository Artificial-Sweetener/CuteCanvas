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

"""Diagonal finite-edge snapping for affine side-handle scaling."""

from __future__ import annotations

from dataclasses import dataclass

from cutecanvas.scene.transform_session import LayerTransformBoxState
from PySide6.QtCore import QPointF
from qpane.sdk.scene import (
    AffineTransformGeometry,
    TransformHandle,
    TransformModifiers,
    TransformOperation,
)

from .edge_candidates import OrientedTargetSnapshot
from .edge_index import OrientedEdgeIndex
from .edge_model import OrientedEdge, OrientedSnapGuide
from .oriented_resolution import OrientedEdgeSnapResolver

_SIDE_EDGE_HANDLES = {
    TransformHandle.TOP: (TransformHandle.TOP_LEFT, TransformHandle.TOP_RIGHT),
    TransformHandle.RIGHT: (TransformHandle.TOP_RIGHT, TransformHandle.BOTTOM_RIGHT),
    TransformHandle.BOTTOM: (
        TransformHandle.BOTTOM_LEFT,
        TransformHandle.BOTTOM_RIGHT,
    ),
    TransformHandle.LEFT: (TransformHandle.TOP_LEFT, TransformHandle.BOTTOM_LEFT),
}


@dataclass(slots=True)
class TransformOrientedScaleSnap:
    """Resolve one diagonal side handle against frozen parallel targets."""

    source: OrientedEdge
    resolver: OrientedEdgeSnapResolver
    geometry: AffineTransformGeometry
    operation: TransformOperation
    origin: QPointF
    initial_handle: QPointF

    def clear(self) -> None:
        """Release the oriented target retained for hysteresis."""
        self.resolver.clear()

    def resolve(
        self,
        raw_handle: QPointF,
        modifiers: TransformModifiers,
        *,
        scene_units_per_device_pixel: float,
    ) -> tuple[QPointF, OrientedSnapGuide] | None:
        """Return a corrected pointer and guide when a parallel target acquires."""
        raw_distance = QPointF.dotProduct(
            self.source.normal,
            raw_handle - self.initial_handle,
        )
        result = self.resolver.resolve(
            raw_distance,
            scene_units_per_device_pixel=scene_units_per_device_pixel,
        )
        if result.guide is None:
            return None
        desired = raw_handle + self.source.normal * (result.distance - raw_distance)
        pointer = self.origin + desired - self.initial_handle
        transform = self.geometry.transform_for_drag(
            self.operation,
            self.origin,
            pointer,
            modifiers,
        )
        return None if transform is None else (pointer, result.guide)


def create_transform_oriented_scale_snap(
    box: LayerTransformBoxState,
    operation: TransformOperation,
    origin: QPointF,
    targets: OrientedTargetSnapshot | None,
    *,
    threshold_device_pixels: float,
    release_device_pixels: float,
    scene_units_per_device_pixel: float,
) -> TransformOrientedScaleSnap | None:
    """Build diagonal side snapping or retain optimized axis ownership."""
    handle = operation.handle
    endpoints = None if handle is None else _SIDE_EDGE_HANDLES.get(handle)
    if endpoints is None or targets is None or targets.scene_id != box.scene_id:
        return None
    geometry = AffineTransformGeometry(box.bounds, box.transform)
    source = OrientedEdge(
        str(box.layer_id),
        geometry.scene_point(endpoints[0]),
        geometry.scene_point(endpoints[1]),
        geometry.scene_center(),
    )
    tangent = source.tangent
    if abs(tangent.x()) <= 1e-9 or abs(tangent.y()) <= 1e-9:
        return None
    return TransformOrientedScaleSnap(
        source,
        OrientedEdgeSnapResolver(
            source,
            OrientedEdgeIndex.build(
                targets.edges,
                scene_units_per_device_pixel=scene_units_per_device_pixel,
            ),
            threshold_device_pixels=threshold_device_pixels,
            release_device_pixels=release_device_pixels,
            grid=targets.grid,
        ),
        geometry,
        operation,
        QPointF(origin),
        geometry.scene_point(handle),
    )


__all__ = ["TransformOrientedScaleSnap", "create_transform_oriented_scale_snap"]
