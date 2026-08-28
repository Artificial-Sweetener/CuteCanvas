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
from .storage_allocation import checked_painter


@dataclass(frozen=True, slots=True)
class NavigationBufferResult:
    """Return target pixels plus physical regions not covered by the old frame."""

    exposed_region: QRegion

    def __post_init__(self) -> None:
        """Detach mutable region data from the transformation operation."""
        object.__setattr__(self, "exposed_region", QRegion(self.exposed_region))


@dataclass(frozen=True, slots=True)
class ScrollRepairRegions:
    """Describe valid, repair, and rollback geometry after a buffer scroll."""

    translated_valid: QRegion
    repair: QRegion
    rollback: QRegion
    repair_rects: tuple[QRect, ...]

    def __post_init__(self) -> None:
        """Detach mutable Qt regions and rectangles from renderer state."""
        object.__setattr__(self, "translated_valid", QRegion(self.translated_valid))
        object.__setattr__(self, "repair", QRegion(self.repair))
        object.__setattr__(self, "rollback", QRegion(self.rollback))
        object.__setattr__(
            self,
            "repair_rects",
            tuple(QRect(rect) for rect in self.repair_rects),
        )


def scroll_repair_regions(
    surface_rect: QRect,
    valid_region: QRegion,
    *,
    dx: int,
    dy: int,
    bleed: int,
    linear_scroll: bool,
) -> ScrollRepairRegions:
    """Plan exposed-pixel repair and the minimal pre-mutation rollback journal."""
    surface_region = QRegion(surface_rect)
    translated_valid = valid_region.translated(dx, dy).intersected(surface_region)
    missing = surface_region.subtracted(translated_valid)
    repair = QRegion()
    for rect in missing:
        repair = repair.united(QRegion(rect.adjusted(-bleed, -bleed, bleed, bleed)))
    repair = repair.intersected(surface_region)
    rollback = repair.intersected(translated_valid) if linear_scroll else repair
    return ScrollRepairRegions(
        translated_valid,
        repair,
        rollback,
        tuple(QRect(rect) for rect in repair),
    )


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
    painter = checked_painter(target, "navigation buffer transfer")
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


__all__ = [
    "NavigationBufferResult",
    "ScrollRepairRegions",
    "navigation_buffer_transform",
    "scroll_repair_regions",
    "transform_navigation_buffer",
]
