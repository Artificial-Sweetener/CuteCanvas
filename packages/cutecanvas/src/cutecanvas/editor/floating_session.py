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
"""Transient state and geometry for one unresolved floating raster edit."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRect, QRectF
from qpane.sdk.scene import LayerDescriptor, LayerTransform

from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.coverage.containment import coverage_contains
from cutecanvas.scene.pixel_fragments import RasterPixelLift
from cutecanvas.scene.pixel_move_preview import RasterPixelMovePreview
from cutecanvas.scene.pixel_transitions import RasterPixelTransition
from cutecanvas.types import RasterExtentPolicy

from ..scene.layer_selection import SceneLayerSelection
from ..selection import LayerCoverageProjector, PixelSelectionState
from .pixel_move_target import SelectedPixelMoveTarget


@dataclass(slots=True)
class FloatingPixelSession:
    """Own transient displacement state around an immutable lifted fragment."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    layer: LayerDescriptor
    selection: CoverageSnapshot
    transform_frame_coverage: CoverageSnapshot
    local_contribution: CoverageSnapshot
    lift: RasterPixelLift
    selected_layer: SceneLayerSelection
    extent_policy: RasterExtentPolicy
    source_revision: object
    cut_source: bool
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    delta: tuple[int, int] = (0, 0)
    drag_origin: QPointF | None = None
    drag_start_delta: tuple[int, int] = (0, 0)
    preview_revision: int = 0
    settled_transition: RasterPixelTransition | None = None
    fragment_transform: LayerTransform = field(default_factory=LayerTransform)
    _selection_projector: LayerCoverageProjector = field(
        default_factory=LayerCoverageProjector,
        repr=False,
    )
    _preview_selection: CoverageSnapshot | None = field(default=None, repr=False)

    @classmethod
    def create(
        cls,
        target: SelectedPixelMoveTarget,
        lift: RasterPixelLift,
        selected_layer: SceneLayerSelection,
        *,
        copy: bool,
        transform_frame_coverage: CoverageSnapshot,
    ) -> FloatingPixelSession:
        """Create a session from one fully resolved editable target."""
        return cls(
            scene_id=target.scene.scene_id,
            layer_id=target.layer.layer_id,
            layer=target.layer,
            selection=target.selection,
            transform_frame_coverage=transform_frame_coverage,
            local_contribution=target.local_contribution,
            lift=lift,
            selected_layer=selected_layer,
            extent_policy=target.extent_policy,
            source_revision=target.source_revision,
            cut_source=not copy,
        )

    @property
    def dragging(self) -> bool:
        """Return whether a pointer sequence is currently active."""
        return self.drag_origin is not None

    @property
    def preview_state(self) -> PixelSelectionState:
        """Return affine render-only coverage for the session's selection frame."""
        return PixelSelectionState(
            self.scene_id,
            -self.preview_revision - 1,
            self.preview_selection,
        )

    @property
    def preview_selection(self) -> CoverageSnapshot | None:
        """Return cached scene coverage projected through current affine geometry."""
        if self._preview_selection is not None:
            return self._preview_selection
        local = self._selection_projector.project(
            self.transform_frame_coverage,
            self.fragment_transform,
        )
        if local is None or self.layer.transform is None:
            return None
        self._preview_selection = self._selection_projector.project(
            local,
            self.layer.transform,
        )
        return self._preview_selection

    @property
    def raster_preview(self) -> RasterPixelMovePreview | None:
        """Return stable lifted pixels plus their transient displacement."""
        if self.fragment_transform == LayerTransform():
            return None
        return RasterPixelMovePreview(
            session_id=self.session_id,
            scene_id=self.scene_id,
            layer_id=self.layer_id,
            lift=self.lift,
            cut_source=self.cut_source,
            settled_transition=self.settled_transition,
            fragment_transform=self.fragment_transform,
            extent_clip_bounds=(
                self.layer.raster_bounds
                if self.extent_policy is RasterExtentPolicy.FIXED
                else None
            ),
        )

    @property
    def scene_delta(self) -> tuple[int, int]:
        """Map quantized local displacement into integer scene coordinates."""
        transform = self.layer.transform
        if transform is None:
            return 0, 0
        mapped = transform.map_vector(
            QPointF(float(self.delta[0]), float(self.delta[1]))
        )
        return round(mapped.x()), round(mapped.y())

    def contains(self, scene_point: QPointF) -> bool:
        """Return whether transformed fragment coverage contains ``scene_point``."""
        transform = self.scene_transform
        local_point = transform.inverse_map(scene_point)
        return bool(
            local_point is not None
            and coverage_contains(
                self.lift.fragment.contribution_coverage,
                local_point,
            )
        )

    @property
    def scene_transform(self) -> LayerTransform:
        """Return current fragment-local to scene geometry."""
        layer_transform = self.layer.transform
        return (
            self.fragment_transform
            if layer_transform is None
            else self.fragment_transform.followed_by(layer_transform)
        )

    @property
    def scene_bounds(self) -> QRect:
        """Return the conservative scene rectangle of transformed pixels."""
        bounds = self.lift.fragment.bounds
        placement = self.scene_transform.map_bounds(bounds)
        return QRectF(
            placement.x,
            placement.y,
            placement.width,
            placement.height,
        ).toAlignedRect()

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
        mapped_delta = transform.inverse_map_vector(drag_delta)
        if mapped_delta is None:
            return False
        local_delta = (
            self.drag_start_delta[0] + round(mapped_delta.x()),
            self.drag_start_delta[1] + round(mapped_delta.y()),
        )
        if local_delta == self.delta:
            return False
        self.delta = local_delta
        self.fragment_transform = LayerTransform(
            dx=float(local_delta[0]),
            dy=float(local_delta[1]),
        )
        self.settled_transition = None
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
        self.fragment_transform = LayerTransform(
            dx=float(self.delta[0]),
            dy=float(self.delta[1]),
        )
        self.drag_start_delta = self.delta
        self.settled_transition = None
        self.advance_preview()

    def advance_preview(self) -> None:
        """Advance transient identity after presentation-affecting state changes."""
        self.preview_revision += 1
        self._preview_selection = None

    def set_fragment_transform(self, transform: LayerTransform) -> bool:
        """Replace affine fragment geometry and advance transient identity."""
        if transform == self.fragment_transform:
            return False
        self.fragment_transform = transform
        self.settled_transition = None
        self.advance_preview()
        return True
