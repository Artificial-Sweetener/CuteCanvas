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
"""Authoritative affine mapping from paint destinations into sampled content."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF
from qpane.sdk.scene import LayerTransform


@dataclass(frozen=True, slots=True)
class AffineSampleMapping:
    """Map destination scene coordinates into one sampled scene."""

    destination_to_source: LayerTransform

    @classmethod
    def anchored(
        cls,
        *,
        destination_anchor: QPointF,
        source_anchor: QPointF,
        inverse_content_transform: LayerTransform,
    ) -> AffineSampleMapping:
        """Anchor one inverse content transform at two corresponding points."""
        mapped_destination = inverse_content_transform.map_vector(destination_anchor)
        return cls(
            LayerTransform(
                inverse_content_transform.m11,
                inverse_content_transform.m12,
                inverse_content_transform.m21,
                inverse_content_transform.m22,
                source_anchor.x() - mapped_destination.x(),
                source_anchor.y() - mapped_destination.y(),
            )
        )

    def map_point(self, destination: QPointF) -> QPointF:
        """Return the sampled scene point for one destination scene point."""
        return self.destination_to_source.map_point(destination)

    def map_vector(self, destination_vector: QPointF) -> QPointF:
        """Return the sampled displacement for one destination displacement."""
        return self.destination_to_source.map_vector(destination_vector)

    def layer_raster_to_source_scene(
        self,
        layer_to_destination_scene: LayerTransform,
    ) -> LayerTransform:
        """Map destination raster edges through center-anchored scene sampling."""
        raster_edges_to_centers = LayerTransform(dx=-0.5, dy=-0.5)
        source_centers_to_edges = LayerTransform(dx=0.5, dy=0.5)
        return (
            raster_edges_to_centers.followed_by(layer_to_destination_scene)
            .followed_by(self.destination_to_source)
            .followed_by(source_centers_to_edges)
        )
