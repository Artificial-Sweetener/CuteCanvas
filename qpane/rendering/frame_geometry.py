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

"""Viewport-dependent geometry shared by render contribution planners."""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose

from PySide6.QtCore import QPointF, QRect, QRectF

from ..scene.model import SceneDescriptor
from ..scene.render_plan import SceneContentSnapshot


@dataclass(frozen=True, slots=True)
class RenderFrameGeometry:
    """Detached viewport geometry used while planning one rendered frame."""

    content_snapshot: SceneContentSnapshot
    zoom: float
    native_zoom: float
    current_pan: QPointF
    qpane_rect: QRect
    physical_viewport_rect: QRectF
    visible_scene_rect: QRectF
    debug_draw_tile_grid: bool
    tile_size: int
    tile_overlap: int

    def __post_init__(self) -> None:
        """Detach mutable Qt values from caller-owned frame inputs."""
        object.__setattr__(self, "current_pan", QPointF(self.current_pan))
        object.__setattr__(self, "qpane_rect", QRect(self.qpane_rect))
        object.__setattr__(
            self,
            "physical_viewport_rect",
            QRectF(self.physical_viewport_rect),
        )
        object.__setattr__(self, "visible_scene_rect", QRectF(self.visible_scene_rect))


def visible_scene_rect(
    *,
    scene: SceneDescriptor,
    zoom: float,
    current_pan: QPointF,
    physical_viewport_rect: QRectF,
) -> QRectF:
    """Return the scene-space rectangle visible through the viewport."""
    safe_zoom = zoom if not isclose(zoom, 0.0) else 1.0
    viewport_center = QPointF(physical_viewport_rect.center())
    scene_center = QPointF(
        scene.bounds.x + scene.bounds.width / 2.0,
        scene.bounds.y + scene.bounds.height / 2.0,
    )
    top_left_scene = (
        physical_viewport_rect.topLeft() - viewport_center - current_pan
    ) / safe_zoom + scene_center
    bottom_right_scene = (
        physical_viewport_rect.bottomRight() - viewport_center - current_pan
    ) / safe_zoom + scene_center
    return QRectF(top_left_scene, bottom_right_scene).normalized()
