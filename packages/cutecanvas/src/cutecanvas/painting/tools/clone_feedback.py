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
"""Project Clone Stamp sample mappings into exact panel-space feedback."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QPointF
from qpane.sdk.rendering import SceneCoordinateSystem, ScenePoint
from qpane.sdk.scene import LayerMapping

from ..clone_operation import CloneStampOperation
from .brush_preview import AffineBrushPreview


class CloneStampFeedbackProjector:
    """Project one target brush footprint through the active sample mapping."""

    def __init__(
        self,
        *,
        operation: CloneStampOperation,
        coordinates: SceneCoordinateSystem,
    ) -> None:
        """Bind clone mapping, selected destination, and QPane coordinates."""
        self._operation = operation
        self._coordinates = coordinates

    def footprint(self, diameter: float) -> AffineBrushPreview | None:
        """Return the transformed sampled-area footprint in panel coordinates."""
        layer = self._operation.destination_layer()
        center = self._operation.source_scene_point()
        linear = self._operation.sample_linear_transform()
        if layer is None or layer.transform is None or center is None:
            return None
        radius = max(0.5, float(diameter) / 2.0)
        destination_x = _mapped_vector_at(
            layer.transform,
            center,
            QPointF(radius, 0.0),
        )
        destination_y = _mapped_vector_at(
            layer.transform,
            center,
            QPointF(0.0, radius),
        )
        if destination_x is None or destination_y is None:
            return None
        source_x = linear.map_vector(destination_x)
        source_y = linear.map_vector(destination_y)
        panel_center = self._panel_point(layer.scene_id, center)
        panel_x = self._panel_point(layer.scene_id, center + source_x)
        panel_y = self._panel_point(layer.scene_id, center + source_y)
        if panel_center is None or panel_x is None or panel_y is None:
            return None
        axis_x = panel_x - panel_center
        axis_y = panel_y - panel_center
        return AffineBrushPreview(
            center_x=panel_center.x(),
            center_y=panel_center.y(),
            axis_x_x=axis_x.x(),
            axis_x_y=axis_x.y(),
            axis_y_x=axis_y.x(),
            axis_y_y=axis_y.y(),
            contact=self._operation.stroke_active,
        )

    def _panel_point(
        self,
        scene_id: uuid.UUID,
        point: QPointF,
    ) -> QPointF | None:
        """Project one scene point through the authoritative QPane view."""
        projected = self._coordinates.scene_to_panel(
            ScenePoint.from_qt(scene_id, point)
        )
        return None if projected is None else projected.to_qt()


def _mapped_vector_at(
    mapping: LayerMapping,
    scene_anchor: QPointF,
    local_vector: QPointF,
) -> QPointF | None:
    """Return one local vector mapped at a finite projective anchor."""
    local_anchor = mapping.inverse_map(scene_anchor)
    if local_anchor is None:
        return None
    mapped_anchor = mapping.map_point(local_anchor)
    mapped_tip = mapping.map_point(local_anchor + local_vector)
    return mapped_tip - mapped_anchor
