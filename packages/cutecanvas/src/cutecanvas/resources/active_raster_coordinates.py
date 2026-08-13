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
"""Project panel points through the active raster layer instance."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF

from qpane import LayerSourcePoint, PanelPoint, SceneCoordinateSystem

from .active_raster import ActiveRasterResolver, ActiveRasterSnapshot


@dataclass(frozen=True, slots=True)
class ActiveRasterCoordinateProjection:
    """Capture one raster instance and its current coordinate projection."""

    snapshot: ActiveRasterSnapshot
    coordinates: SceneCoordinateSystem

    @property
    def resource_id(self) -> uuid.UUID:
        """Return the raster resource used by the captured layer instance."""
        return self.snapshot.resource_id

    @property
    def scene_id(self) -> uuid.UUID:
        """Return the scene containing the captured raster instance."""
        return self.snapshot.scene_id

    @property
    def layer_id(self) -> uuid.UUID:
        """Return the captured raster layer instance."""
        return self.snapshot.layer_id

    def panel_to_source(self, point: QPoint | QPointF) -> QPointF | None:
        """Project a logical panel point into zero-origin raster pixels."""
        projected = self.coordinates.panel_to_layer_source(
            self.snapshot.scene_id,
            self.snapshot.layer_id,
            PanelPoint.from_qt(point),
        )
        return None if projected is None else projected.to_qt()

    def source_to_panel(self, point: QPoint | QPointF) -> QPointF | None:
        """Project zero-origin raster pixels into logical panel coordinates."""
        projected = self.coordinates.layer_source_to_panel(
            LayerSourcePoint.from_qt(
                self.snapshot.scene_id,
                self.snapshot.layer_id,
                point,
            )
        )
        return None if projected is None else projected.to_qt()


class ActiveRasterCoordinateResolver:
    """Resolve a stable coordinate projection for the active raster instance."""

    def __init__(
        self,
        *,
        rasters: ActiveRasterResolver,
        coordinates: SceneCoordinateSystem,
        preferred_layer_id: Callable[[], uuid.UUID | None],
    ) -> None:
        """Bind raster, scene-coordinate, and layer-selection owners."""
        self._rasters = rasters
        self._coordinates = coordinates
        self._preferred_layer_id = preferred_layer_id

    def resolve(self) -> ActiveRasterCoordinateProjection | None:
        """Capture the current raster instance and coordinate system."""
        snapshot = self._rasters.resolve(preferred_layer_id=self._preferred_layer_id())
        if snapshot is None:
            return None
        return ActiveRasterCoordinateProjection(snapshot, self._coordinates)


__all__ = (
    "ActiveRasterCoordinateProjection",
    "ActiveRasterCoordinateResolver",
)
