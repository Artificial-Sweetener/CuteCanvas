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

"""Select the single affine base raster eligible for direct presentation."""

from __future__ import annotations

from math import isclose

from PySide6.QtGui import QTransform

from ..scene.render_plan import RasterLayerRenderItem, SceneRenderPlan


def base_only_raster_item(plan: SceneRenderPlan) -> RasterLayerRenderItem | None:
    """Return the sole ordinary affine raster eligible for direct painting."""
    if plan.transient_raster is not None or plan.presentation_effects:
        return None
    if len(plan.render_items) != 1:
        return None
    item = plan.render_items[0]
    if not isinstance(item, RasterLayerRenderItem):
        return None
    if item is not plan.base_raster_item:
        return None
    if not item.descriptor.visible:
        return None
    if not isclose(item.descriptor.opacity, 1.0, rel_tol=0.0, abs_tol=1e-9):
        return None
    if item.clip is not None or item.effect_clip_path is not None:
        return None
    if not isinstance(item.transform, QTransform):
        return None
    if item.placement != plan.scene_bounds or item.source_image.isNull():
        return None
    return item


__all__ = ["base_only_raster_item"]
