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
"""Capture and project viewport-independent normalized inspection geometry."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QSizeF

from .model import (
    InspectionRegion,
    InspectionTarget,
    InspectionViewState,
    InspectionZoomMode,
    ProjectedViewport,
)


def capture_inspection(
    target: InspectionTarget,
    viewport_size: QSizeF,
    *,
    zoom: float,
    pan: QPointF,
    zoom_mode: InspectionZoomMode = InspectionZoomMode.CUSTOM,
) -> InspectionViewState:
    """Capture one viewport as normalized target-independent inspection.

    Region spans describe normalized target distance per physical display
    pixel. They deliberately exclude viewport extent: resizing a viewport
    reveals more or less content without changing the user's image scale.

    Args:
        target: Intrinsic target geometry being displayed.
        viewport_size: Physical viewport size in device pixels.
        zoom: Physical device pixels per target coordinate unit.
        pan: Physical viewport displacement from centered target placement.
        zoom_mode: Local mode that produced the transform.

    Returns:
        Detached normalized center and display-scale state.

    Raises:
        ValueError: If viewport or zoom geometry is invalid.
    """
    size = QSizeF(viewport_size)
    current_pan = QPointF(pan)
    if (
        size.width() <= 0.0
        or size.height() <= 0.0
        or not math.isfinite(float(zoom))
        or zoom <= 0.0
    ):
        raise ValueError("capture requires positive viewport dimensions and zoom")
    bounds = target.bounds
    center_scene_x = bounds.center().x() - current_pan.x() / zoom
    center_scene_y = bounds.center().y() - current_pan.y() / zoom
    region = InspectionRegion(
        center_x=(center_scene_x - bounds.left()) / bounds.width(),
        center_y=(center_scene_y - bounds.top()) / bounds.height(),
        span_x=1.0 / (bounds.width() * zoom),
        span_y=1.0 / (bounds.height() * zoom),
    )
    return InspectionViewState(region, InspectionZoomMode(zoom_mode))


def project_inspection(
    target: InspectionTarget,
    viewport_size: QSizeF,
    state: InspectionViewState,
) -> ProjectedViewport:
    """Project normalized inspection state into one target-local viewport.

    The target-relative display scale is contained when target aspect ratios
    differ. Viewport dimensions validate the receiving surface but never alter
    custom scale; resizing reveals more or less content around the same center.

    Args:
        target: Intrinsic target geometry receiving the state.
        viewport_size: Physical viewport size in device pixels.
        state: Normalized region and target-local mode.

    Returns:
        Positive zoom and physical pan for the receiving viewport.

    Raises:
        ValueError: If viewport dimensions are not positive.
    """
    size = QSizeF(viewport_size)
    if size.width() <= 0.0 or size.height() <= 0.0:
        raise ValueError("projection requires positive viewport dimensions")
    bounds = target.bounds
    region = state.region
    zoom_x = 1.0 / (bounds.width() * region.span_x)
    zoom_y = 1.0 / (bounds.height() * region.span_y)
    zoom = min(zoom_x, zoom_y)
    target_center = QPointF(
        bounds.left() + bounds.width() * region.center_x,
        bounds.top() + bounds.height() * region.center_y,
    )
    pan = QPointF(
        (bounds.center().x() - target_center.x()) * zoom,
        (bounds.center().y() - target_center.y()) * zoom,
    )
    return ProjectedViewport(zoom, pan, state.zoom_mode)
