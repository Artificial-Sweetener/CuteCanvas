#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Transient state and geometry for one unresolved floating raster edit."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF

from ..coverage import CoverageSnapshot
from ..scene.layer_selection import SceneLayerSelection
from ..scene.model import LayerDescriptor
from ..scene.pixel_fragments import RasterPixelLift
from ..scene.pixel_move_preview import RasterPixelMovePreview
from ..scene.pixel_transitions import RasterPixelTransition
from ..selection import PixelSelectionState
from .pixel_move_target import SelectedPixelMoveTarget, coverage_contains


@dataclass(slots=True)
class FloatingPixelSession:
    """Own transient displacement state around an immutable lifted fragment."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    layer: LayerDescriptor
    selection: CoverageSnapshot
    movement_selection: CoverageSnapshot
    local_coverage: CoverageSnapshot
    lift: RasterPixelLift
    selected_layer: SceneLayerSelection
    cut_source: bool
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    delta: tuple[int, int] = (0, 0)
    drag_origin: QPointF | None = None
    drag_start_delta: tuple[int, int] = (0, 0)
    preview_revision: int = 0
    preview_transition: RasterPixelTransition | None = None

    @classmethod
    def create(
        cls,
        target: SelectedPixelMoveTarget,
        lift: RasterPixelLift,
        selected_layer: SceneLayerSelection,
        *,
        copy: bool,
    ) -> FloatingPixelSession:
        """Create a session from one fully resolved editable target."""
        return cls(
            scene_id=target.scene.scene_id,
            layer_id=target.layer.layer_id,
            layer=target.layer,
            selection=target.selection,
            movement_selection=target.scene_coverage,
            local_coverage=target.local_coverage,
            lift=lift,
            selected_layer=selected_layer,
            cut_source=not copy,
        )

    @property
    def dragging(self) -> bool:
        """Return whether a pointer sequence is currently active."""
        return self.drag_origin is not None

    @property
    def preview_state(self) -> PixelSelectionState:
        """Return translated render-only selection coverage."""
        delta_x, delta_y = self.scene_delta
        return PixelSelectionState(
            self.scene_id,
            -self.preview_revision - 1,
            self.movement_selection.translated(delta_x, delta_y),
        )

    @property
    def raster_preview(self) -> RasterPixelMovePreview | None:
        """Return the exact transient transition for rendering when displaced."""
        if self.preview_transition is None:
            return None
        return RasterPixelMovePreview(
            session_id=self.session_id,
            scene_id=self.scene_id,
            layer_id=self.layer_id,
            coverage=self.local_coverage,
            transition=self.preview_transition,
            pixel_format=self.lift.fragment.pixel_format,
            delta_x=self.delta[0],
            delta_y=self.delta[1],
        )

    @property
    def scene_delta(self) -> tuple[int, int]:
        """Map quantized local displacement into integer scene coordinates."""
        transform = self.layer.transform
        if transform is None:
            return 0, 0
        return (
            round(self.delta[0] * transform.scale_x),
            round(self.delta[1] * transform.scale_y),
        )

    def contains(self, scene_point: QPointF) -> bool:
        """Return whether the translated selection covers ``scene_point``."""
        return coverage_contains(self.preview_state.coverage, scene_point)

    def begin_drag(self, scene_point: QPointF) -> None:
        """Capture a pointer origin for an additional drag."""
        self.drag_origin = QPointF(scene_point)
        self.drag_start_delta = self.delta

    def update_drag(self, scene_point: QPointF) -> bool:
        """Update quantized layer-local displacement from pointer movement."""
        transform = self.layer.transform
        if self.drag_origin is None or transform is None:
            return False
        drag_delta = scene_point - self.drag_origin
        local_delta = (
            self.drag_start_delta[0] + round(drag_delta.x() / transform.scale_x),
            self.drag_start_delta[1] + round(drag_delta.y() / transform.scale_y),
        )
        if local_delta == self.delta:
            return False
        self.delta = local_delta
        self.advance_preview()
        return True

    def finish_drag(self, scene_point: QPointF) -> bool:
        """Finish the active pointer drag while keeping the session unresolved."""
        if self.drag_origin is None:
            return False
        self.update_drag(scene_point)
        self.drag_origin = None
        self.drag_start_delta = self.delta
        self.advance_preview()
        return True

    def suspend_drag(self) -> bool:
        """Release pointer capture without changing unresolved displacement."""
        if self.drag_origin is None:
            return False
        self.drag_origin = None
        self.drag_start_delta = self.delta
        return True

    def nudge(self, delta_x: int, delta_y: int) -> None:
        """Apply one integer keyboard displacement."""
        self.delta = (self.delta[0] + int(delta_x), self.delta[1] + int(delta_y))
        self.drag_start_delta = self.delta
        self.advance_preview()

    def advance_preview(self) -> None:
        """Advance transient identity after presentation-affecting state changes."""
        self.preview_revision += 1
