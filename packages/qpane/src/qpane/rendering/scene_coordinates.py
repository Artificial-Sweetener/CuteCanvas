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
"""Typed projection between panel, scene, and layer-source coordinates."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QTransform

from ..scene.affine import LayerTransform
from ..scene.bilinear import BilinearLayerTransform
from ..scene.mapping import LayerMapping
from ..scene.piecewise import PiecewiseLayerTransform
from ..scene.projective import ProjectiveLayerTransform


@dataclass(frozen=True, slots=True)
class PanelPoint:
    """Identify one point in logical widget coordinates."""

    x: float
    y: float

    def __post_init__(self) -> None:
        """Reject non-finite panel coordinates."""
        _validate_coordinates(self.x, self.y)

    @classmethod
    def from_qt(cls, point: QPoint | QPointF) -> PanelPoint:
        """Copy one Qt point into the panel coordinate domain."""
        if not isinstance(point, (QPoint, QPointF)):
            raise TypeError("point must be QPoint or QPointF")
        value = QPointF(point)
        return cls(value.x(), value.y())

    def to_qt(self) -> QPointF:
        """Return a detached Qt representation."""
        return QPointF(self.x, self.y)


@dataclass(frozen=True, slots=True)
class ScenePoint:
    """Identify one absolute point in a particular render scene."""

    scene_id: uuid.UUID
    x: float
    y: float

    def __post_init__(self) -> None:
        """Reject invalid scene identity or coordinates."""
        if not isinstance(self.scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        _validate_coordinates(self.x, self.y)

    @classmethod
    def from_qt(
        cls,
        scene_id: uuid.UUID,
        point: QPoint | QPointF,
    ) -> ScenePoint:
        """Copy one Qt point into an identified scene coordinate domain."""
        if not isinstance(point, (QPoint, QPointF)):
            raise TypeError("point must be QPoint or QPointF")
        value = QPointF(point)
        return cls(scene_id, value.x(), value.y())

    def to_qt(self) -> QPointF:
        """Return a detached Qt representation."""
        return QPointF(self.x, self.y)


@dataclass(frozen=True, slots=True)
class LayerSourcePoint:
    """Identify one point in a particular layer's zero-origin source space."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    x: float
    y: float

    def __post_init__(self) -> None:
        """Reject invalid layer identity or coordinates."""
        if not isinstance(self.scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(self.layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        _validate_coordinates(self.x, self.y)

    @classmethod
    def from_qt(
        cls,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        point: QPoint | QPointF,
    ) -> LayerSourcePoint:
        """Copy one Qt point into an identified layer-source domain."""
        if not isinstance(point, (QPoint, QPointF)):
            raise TypeError("point must be QPoint or QPointF")
        value = QPointF(point)
        return cls(scene_id, layer_id, value.x(), value.y())

    def to_qt(self) -> QPointF:
        """Return a detached Qt representation."""
        return QPointF(self.x, self.y)


@dataclass(frozen=True, slots=True)
class LayerLocalPoint:
    """Identify one point in a layer's authored local coordinate space."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    x: float
    y: float

    def __post_init__(self) -> None:
        """Reject invalid layer identity or coordinates."""
        if not isinstance(self.scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(self.layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        _validate_coordinates(self.x, self.y)

    @classmethod
    def from_qt(
        cls,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        point: QPoint | QPointF,
    ) -> LayerLocalPoint:
        """Copy one Qt point into an identified layer-local domain."""
        if not isinstance(point, (QPoint, QPointF)):
            raise TypeError("point must be QPoint or QPointF")
        value = QPointF(point)
        return cls(scene_id, layer_id, value.x(), value.y())

    def to_qt(self) -> QPointF:
        """Return a detached Qt representation."""
        return QPointF(self.x, self.y)


class SceneCoordinateProjection:
    """Project typed points through one immutable scene-frame transform."""

    __slots__ = ("_panel_to_scene", "_scene_to_panel", "scene_id")

    def __init__(self, scene_id: uuid.UUID, scene_to_panel: QTransform) -> None:
        """Capture one scene identity and its absolute panel transform."""
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(scene_to_panel, QTransform):
            raise TypeError("scene_to_panel must be a QTransform")
        panel_to_scene, invertible = scene_to_panel.inverted()
        self.scene_id = scene_id
        self._scene_to_panel = QTransform(scene_to_panel)
        self._panel_to_scene = QTransform(panel_to_scene) if invertible else None

    def panel_to_scene(self, point: PanelPoint) -> ScenePoint | None:
        """Project a logical panel point into this scene."""
        if not isinstance(point, PanelPoint):
            raise TypeError("point must be PanelPoint")
        if self._panel_to_scene is None:
            return None
        result = self._panel_to_scene.map(point.to_qt())
        return ScenePoint(self.scene_id, result.x(), result.y())

    def scene_to_panel(self, point: ScenePoint) -> PanelPoint | None:
        """Project a point from this scene into logical panel coordinates."""
        if not isinstance(point, ScenePoint):
            raise TypeError("point must be ScenePoint")
        if point.scene_id != self.scene_id:
            return None
        result = self._scene_to_panel.map(point.to_qt())
        return PanelPoint(result.x(), result.y())


class LayerCoordinateProjection:
    """Project one layer source through its authoritative scene and panel geometry."""

    __slots__ = (
        "_layer_transform",
        "_scene",
        "_source_origin",
        "layer_id",
        "scene_id",
    )

    def __init__(
        self,
        scene: SceneCoordinateProjection,
        layer_id: uuid.UUID,
        layer_transform: LayerMapping,
        source_origin: QPoint | QPointF,
    ) -> None:
        """Capture one layer transform and its source-storage origin."""
        if not isinstance(scene, SceneCoordinateProjection):
            raise TypeError("scene must be SceneCoordinateProjection")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not isinstance(
            layer_transform,
            (
                LayerTransform,
                ProjectiveLayerTransform,
                PiecewiseLayerTransform,
                BilinearLayerTransform,
            ),
        ):
            raise TypeError("layer_transform must be a layer mapping")
        if not isinstance(source_origin, (QPoint, QPointF)):
            raise TypeError("source_origin must be QPoint or QPointF")
        self.scene_id = scene.scene_id
        self.layer_id = layer_id
        self._scene = scene
        self._layer_transform = layer_transform
        self._source_origin = QPointF(source_origin)

    def panel_to_source(self, point: PanelPoint) -> LayerSourcePoint | None:
        """Project a logical panel point into zero-origin layer-source space."""
        scene_point = self._scene.panel_to_scene(point)
        return None if scene_point is None else self.scene_to_source(scene_point)

    def panel_to_local(self, point: PanelPoint) -> LayerLocalPoint | None:
        """Project a logical panel point into authored layer-local space."""
        scene_point = self._scene.panel_to_scene(point)
        return None if scene_point is None else self.scene_to_local(scene_point)

    def source_to_panel(self, point: LayerSourcePoint) -> PanelPoint | None:
        """Project a layer-source point into logical panel coordinates."""
        scene_point = self.source_to_scene(point)
        return None if scene_point is None else self._scene.scene_to_panel(scene_point)

    def local_to_panel(self, point: LayerLocalPoint) -> PanelPoint | None:
        """Project an authored layer-local point into logical panel coordinates."""
        scene_point = self.local_to_scene(point)
        return None if scene_point is None else self._scene.scene_to_panel(scene_point)

    def scene_to_source(self, point: ScenePoint) -> LayerSourcePoint | None:
        """Project an absolute scene point into zero-origin layer-source space."""
        local = self.scene_to_local(point)
        return None if local is None else self.local_to_source(local)

    def source_to_scene(self, point: LayerSourcePoint) -> ScenePoint | None:
        """Project a zero-origin layer-source point into absolute scene space."""
        local = self.source_to_local(point)
        return None if local is None else self.local_to_scene(local)

    def scene_to_local(self, point: ScenePoint) -> LayerLocalPoint | None:
        """Project an absolute scene point into authored layer-local space."""
        if not isinstance(point, ScenePoint):
            raise TypeError("point must be ScenePoint")
        if point.scene_id != self.scene_id:
            return None
        local = self._layer_transform.inverse_map(point.to_qt())
        if local is None:
            return None
        return LayerLocalPoint(
            self.scene_id,
            self.layer_id,
            local.x(),
            local.y(),
        )

    def local_to_scene(self, point: LayerLocalPoint) -> ScenePoint | None:
        """Project an authored layer-local point into absolute scene space."""
        if not isinstance(point, LayerLocalPoint):
            raise TypeError("point must be LayerLocalPoint")
        if point.scene_id != self.scene_id or point.layer_id != self.layer_id:
            return None
        try:
            result = self._layer_transform.map_point(point.to_qt())
        except ValueError:
            if isinstance(
                self._layer_transform,
                (PiecewiseLayerTransform, BilinearLayerTransform),
            ):
                return None
            raise
        return ScenePoint(self.scene_id, result.x(), result.y())

    def local_to_source(self, point: LayerLocalPoint) -> LayerSourcePoint | None:
        """Convert authored layer-local coordinates into zero-origin source space."""
        if not isinstance(point, LayerLocalPoint):
            raise TypeError("point must be LayerLocalPoint")
        if point.scene_id != self.scene_id or point.layer_id != self.layer_id:
            return None
        return LayerSourcePoint(
            self.scene_id,
            self.layer_id,
            point.x - self._source_origin.x(),
            point.y - self._source_origin.y(),
        )

    def source_to_local(self, point: LayerSourcePoint) -> LayerLocalPoint | None:
        """Convert zero-origin source coordinates into authored layer-local space."""
        if not isinstance(point, LayerSourcePoint):
            raise TypeError("point must be LayerSourcePoint")
        if point.scene_id != self.scene_id or point.layer_id != self.layer_id:
            return None
        return LayerLocalPoint(
            self.scene_id,
            self.layer_id,
            point.x + self._source_origin.x(),
            point.y + self._source_origin.y(),
        )


class SceneCoordinateSystem:
    """Own typed current-frame projection for one QPane rendering view."""

    def __init__(
        self,
        *,
        scene_projection: Callable[[], SceneCoordinateProjection | None],
        layer_projection: Callable[
            [uuid.UUID, uuid.UUID], LayerCoordinateProjection | None
        ],
    ) -> None:
        """Bind focused projection resolvers supplied by the rendering presenter."""
        self._scene_projection = scene_projection
        self._layer_projection = layer_projection

    def panel_to_scene(self, point: PanelPoint) -> ScenePoint | None:
        """Project a panel point into the active scene."""
        if not isinstance(point, PanelPoint):
            raise TypeError("point must be PanelPoint")
        projection = self._scene_projection()
        return None if projection is None else projection.panel_to_scene(point)

    def scene_to_panel(self, point: ScenePoint) -> PanelPoint | None:
        """Project an identified scene point into the current panel."""
        if not isinstance(point, ScenePoint):
            raise TypeError("point must be ScenePoint")
        projection = self._scene_projection()
        return None if projection is None else projection.scene_to_panel(point)

    def panel_to_layer_source(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        point: PanelPoint,
    ) -> LayerSourcePoint | None:
        """Project a panel point into one identified layer's source space."""
        if not isinstance(point, PanelPoint):
            raise TypeError("point must be PanelPoint")
        projection = self._layer_projection(scene_id, layer_id)
        return None if projection is None else projection.panel_to_source(point)

    def scene_to_layer_source(
        self,
        point: ScenePoint,
        layer_id: uuid.UUID,
    ) -> LayerSourcePoint | None:
        """Project an identified scene point into one layer's source space."""
        if not isinstance(point, ScenePoint):
            raise TypeError("point must be ScenePoint")
        projection = self._layer_projection(point.scene_id, layer_id)
        return None if projection is None else projection.scene_to_source(point)

    def panel_to_layer_local(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        point: PanelPoint,
    ) -> LayerLocalPoint | None:
        """Project a panel point into one identified layer's local space."""
        if not isinstance(point, PanelPoint):
            raise TypeError("point must be PanelPoint")
        projection = self._layer_projection(scene_id, layer_id)
        return None if projection is None else projection.panel_to_local(point)

    def scene_to_layer_local(
        self,
        point: ScenePoint,
        layer_id: uuid.UUID,
    ) -> LayerLocalPoint | None:
        """Project an identified scene point into one layer's local space."""
        if not isinstance(point, ScenePoint):
            raise TypeError("point must be ScenePoint")
        projection = self._layer_projection(point.scene_id, layer_id)
        return None if projection is None else projection.scene_to_local(point)

    def layer_source_to_scene(
        self,
        point: LayerSourcePoint,
    ) -> ScenePoint | None:
        """Project an identified layer-source point into its scene."""
        if not isinstance(point, LayerSourcePoint):
            raise TypeError("point must be LayerSourcePoint")
        projection = self._layer_projection(point.scene_id, point.layer_id)
        return None if projection is None else projection.source_to_scene(point)

    def layer_source_to_panel(
        self,
        point: LayerSourcePoint,
    ) -> PanelPoint | None:
        """Project an identified layer-source point into the current panel."""
        if not isinstance(point, LayerSourcePoint):
            raise TypeError("point must be LayerSourcePoint")
        projection = self._layer_projection(point.scene_id, point.layer_id)
        return None if projection is None else projection.source_to_panel(point)

    def layer_local_to_scene(
        self,
        point: LayerLocalPoint,
    ) -> ScenePoint | None:
        """Project an identified layer-local point into its scene."""
        if not isinstance(point, LayerLocalPoint):
            raise TypeError("point must be LayerLocalPoint")
        projection = self._layer_projection(point.scene_id, point.layer_id)
        return None if projection is None else projection.local_to_scene(point)

    def layer_local_to_panel(
        self,
        point: LayerLocalPoint,
    ) -> PanelPoint | None:
        """Project an identified layer-local point into the current panel."""
        if not isinstance(point, LayerLocalPoint):
            raise TypeError("point must be LayerLocalPoint")
        projection = self._layer_projection(point.scene_id, point.layer_id)
        return None if projection is None else projection.local_to_panel(point)

    def layer_local_to_source(
        self,
        point: LayerLocalPoint,
    ) -> LayerSourcePoint | None:
        """Convert an identified layer-local point into source space."""
        if not isinstance(point, LayerLocalPoint):
            raise TypeError("point must be LayerLocalPoint")
        projection = self._layer_projection(point.scene_id, point.layer_id)
        return None if projection is None else projection.local_to_source(point)

    def layer_source_to_local(
        self,
        point: LayerSourcePoint,
    ) -> LayerLocalPoint | None:
        """Convert an identified layer-source point into local space."""
        if not isinstance(point, LayerSourcePoint):
            raise TypeError("point must be LayerSourcePoint")
        projection = self._layer_projection(point.scene_id, point.layer_id)
        return None if projection is None else projection.source_to_local(point)


def _validate_coordinates(x: float, y: float) -> None:
    """Reject non-finite coordinate components."""
    if not math.isfinite(float(x)) or not math.isfinite(float(y)):
        raise ValueError("coordinate components must be finite")
