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

"""Project scene and layer geometry into one viewport frame."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QTransform

from ..scene.affine import LayerTransform
from ..scene.model import LayerDescriptor, SceneDescriptor
from .frame_geometry import RenderFrameGeometry
from .viewport import Viewport


class SceneFrameProjector:
    """Own viewport transforms shared by render contribution planners."""

    def __init__(self, viewport: Viewport) -> None:
        """Capture the authoritative viewport transform owner."""
        self._viewport = viewport

    def scene_to_panel(
        self,
        scene: SceneDescriptor,
        frame: RenderFrameGeometry,
    ) -> QTransform:
        """Return the scene-local to panel transform for one frame."""
        scene_size = QSize(
            max(1, round(scene.bounds.width)),
            max(1, round(scene.bounds.height)),
        )
        return self._viewport.get_transform(
            scene_size,
            1.0,
            pan_override=frame.current_pan,
            content_snapshot=frame.content_snapshot,
        )

    def layer_to_panel(
        self,
        *,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        source_size: QSize,
        frame: RenderFrameGeometry,
    ) -> QTransform:
        """Map render-source pixels through exact layer geometry into the panel."""
        layer_transform = layer.transform
        if layer_transform is None or source_size.isEmpty():
            return QTransform()
        raster_bounds = layer.raster_bounds
        if raster_bounds is None:
            image_to_local = LayerTransform()
        else:
            image_to_local = LayerTransform(
                m11=raster_bounds.width / source_size.width(),
                m22=raster_bounds.height / source_size.height(),
                dx=float(raster_bounds.x),
                dy=float(raster_bounds.y),
            )
        scene_relative = image_to_local.followed_by(layer_transform).translated(
            -scene.bounds.x,
            -scene.bounds.y,
        )
        return scene_relative.to_qtransform() * self.scene_to_panel(scene, frame)
