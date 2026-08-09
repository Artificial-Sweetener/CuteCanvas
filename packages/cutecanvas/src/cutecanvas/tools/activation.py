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
"""Focused activation-port assembly for CuteCanvas editor tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtGui import QPen
from qpane import CursorInteractionPort, NavigationInteractionPort
from qpane.sdk.vector import VectorShapeKind

from ..coverage import CoverageCombineMode
from ..coverage.canvas_aperture import CoverageCanvasAperture
from ..editor import EditorOperation
from ..painting.tools.clone_feedback import CloneStampFeedbackProjector
from ..selection.translation_interaction import PixelSelectionTranslationInteraction
from .affine_ports import SharedEdgeResizePort, TransformInteractionPort
from .ports import (
    AuthoringSnapPort,
    CloneStampInteractionPort,
    MoveInteractionPort,
    PaintBucketInteractionPort,
    PaintingInteractionPort,
    PixelSelectionInteractionPort,
    SelectionTranslationPort,
    SmartSegmentationInteractionPort,
    ToolActivationPorts,
    VectorInteractionPort,
    VectorNodeInteractionPort,
    VectorTextInteractionPort,
    tool_activation_ports,
)

if TYPE_CHECKING:
    from ..canvas import CuteCanvas


def build_editor_tool_ports(
    qpane: CuteCanvas,
    *,
    is_alt_held: Callable[[], bool],
    is_shift_held: Callable[[], bool],
    get_brush_size: Callable[[], int],
    get_preview_pens: Callable[[], tuple[QPen, QPen]],
) -> ToolActivationPorts:
    """Resolve one immutable activation boundary from authoritative owners."""
    viewport = qpane.view().viewport
    is_image_null = lambda: not qpane.view().has_renderable_content()

    def can_pan() -> bool:
        """Return whether current content exceeds the physical viewport."""
        if is_image_null():
            return False
        return viewport.can_pan(
            zoom=viewport.zoom,
            image_size=qpane.view().content_rect().size(),
            panel_size=qpane.physicalViewportRect().size(),
        )

    cursor = CursorInteractionPort(
        is_drag_out_allowed=qpane.isDragOutAllowed,
        is_content_empty=is_image_null,
    )
    navigation = NavigationInteractionPort(
        is_navigation_locked=viewport.is_locked,
        is_content_empty=is_image_null,
        is_drag_out_allowed=qpane.isDragOutAllowed,
        can_pan=can_pan,
        get_pan=lambda: viewport.pan,
        get_zoom=lambda: viewport.zoom,
        get_native_zoom=viewport.nativeZoom,
        get_fit_zoom=viewport.computeFitZoom,
        get_zoom_mode=viewport.get_zoom_mode,
        set_zoom_fit=viewport.setZoomFit,
        set_zoom_fit_interpolated=qpane._apply_zoom_fit_interpolated,
        set_zoom_one_to_one=viewport.setZoom1To1,
        set_zoom_one_to_one_interpolated=(qpane._apply_zoom_one_to_one_interpolated),
        get_dpr=qpane.devicePixelRatioF,
    )
    movement = qpane.editorMovementInteraction()
    authoring_snapping = qpane.snappingSubsystem().authoring
    authoring_snap_port = AuthoringSnapPort(
        begin=authoring_snapping.begin,
        update=authoring_snapping.update,
        clear=authoring_snapping.clear,
    )
    movement_port = MoveInteractionPort(
        begin_move=movement.begin,
        update_move=movement.update,
        finish_move=movement.finish,
        suspend_move=movement.suspend,
        cancel_move=movement.cancel,
        anchor_move=movement.anchor_floating_pixels,
        update_move_hover=movement.update_hover,
        clear_move_hover=movement.clear_hover,
        move_target_available=lambda: movement.target_available,
        move_cursor_intent=lambda: movement.cursor_intent,
        nudge_move=movement.nudge,
    )
    transform = qpane.sceneLayerTransformInteraction()
    transform_port = TransformInteractionPort(
        transform_presentation=transform.presentation,
        begin_transform=transform.begin,
        update_transform=transform.update,
        end_transform_gesture=transform.end_gesture,
        commit_transform=transform.commit,
        cancel_transform=transform.cancel,
        suspend_transform=transform.suspend,
    )
    shared_edge = qpane.sharedEdgeResizeInteraction()
    shared_edge_port = SharedEdgeResizePort(
        presentation=shared_edge.presentation,
        update_hover=shared_edge.update_hover,
        clear_hover=shared_edge.clear_hover,
        begin=shared_edge.begin,
        update=shared_edge.update,
        finish=shared_edge.finish,
        cancel=shared_edge.cancel,
    )
    painting = qpane.paintingCoordinator()
    paint_destination = qpane.interactivePaintDestination()
    mask_aperture = qpane.activeMaskCanvasAperture()
    mask_coordinates = qpane.activeMaskLayerCoordinates()
    canvas_aperture = CoverageCanvasAperture(
        active_scene=qpane.view().current_scene_descriptor,
        panel_to_scene=qpane.view().panel_to_scene_point,
        target_to_panel=qpane.view().scene_to_panel_point,
    )
    mask_shape_aperture = CoverageCanvasAperture(
        active_scene=qpane.view().current_scene_descriptor,
        panel_to_scene=qpane.view().panel_to_scene_point,
        target_to_panel=mask_coordinates.source_to_panel,
        target_aperture_path=mask_aperture.coverage_aperture_path,
    )
    selection_translation = PixelSelectionTranslationInteraction(
        active_scene=qpane.view().current_scene_descriptor,
        selections=qpane.pixelSelectionService(),
    )
    selection_port = PixelSelectionInteractionPort(
        panel_to_scene_point=qpane.view().panel_to_scene_point,
        target_to_panel_point=qpane.view().scene_to_panel_point,
        can_select=lambda: (
            qpane.editorOperationResolver()
            .resolve(EditorOperation.SELECT_PIXELS)
            .allowed
        ),
        has_selection=lambda: bool(
            (state := qpane.pixelSelectionState()) is not None and state.has_selection
        ),
        alt_constrains_empty_shape=True,
        commit_pixel_selection=qpane.editorInteraction().commit_active_pixel_selection,
        commit_coverage_item=qpane.editorInteraction().commit_active_coverage_item,
        is_shift_held=is_shift_held,
        is_alt_held=is_alt_held,
        get_shape_feather_radius=lambda: (
            qpane.coverageShapeConfiguration().options.feather_radius
        ),
        constrain_coverage_item=canvas_aperture.constrain_item,
        coverage_item_to_panel_path=canvas_aperture.item_panel_path,
        snapping=authoring_snap_port,
        translation=SelectionTranslationPort(
            can_begin=selection_translation.can_begin,
            begin=selection_translation.begin,
            update=selection_translation.update,
            finish=selection_translation.finish,
            cancel=selection_translation.cancel,
            suspend=selection_translation.suspend,
        ),
    )
    coverage_shape_port = PixelSelectionInteractionPort(
        panel_to_scene_point=mask_coordinates.panel_to_source,
        target_to_panel_point=mask_coordinates.source_to_panel,
        can_select=painting.can_commit_coverage_item,
        commit_coverage_item=painting.commit_coverage_item,
        is_shift_held=is_shift_held,
        is_alt_held=is_alt_held,
        default_combine_mode=CoverageCombineMode.ADD,
        get_shape_feather_radius=lambda: (
            qpane.coverageShapeConfiguration().options.feather_radius
        ),
        constrain_coverage_item=mask_shape_aperture.constrain_item,
        coverage_item_to_panel_path=mask_shape_aperture.item_panel_path,
        snapping=authoring_snap_port,
    )
    painting_port = PaintingInteractionPort(
        is_alt_held=is_alt_held,
        is_shift_held=is_shift_held,
        can_paint=paint_destination.can_prepare,
        prepare_paint=paint_destination.prepare,
        get_brush_size=get_brush_size,
        get_preview_pens=get_preview_pens,
        panel_hit_test=qpane.panelHitTest,
        panel_hit_test_precise=viewport.panel_hit_test,
        panel_to_content_point=viewport.panel_to_content_point,
        image_to_panel_point=viewport.content_to_panel_point,
        panel_to_target_point=painting.panel_to_target,
        target_to_panel_point=painting.target_to_panel,
        is_point_in_widget=lambda point: qpane.rect().contains(point),
        get_image_rect=qpane.view().content_rect,
        get_brush_increment=lambda: qpane.settings.brush_scroll_increment,
        get_pen_pressure_min_ratio=lambda: qpane.settings.pen_pressure_min_ratio,
        get_pen_pressure_gamma=lambda: qpane.settings.pen_pressure_gamma,
        get_pen_pressure_enabled=lambda: qpane.settings.pen_pressure_enabled,
        get_pressure_diameter=painting.diameter_for_pressure,
        get_smoothing=lambda: painting.preset.smoothing,
        get_zoom=lambda: viewport.zoom,
        get_dpr=qpane.devicePixelRatioF,
        get_preview_color=painting.preview_color,
        request_overlay_update=qpane.update,
    )
    clone_stamp = qpane.cloneStampOperation()
    clone_feedback = CloneStampFeedbackProjector(
        operation=clone_stamp,
        coordinates=qpane.coordinateSystem(),
    )
    clone_stamp_port = CloneStampInteractionPort(
        painting=painting_port,
        set_source_from_panel=clone_stamp.set_source_from_panel,
        source_footprint=clone_feedback.footprint,
        source_set=clone_stamp.source_is_available,
    )
    bucket = qpane.paintBucketCoordinator()
    bucket_port = PaintBucketInteractionPort(
        panel_to_target_point=painting.panel_to_target,
        can_fill=lambda: bucket.can_fill,
        request_fill=lambda point, mode: bucket.request(point, mode=mode),
        cancel_fill=bucket.cancel,
        is_shift_held=is_shift_held,
        is_alt_held=is_alt_held,
    )
    smart_segmentation_port = SmartSegmentationInteractionPort(
        is_alt_held=is_alt_held,
        is_shift_held=is_shift_held,
        resolve_prompt_projection=qpane.active_raster_coordinates().resolve,
        panel_to_active_mask_point=mask_coordinates.panel_to_source,
        get_min_selection_size=lambda: qpane.settings.smart_select_min_size,
        get_active_mask_color=lambda: (
            qpane.mask_service.getActiveMaskColor() if qpane.mask_service else None
        ),
        get_active_mask_id=lambda: (
            qpane.mask_service.getActiveMaskId() if qpane.mask_service else None
        ),
    )
    vector = qpane._vector_interaction_controller()
    vector_port = VectorInteractionPort(
        panel_to_source=vector.panel_to_active_source,
        commit_shape=vector.commit_shape,
        commit_path=lambda points, closed: vector.commit_path(points, closed=closed),
        shape_is_ellipse=lambda: vector.shape is VectorShapeKind.ELLIPSE,
        snapping=authoring_snap_port,
    )
    nodes = qpane._vector_node_controller()
    node_port = VectorNodeInteractionPort(
        begin=nodes.begin,
        update=nodes.update,
        finish=nodes.finish,
        cancel=nodes.cancel,
        overlay_state=nodes.overlay_state,
    )
    text = qpane._vector_text_controller()
    text_port = VectorTextInteractionPort(
        begin_at=text.begin_at,
        insert=text.insert,
        backspace=text.backspace,
        delete=text.delete,
        move_cursor=text.move_cursor,
        move_cursor_to=text.move_cursor_to,
        text_length=lambda: 0 if text.state() is None else len(text.state().text),
        commit=text.commit,
        cancel=text.cancel,
        active=lambda: text.active,
        overlay_state=text.overlay_state,
    )
    return tool_activation_ports(
        cursor=cursor,
        navigation=navigation,
        movement=movement_port,
        transform=transform_port,
        shared_edge_resize=shared_edge_port,
        pixel_selection=selection_port,
        coverage_shapes=coverage_shape_port,
        painting=painting_port,
        clone_stamp=clone_stamp_port,
        paint_bucket=bucket_port,
        smart_segmentation=smart_segmentation_port,
        domain_ports={
            qpane.CONTROL_MODE_VECTOR_SHAPE: vector_port,
            qpane.CONTROL_MODE_VECTOR_PATH: vector_port,
            qpane.CONTROL_MODE_VECTOR_NODE: node_port,
            qpane.CONTROL_MODE_VECTOR_TEXT: text_port,
        },
    )
