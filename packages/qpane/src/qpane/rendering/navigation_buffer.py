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
"""Transform a settled backing frame for immediate viewport navigation."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPainter, QRegion, QTransform

from ..scene.render_plan import SceneRenderPlan


@dataclass(frozen=True, slots=True)
class NavigationBufferResult:
    """Return target pixels plus physical regions not covered by the old frame."""

    exposed_region: QRegion

    def __post_init__(self) -> None:
        """Detach mutable region data from the transformation operation."""
        object.__setattr__(self, "exposed_region", QRegion(self.exposed_region))


def navigation_buffer_transform(
    previous_plan: SceneRenderPlan,
    target_plan: SceneRenderPlan,
    *,
    overscan: int,
    device_pixel_ratio: float = 1.0,
) -> QTransform:
    """Return the widget-logical transform between two navigation plans."""
    if previous_plan.zoom <= 0.0 or target_plan.zoom <= 0.0:
        raise ValueError("navigation plans must have positive zoom")
    if device_pixel_ratio <= 0.0:
        raise ValueError("device_pixel_ratio must be positive")
    scale = target_plan.zoom / previous_plan.zoom
    previous_center = QRectF(previous_plan.qpane_rect).center()
    target_center = QRectF(target_plan.qpane_rect).center()
    margin = QPointF(
        float(overscan) / device_pixel_ratio,
        float(overscan) / device_pixel_ratio,
    )
    previous_pan = previous_plan.current_pan / device_pixel_ratio
    target_pan = target_plan.current_pan / device_pixel_ratio
    previous_anchor = margin + previous_center + previous_pan
    target_anchor = margin + target_center + target_pan
    transform = QTransform()
    transform.translate(target_anchor.x(), target_anchor.y())
    transform.scale(scale, scale)
    transform.translate(-previous_anchor.x(), -previous_anchor.y())
    return transform


def transform_navigation_buffer(
    target: QImage,
    source: QImage,
    *,
    previous_plan: SceneRenderPlan,
    target_plan: SceneRenderPlan,
    overscan: int,
    viewport_size: QSize,
    source_guard_valid: bool,
) -> NavigationBufferResult:
    """Transform only visible pixels while retaining offscreen guard storage."""
    if target.size() != source.size():
        raise ValueError("navigation buffers must have matching dimensions")
    if previous_plan.zoom <= 0.0 or target_plan.zoom <= 0.0:
        raise ValueError("navigation plans must have positive zoom")
    transform = navigation_buffer_transform(
        previous_plan,
        target_plan,
        overscan=overscan,
        device_pixel_ratio=source.devicePixelRatio(),
    )
    target_rect = QRect(
        overscan,
        overscan,
        viewport_size.width(),
        viewport_size.height(),
    ).intersected(target.rect())
    source_rect = source.rect() if source_guard_valid else target_rect
    painter = QPainter(target)
    try:
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.setClipRect(target_rect)
        painter.fillRect(target_rect, Qt.GlobalColor.transparent)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setTransform(transform)
        painter.drawImage(0, 0, source)
    finally:
        painter.end()
    covered = transform.mapRect(QRectF(source_rect)).toAlignedRect()
    exposed = QRegion(target_rect).subtracted(QRegion(covered))
    return NavigationBufferResult(exposed)
