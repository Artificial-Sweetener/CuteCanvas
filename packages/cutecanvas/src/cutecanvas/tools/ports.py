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

"""Focused activation ports for CuteCanvas's built-in tools."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QPointF, QRect
from PySide6.QtGui import QColor, QPainterPath, QPen

from cutecanvas.coverage import CoverageCombineMode
from qpane import CursorInteractionPort, NavigationInteractionPort

from .dependencies import ToolDependencies

if TYPE_CHECKING:
    from qpane.sdk.rendering import PanelHitTest
    from qpane.sdk.scene import TransformModifiers, TransformOperation

    from cutecanvas.coverage import CoverageItem, CoverageSnapshot
    from cutecanvas.painting.tools.brush_preview import AffineBrushPreview

    from ..editor.transform_interaction import TransformBoxPresentation


def _false() -> bool:
    """Return the inert false-valued tool default."""
    return False


def _true() -> bool:
    """Return the safe true-valued tool guard default."""
    return True


def _one() -> float:
    """Return the neutral scalar used by editor tool defaults."""
    return 1.0


def _point(
    point: QPointF,
    _suppressed: bool = False,
    _constrain: bool = False,
) -> QPointF:
    """Return a detached point for inert authoring-snap defaults."""
    return QPointF(point)


@dataclass(frozen=True, slots=True)
class AuthoringSnapPort:
    """Resolve panel-space geometry through the shared authoring session."""

    begin: Callable[[QPointF, bool], QPointF] = _point
    update: Callable[[QPointF, bool, bool], QPointF] = _point
    clear: Callable[[], bool] = _false


@dataclass(frozen=True, slots=True)
class MoveInteractionPort:
    """Dependencies used by source-neutral layer and pixel movement."""

    begin_move: Callable[[QPointF, bool], bool] = lambda _point, _copy: False
    update_move: Callable[[QPointF, bool], bool] = lambda _point, _suppress: False
    finish_move: Callable[[QPointF, bool], bool] = lambda _point, _suppress: False
    suspend_move: Callable[[], bool] = _false
    cancel_move: Callable[[], bool] = _false
    anchor_move: Callable[[], bool] = _false
    update_move_hover: Callable[[QPointF], bool] = lambda _point: False
    clear_move_hover: Callable[[], bool] = _false
    move_target_available: Callable[[], bool] = _false
    nudge_move: Callable[[int, int], bool] = lambda _x, _y: False


@dataclass(frozen=True, slots=True)
class TransformInteractionPort:
    """Dependencies used by source-neutral affine transform interaction."""

    transform_presentation: Callable[[], TransformBoxPresentation | None] = lambda: None
    begin_transform: Callable[[TransformOperation, QPointF], bool] = (
        lambda _operation, _point: False
    )
    update_transform: Callable[[QPointF, TransformModifiers], bool] = (
        lambda _point, _modifiers: False
    )
    end_transform_gesture: Callable[[QPointF, TransformModifiers], bool] = (
        lambda _point, _modifiers: False
    )
    commit_transform: Callable[[], bool] = _false
    cancel_transform: Callable[[], bool] = _false
    suspend_transform: Callable[[], bool] = _false


@dataclass(frozen=True, slots=True)
class PixelSelectionInteractionPort:
    """Dependencies used by geometric pixel-selection tools."""

    panel_to_scene_point: Callable[[QPointF], QPointF | None] = lambda _point: None
    can_select: Callable[[], bool] = _true
    commit_pixel_selection: Callable[[CoverageSnapshot, CoverageCombineMode], bool] = (
        lambda _coverage, _mode: False
    )
    commit_coverage_item: Callable[[CoverageItem], bool] = lambda _item: False
    is_shift_held: Callable[[], bool] = _false
    is_alt_held: Callable[[], bool] = _false
    default_combine_mode: CoverageCombineMode = CoverageCombineMode.REPLACE
    get_shape_feather_radius: Callable[[], float] = lambda: 0.0
    constrain_coverage_item: Callable[[CoverageItem], CoverageItem | None] = (
        lambda item: item
    )
    coverage_item_to_panel_path: (
        Callable[[CoverageItem], QPainterPath | None] | None
    ) = None
    snapping: AuthoringSnapPort = field(default_factory=AuthoringSnapPort)


@dataclass(frozen=True, slots=True)
class PaintingInteractionPort:
    """Dependencies used by the shared coverage-paint interaction."""

    is_alt_held: Callable[[], bool] = _false
    is_shift_held: Callable[[], bool] = _false
    can_paint: Callable[[], bool] = _true
    prepare_paint: Callable[[], bool] = _true
    gesture_start_allowed: Callable[[QPointF], bool] = lambda _point: True
    get_brush_size: Callable[[], int] = lambda: 20
    get_preview_pens: Callable[[], tuple[QPen, QPen]] | None = None
    panel_hit_test: Callable[[QPoint], PanelHitTest | None] | None = None
    panel_hit_test_precise: Callable[[QPointF], PanelHitTest | None] | None = None
    panel_to_content_point: Callable[[QPoint], QPoint | None] = lambda _point: None
    image_to_panel_point: Callable[[QPoint | QPointF], QPointF | None] = (
        lambda _point: None
    )
    panel_to_target_point: Callable[[QPoint | QPointF], QPointF | None] | None = None
    target_to_panel_point: Callable[[QPoint | QPointF], QPointF | None] | None = None
    is_point_in_widget: Callable[[QPoint], bool] = lambda _point: True
    get_image_rect: Callable[[], QRect] = field(default_factory=lambda: lambda: QRect())
    get_brush_increment: Callable[[], int] = lambda: 5
    get_pen_pressure_min_ratio: Callable[[], float] = lambda: 0.15
    get_pen_pressure_gamma: Callable[[], float] = _one
    get_pen_pressure_enabled: Callable[[], bool] = _true
    get_pressure_diameter: Callable[[float], float] | None = None
    get_smoothing: Callable[[], float] = lambda: 0.0
    get_zoom: Callable[[], float] = _one
    get_dpr: Callable[[], float] = _one
    get_preview_color: Callable[[], QColor | None] = lambda: None
    request_overlay_update: Callable[[QRect], None] | None = None


@dataclass(frozen=True, slots=True)
class CloneStampInteractionPort:
    """Dependencies used by Clone Stamp interaction and source feedback."""

    painting: PaintingInteractionPort = field(default_factory=PaintingInteractionPort)
    set_source_from_panel: Callable[[QPointF], bool] = lambda _point: False
    source_footprint: Callable[[float], AffineBrushPreview | None] = (
        lambda _diameter: None
    )
    source_set: Callable[[], bool] = _false


@dataclass(frozen=True, slots=True)
class PaintBucketInteractionPort:
    """Dependencies used by asynchronous target-local flood fills."""

    panel_to_target_point: Callable[[QPointF], QPointF | None] = lambda _point: None
    can_fill: Callable[[], bool] = _false
    request_fill: Callable[[QPointF, CoverageCombineMode], bool] = (
        lambda _point, _mode: False
    )
    cancel_fill: Callable[[], bool] = _false
    is_shift_held: Callable[[], bool] = _false
    is_alt_held: Callable[[], bool] = _false


@dataclass(frozen=True, slots=True)
class SmartSelectionInteractionPort:
    """Dependencies used by the factory SAM selection interaction."""

    is_alt_held: Callable[[], bool] = _false
    get_dpr: Callable[[], float] = _one
    panel_to_content_point: Callable[[QPoint], QPoint | None] = lambda _point: None
    image_to_panel_point: Callable[[QPoint | QPointF], QPointF | None] = (
        lambda _point: None
    )
    panel_to_active_mask_point: Callable[[QPoint | QPointF], QPointF | None] | None = (
        None
    )
    active_mask_to_panel_point: Callable[[QPoint | QPointF], QPointF | None] | None = (
        None
    )
    get_min_selection_size: Callable[[], int] = lambda: 5
    get_active_mask_color: Callable[[], QColor | None] = lambda: None


@dataclass(frozen=True, slots=True)
class VectorInteractionPort:
    """Dependencies used by semantic vector shape and path gestures."""

    panel_to_source: Callable[[QPointF], QPointF | None] = lambda _point: None
    commit_shape: Callable[[QPointF, QPointF], object | None] = (
        lambda _begin, _end: None
    )
    commit_path: Callable[[tuple[QPointF, ...], bool], object | None] = (
        lambda _points, _closed: None
    )
    shape_is_ellipse: Callable[[], bool] = _false
    snapping: AuthoringSnapPort = field(default_factory=AuthoringSnapPort)


@dataclass(frozen=True, slots=True)
class VectorNodeInteractionPort:
    """Dependencies used by direct vector-node selection and dragging."""

    begin: Callable[[QPointF], bool] = lambda _point: False
    update: Callable[[QPointF], bool] = lambda _point: False
    finish: Callable[[QPointF], bool] = lambda _point: False
    cancel: Callable[[], bool] = _false
    overlay_state: Callable[[], object | None] = lambda: None


@dataclass(frozen=True, slots=True)
class VectorTextInteractionPort:
    """Dependencies used by in-place semantic text interaction."""

    begin_at: Callable[[QPointF], bool] = lambda _point: False
    insert: Callable[[str], bool] = lambda _value: False
    backspace: Callable[[], bool] = _false
    delete: Callable[[], bool] = _false
    move_cursor: Callable[[int], bool] = lambda _offset: False
    move_cursor_to: Callable[[int], bool] = lambda _cursor: False
    text_length: Callable[[], int] = lambda: 0
    commit: Callable[[], bool] = _false
    cancel: Callable[[], bool] = _false
    active: Callable[[], bool] = _false
    overlay_state: Callable[[], object | None] = lambda: None


BuiltInToolPort = (
    CursorInteractionPort
    | NavigationInteractionPort
    | MoveInteractionPort
    | TransformInteractionPort
    | PixelSelectionInteractionPort
    | PaintingInteractionPort
    | CloneStampInteractionPort
    | PaintBucketInteractionPort
    | SmartSelectionInteractionPort
    | VectorInteractionPort
    | VectorNodeInteractionPort
    | VectorTextInteractionPort
)


@dataclass(frozen=True, slots=True)
class ToolActivationPorts:
    """Focused built-in ports plus the frozen custom-tool compatibility mapping."""

    cursor: CursorInteractionPort = field(default_factory=CursorInteractionPort)
    navigation: NavigationInteractionPort = field(
        default_factory=NavigationInteractionPort
    )
    movement: MoveInteractionPort = field(default_factory=MoveInteractionPort)
    transform: TransformInteractionPort = field(
        default_factory=TransformInteractionPort
    )
    pixel_selection: PixelSelectionInteractionPort = field(
        default_factory=PixelSelectionInteractionPort
    )
    coverage_shapes: PixelSelectionInteractionPort = field(
        default_factory=PixelSelectionInteractionPort
    )
    painting: PaintingInteractionPort = field(default_factory=PaintingInteractionPort)
    clone_stamp: CloneStampInteractionPort = field(
        default_factory=CloneStampInteractionPort
    )
    paint_bucket: PaintBucketInteractionPort = field(
        default_factory=PaintBucketInteractionPort
    )
    smart_selection: SmartSelectionInteractionPort = field(
        default_factory=SmartSelectionInteractionPort
    )
    domain_ports: Mapping[str, BuiltInToolPort] = field(default_factory=dict)
    extension: ToolDependencies = field(default_factory=ToolDependencies)

    def for_mode(self, mode: str) -> BuiltInToolPort | ToolDependencies:
        """Return the one activation boundary associated with a tool mode."""
        ports: dict[str, BuiltInToolPort] = {
            "cursor": self.cursor,
            "panzoom": self.navigation,
            "move": self.movement,
            "transform": self.transform,
            "select-rectangle": self.pixel_selection,
            "select-ellipse": self.pixel_selection,
            "select-lasso": self.pixel_selection,
            "mask-rectangle": self.coverage_shapes,
            "mask-ellipse": self.coverage_shapes,
            "mask-lasso": self.coverage_shapes,
            "draw-brush": self.painting,
            "clone-stamp": self.clone_stamp,
            "paint-bucket": self.paint_bucket,
            "smart-select": self.smart_selection,
        }
        return ports.get(mode, self.domain_ports.get(mode, self.extension))


def tool_activation_ports(
    *,
    cursor: CursorInteractionPort,
    navigation: NavigationInteractionPort,
    movement: MoveInteractionPort,
    transform: TransformInteractionPort,
    pixel_selection: PixelSelectionInteractionPort,
    painting: PaintingInteractionPort,
    clone_stamp: CloneStampInteractionPort | None = None,
    paint_bucket: PaintBucketInteractionPort | None = None,
    smart_selection: SmartSelectionInteractionPort,
    coverage_shapes: PixelSelectionInteractionPort | None = None,
    domain_ports: Mapping[str, BuiltInToolPort] | None = None,
) -> ToolActivationPorts:
    """Build focused ports plus the frozen custom-tool mapping projection."""
    extension = ToolDependencies(
        is_alt_held=painting.is_alt_held,
        is_shift_held=painting.is_shift_held,
        is_pan_zoom_locked=navigation.is_navigation_locked,
        is_image_null=navigation.is_content_empty,
        is_drag_out_allowed=navigation.is_drag_out_allowed,
        can_pan=navigation.can_pan,
        get_pan=navigation.get_pan,
        get_zoom=navigation.get_zoom,
        get_native_zoom=navigation.get_native_zoom,
        get_fit_zoom=navigation.get_fit_zoom,
        set_zoom_fit=navigation.set_zoom_fit,
        set_zoom_one_to_one=navigation.set_zoom_one_to_one,
        get_dpr=navigation.get_dpr,
        get_brush_size=painting.get_brush_size,
        get_brush_increment=painting.get_brush_increment,
        panel_hit_test=painting.panel_hit_test,
        panel_hit_test_precise=painting.panel_hit_test_precise,
        panel_to_content_point=painting.panel_to_content_point,
        panel_to_scene_point=pixel_selection.panel_to_scene_point,
        image_to_panel_point=painting.image_to_panel_point,
        panel_to_active_mask_point=painting.panel_to_target_point,
        active_mask_to_panel_point=painting.target_to_panel_point,
        is_point_in_widget=painting.is_point_in_widget,
        get_image_rect=painting.get_image_rect,
        get_min_selection_size=smart_selection.get_min_selection_size,
        get_active_mask_color=painting.get_preview_color,
        begin_move=movement.begin_move,
        update_move=lambda point: movement.update_move(point, False),
        finish_move=lambda point: movement.finish_move(point, False),
        suspend_move=movement.suspend_move,
        cancel_move=movement.cancel_move,
        anchor_move=movement.anchor_move,
        update_move_hover=movement.update_move_hover,
        clear_move_hover=movement.clear_move_hover,
        move_target_available=movement.move_target_available,
        nudge_move=movement.nudge_move,
        commit_pixel_selection=pixel_selection.commit_pixel_selection,
        get_pen_pressure_min_ratio=painting.get_pen_pressure_min_ratio,
        get_pen_pressure_gamma=painting.get_pen_pressure_gamma,
        get_pen_pressure_enabled=painting.get_pen_pressure_enabled,
    )
    if navigation.get_zoom_mode is not None:
        extension["get_zoom_mode"] = navigation.get_zoom_mode
    if navigation.set_zoom_fit_interpolated is not None:
        extension["set_zoom_fit_interpolated"] = navigation.set_zoom_fit_interpolated
    if navigation.set_zoom_one_to_one_interpolated is not None:
        extension["set_zoom_one_to_one_interpolated"] = (
            navigation.set_zoom_one_to_one_interpolated
        )
    if painting.get_preview_pens is not None:
        extension["get_preview_pens"] = painting.get_preview_pens
    if painting.request_overlay_update is not None:
        extension["request_overlay_update"] = painting.request_overlay_update
    if painting.panel_to_target_point is not None:
        extension["panel_to_active_mask_point"] = painting.panel_to_target_point
    if painting.target_to_panel_point is not None:
        extension["active_mask_to_panel_point"] = painting.target_to_panel_point
    return ToolActivationPorts(
        cursor=cursor,
        navigation=navigation,
        movement=movement,
        transform=transform,
        pixel_selection=pixel_selection,
        coverage_shapes=coverage_shapes or pixel_selection,
        painting=painting,
        clone_stamp=clone_stamp or CloneStampInteractionPort(painting=painting),
        paint_bucket=paint_bucket or PaintBucketInteractionPort(),
        smart_selection=smart_selection,
        domain_ports={} if domain_ports is None else dict(domain_ports),
        extension=extension,
    )
