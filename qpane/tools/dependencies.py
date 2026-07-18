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

"""Typed dependency bundle that tools receive during activation."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, TypedDict

from PySide6.QtCore import QPoint, QPointF, QRect
from PySide6.QtGui import QColor, QPen

if TYPE_CHECKING:
    from qpane.rendering import ViewportZoomMode
    from qpane.rendering.coordinates import PanelHitTest


class ToolDependencies(TypedDict, total=False):
    """Optional dependency bundle forwarded to tool.activate.

    Each entry supplies a callable collaborator fetched lazily from the qpane view
    so individual tools can remain decoupled from widget internals. Some tools use
    ``get_native_zoom`` and ``get_fit_zoom`` to snap wheel steps to 1:1 or fit.
    """

    is_alt_held: Callable[[], bool]
    is_shift_held: Callable[[], bool]
    is_pan_zoom_locked: Callable[[], bool]
    is_image_null: Callable[[], bool]
    is_drag_out_allowed: Callable[[], bool]
    can_pan: Callable[[], bool]
    get_pan: Callable[[], QPointF]
    get_zoom: Callable[[], float]
    get_native_zoom: Callable[[], float]
    get_fit_zoom: Callable[[], float]
    get_zoom_mode: Callable[[], ViewportZoomMode]
    set_zoom_fit: Callable[[], None]
    set_zoom_fit_interpolated: Callable[[], None]
    set_zoom_one_to_one: Callable[[QPoint | None], None]
    set_zoom_one_to_one_interpolated: Callable[[QPoint | None], None]
    get_brush_size: Callable[[], int]
    get_preview_pens: Callable[[], tuple[QPen, QPen]]
    get_brush_increment: Callable[[], int]
    panel_hit_test: Callable[[QPoint], PanelHitTest | None]
    panel_hit_test_precise: Callable[[QPointF], PanelHitTest | None]
    panel_to_content_point: Callable[[QPoint], QPoint | None]
    image_to_panel_point: Callable[[QPoint | QPointF], QPointF | None]
    panel_to_active_mask_point: Callable[[QPoint | QPointF], QPointF | None]
    active_mask_to_panel_point: Callable[[QPoint | QPointF], QPointF | None]
    is_point_in_widget: Callable[[QPoint], bool]
    get_image_rect: Callable[[], QRect]
    get_dpr: Callable[[], float]
    get_min_selection_size: Callable[[], int]
    get_active_mask_color: Callable[[], QColor | None]
    request_overlay_update: Callable[[QRect], None]
    begin_layer_move: Callable[[QPointF], bool]
    update_layer_move: Callable[[QPointF], bool]
    finish_layer_move: Callable[[QPointF], bool]
    cancel_layer_move: Callable[[], bool]
    get_pen_pressure_min_ratio: Callable[[], float]
    get_pen_pressure_gamma: Callable[[], float]
    get_pen_pressure_enabled: Callable[[], bool]
