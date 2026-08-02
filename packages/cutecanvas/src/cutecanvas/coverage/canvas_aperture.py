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

"""Constrain retained coverage authorship to the composition canvas."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainterPath, QTransform
from qpane.sdk.scene import LayerTransform, SceneDescriptor
from qpane.sdk.vector import object_path

from .document import CoverageItem, VectorCoverageItem
from .path_conversion import retained_vector_path


class CoverageCanvasAperture:
    """Own canvas clipping and presentation for retained coverage shapes."""

    def __init__(
        self,
        *,
        active_scene: Callable[[], SceneDescriptor | None],
        panel_to_scene: Callable[[QPointF], QPointF | None],
        target_to_panel: Callable[[QPointF], QPointF | None],
        target_aperture_path: Callable[[], QPainterPath | None] | None = None,
    ) -> None:
        """Bind the scene canvas and one coverage target coordinate domain."""
        self._active_scene = active_scene
        self._panel_to_scene = panel_to_scene
        self._target_to_panel = target_to_panel
        self._target_aperture_path = (
            self._scene_aperture_path
            if target_aperture_path is None
            else target_aperture_path
        )
        self._scene_path_key: tuple[object, ...] | None = None
        self._scene_path: QPainterPath | None = None

    def contains_panel_point(self, point: QPointF) -> bool:
        """Return whether a panel point lies inside the composition canvas."""
        scene = self._active_scene()
        scene_point = self._panel_to_scene(point)
        if scene is None or scene_point is None:
            return False
        bounds = scene.bounds
        return (
            bounds.x <= scene_point.x() < bounds.x + bounds.width
            and bounds.y <= scene_point.y() < bounds.y + bounds.height
        )

    def constrain_item(self, item: CoverageItem) -> CoverageItem | None:
        """Clip one retained vector item to the canvas in target coordinates."""
        if not isinstance(item, VectorCoverageItem):
            return item
        aperture = self._target_aperture_path()
        if aperture is None:
            return None
        path = item.transform.to_qtransform().map(object_path(item.geometry))
        if aperture.contains(path):
            return item
        geometry = retained_vector_path(
            path.intersected(aperture),
            style=item.geometry.style,
            object_id=item.geometry.object_id,
        )
        if geometry is None:
            return None
        return VectorCoverageItem(
            item.item_id,
            geometry,
            item.combine_mode,
            LayerTransform(),
            item.feather_radius,
        )

    def item_panel_path(self, item: CoverageItem) -> QPainterPath | None:
        """Project one constrained vector item's exact path into panel space."""
        if not isinstance(item, VectorCoverageItem):
            return None
        transform = self._target_to_panel_transform()
        if transform is None:
            return None
        target_path = item.transform.to_qtransform().map(object_path(item.geometry))
        return transform.map(target_path)

    def _scene_aperture_path(self) -> QPainterPath | None:
        """Return the composition rectangle in scene coordinates."""
        scene = self._active_scene()
        if scene is None:
            return None
        bounds = scene.bounds
        key = (scene.scene_id, bounds)
        if key != self._scene_path_key:
            path = QPainterPath()
            path.addRect(bounds.x, bounds.y, bounds.width, bounds.height)
            self._scene_path_key = key
            self._scene_path = path
        return None if self._scene_path is None else QPainterPath(self._scene_path)

    def _target_to_panel_transform(self) -> QTransform | None:
        """Resolve the target domain's current affine panel projection."""
        origin = self._target_to_panel(QPointF())
        unit_x = self._target_to_panel(QPointF(1.0, 0.0))
        unit_y = self._target_to_panel(QPointF(0.0, 1.0))
        if origin is None or unit_x is None or unit_y is None:
            return None
        return QTransform(
            unit_x.x() - origin.x(),
            unit_x.y() - origin.y(),
            unit_y.x() - origin.x(),
            unit_y.y() - origin.y(),
            origin.x(),
            origin.y(),
        )
