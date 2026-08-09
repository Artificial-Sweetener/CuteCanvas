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

"""Exact finite viewport clipping for supported source mappings."""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainterPath, QTransform

from ..scene.bilinear import BilinearLayerTransform
from ..scene.mapping import LayerMapping
from ..scene.model import LayerPlacement
from ..scene.piecewise import PiecewiseLayerTransform
from ..scene.raster import RasterBounds
from .panel_mapping import PanelLayerMapping, PiecewisePanelMapping


def visible_source_rect(
    source_to_panel: PanelLayerMapping,
    panel_rect: QRectF,
    source_rect: QRectF,
) -> QRectF:
    """Return conservative local bounds contributing to one panel rectangle."""
    if not isinstance(source_to_panel, (QTransform, PiecewisePanelMapping)):
        raise TypeError("source_to_panel must be a panel layer mapping")
    if isinstance(source_to_panel, PiecewisePanelMapping):
        return _visible_piecewise_source_rect(
            source_to_panel,
            panel_rect,
            source_rect,
        )
    panel = QRectF(panel_rect).normalized()
    source = QRectF(source_rect).normalized()
    if panel.isEmpty() or source.isEmpty():
        return QRectF()
    panel_to_source, invertible = source_to_panel.inverted()
    if not invertible:
        return QRectF()
    if source_to_panel.isAffine():
        return panel_to_source.mapRect(panel).intersected(source)
    source_path = QPainterPath()
    source_path.addRect(source)
    panel_path = QPainterPath()
    panel_path.addRect(panel)
    visible_panel = source_to_panel.map(source_path).intersected(panel_path)
    if visible_panel.isEmpty():
        return QRectF()
    return panel_to_source.map(visible_panel).boundingRect().intersected(source)


def _visible_piecewise_source_rect(
    mapping: PiecewisePanelMapping,
    panel_rect: QRectF,
    source_rect: QRectF,
) -> QRectF:
    """Unite conservative source demand without polygon-boolean cancellation."""
    panel = QPainterPath()
    panel.addRect(QRectF(panel_rect).normalized())
    visible = QRectF()
    for patch in mapping.patches:
        contribution = panel.intersected(patch.panel_path)
        if contribution.isEmpty():
            continue
        inverse, invertible = patch.transform.inverted()
        if not invertible:
            return QRectF()
        bounds = inverse.map(contribution).boundingRect()
        visible = bounds if visible.isEmpty() else visible.united(bounds)
    return visible.intersected(QRectF(source_rect).normalized())


def visible_raster_bounds(
    mapping: QTransform,
    visible_scene_rect: QRectF,
    raster_bounds: RasterBounds,
) -> RasterBounds | None:
    """Return conservative integer raster bounds visible through one mapping."""
    source_rect = QRectF(
        raster_bounds.x,
        raster_bounds.y,
        raster_bounds.width,
        raster_bounds.height,
    )
    visible = visible_source_rect(
        mapping, visible_scene_rect, source_rect
    ).toAlignedRect()
    if visible.isEmpty():
        return None
    return raster_bounds.intersection(RasterBounds.from_qrect(visible))


def visible_scene_raster_bounds(
    mapping: LayerMapping,
    scene_bounds: LayerPlacement,
    visible_scene_rect: QRectF,
    raster_bounds: RasterBounds,
) -> RasterBounds | None:
    """Return raster bounds visible inside both the scene and viewport."""
    scene_rect = QRectF(
        scene_bounds.x,
        scene_bounds.y,
        scene_bounds.width,
        scene_bounds.height,
    ).intersected(visible_scene_rect)
    if scene_rect.isEmpty():
        return None
    if isinstance(mapping, (PiecewiseLayerTransform, BilinearLayerTransform)):
        visible_local = mapping.inverse_map_rect(scene_rect)
        if visible_local.isEmpty():
            return None
        return raster_bounds.intersection(
            RasterBounds.from_qrect(visible_local.toAlignedRect())
        )
    return visible_raster_bounds(mapping.to_qtransform(), scene_rect, raster_bounds)


__all__ = [
    "visible_raster_bounds",
    "visible_scene_raster_bounds",
    "visible_source_rect",
]
