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
"""Coordinate transient selected-raster movement and explicit resolution."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import QPoint, QPointF, QRect
from qpane.sdk.scene import (
    AffineTransformGeometry,
    LayerTransform,
    SceneDescriptor,
    TransformLocalBounds,
    TransformModifiers,
    TransformOperation,
)

from cutecanvas.scene.pixel_move_preview import RasterPixelMovePreview

from ..composition.edit_controller import CompositionEditController
from ..scene.layer_selection import SceneLayerSelectionController
from ..scene.mutations import SceneMutationCoordinator
from ..scene.pixel_owners import LayerPixelOwnerRegistry
from ..scene.transform_session import LayerTransformBoxState, LayerTransformGesture
from ..selection import PixelSelectionService, PixelSelectionState
from .floating_history import FloatingPixelHistory
from .floating_layers import FloatingLayerPromotionRegistry
from .floating_resolution import FloatingPixelResolutionOwner
from .floating_session import FloatingPixelSession
from .pixel_move_target import (
    SelectedPixelMoveTarget,
    SelectedPixelMoveTargetResolver,
    coverage_contains,
)
from .selection_projection import LayerSelectionProjectionCache


class SelectedPixelMovementController:
    """Coordinate floating-session input while delegating durable resolution."""

    def __init__(
        self,
        *,
        active_scene: Callable[[], SceneDescriptor | None],
        scene_mutations: SceneMutationCoordinator,
        layer_selection: SceneLayerSelectionController,
        pixel_selection: PixelSelectionService,
        pixel_owners: LayerPixelOwnerRegistry,
        edits: CompositionEditController,
        selection_projections: LayerSelectionProjectionCache,
        preview_changed: Callable[[], None],
        promotions: FloatingLayerPromotionRegistry | None = None,
    ) -> None:
        """Bind authoritative target, transient-session, and resolution owners."""
        self._preview_changed = preview_changed
        promotion_registry = promotions or FloatingLayerPromotionRegistry()
        self._targets = SelectedPixelMoveTargetResolver(
            active_scene=active_scene,
            scene_mutations=scene_mutations,
            layer_selection=layer_selection,
            pixel_selection=pixel_selection,
            pixel_owners=pixel_owners,
            selection_projections=selection_projections,
        )
        history = FloatingPixelHistory(
            edits=edits,
            targets=self._targets,
            pixel_selection=pixel_selection,
            layer_selection=layer_selection,
            selection_projections=selection_projections,
            promotions=promotion_registry,
        )
        self._resolution = FloatingPixelResolutionOwner(
            targets=self._targets,
            history=history,
            pixel_selection=pixel_selection,
            layer_selection=layer_selection,
            selection_projections=selection_projections,
            promotions=promotion_registry,
        )
        self._session: FloatingPixelSession | None = None
        self._transform_gesture: LayerTransformGesture | None = None

    @property
    def active(self) -> bool:
        """Return whether selected content is floating unresolved."""
        return self._session is not None

    @property
    def target_resolver(self) -> SelectedPixelMoveTargetResolver:
        """Expose the sole selected-pixel eligibility owner."""
        return self._targets

    @property
    def dragging(self) -> bool:
        """Return whether a pointer sequence currently moves the floating edit."""
        return bool(self._session is not None and self._session.dragging)

    @property
    def scene_id(self) -> uuid.UUID | None:
        """Return the scene owning the unresolved edit."""
        return None if self._session is None else self._session.scene_id

    @property
    def source_layer_id(self) -> uuid.UUID | None:
        """Return the source layer owning the lifted pixels."""
        return None if self._session is None else self._session.layer_id

    @property
    def cut_source(self) -> bool:
        """Return whether resolution clears the lifted source pixels."""
        return bool(self._session is not None and self._session.cut_source)

    @property
    def offset(self) -> QPoint:
        """Return the current integer source-local displacement."""
        delta = (0, 0) if self._session is None else self._session.delta
        return QPoint(*delta)

    @property
    def scene_bounds(self) -> QRect | None:
        """Return current floating selection bounds in scene coordinates."""
        return None if self._session is None else self._session.scene_bounds

    @property
    def preview_state(self) -> PixelSelectionState | None:
        """Return translated render-only selection coverage during a session."""
        return None if self._session is None else self._session.preview_state

    @property
    def raster_preview(self) -> RasterPixelMovePreview | None:
        """Return transient render geometry without copying source pixels."""
        return None if self._session is None else self._session.raster_preview

    @property
    def transforming(self) -> bool:
        """Return whether floating content owns an affine transform session."""
        session = self._session
        translated = (
            LayerTransform()
            if session is None
            else LayerTransform(dx=float(session.delta[0]), dy=float(session.delta[1]))
        )
        return self._transform_gesture is not None or bool(
            session is not None and session.fragment_transform != translated
        )

    def transform_box_state(self) -> LayerTransformBoxState | None:
        """Return affine box geometry for selected or already floating pixels."""
        session = self._session
        if session is None:
            target = self._targets.resolve_selected()
            bounds = None if target is None else target.local_coverage.bounds
            transform = None if target is None else target.layer.transform
            if target is None or bounds is None or transform is None:
                return None
            return LayerTransformBoxState(
                target.scene.scene_id,
                target.layer.layer_id,
                TransformLocalBounds(
                    float(bounds.x),
                    float(bounds.y),
                    float(bounds.width),
                    float(bounds.height),
                ),
                transform,
                False,
            )
        if session.layer.transform is None:
            return None
        bounds = session.lift.fragment.bounds
        return LayerTransformBoxState(
            session.scene_id,
            session.layer_id,
            TransformLocalBounds(
                float(bounds.x),
                float(bounds.y),
                float(bounds.width),
                float(bounds.height),
            ),
            session.fragment_transform.followed_by(session.layer.transform),
            session.fragment_transform != LayerTransform(),
        )

    def begin_transform(
        self,
        operation: TransformOperation,
        scene_point: QPointF,
    ) -> bool:
        """Begin one affine gesture against selected floating pixels."""
        if self._session is None and not self._begin_selected_session():
            return False
        state = self.transform_box_state()
        if state is None:
            return False
        self._transform_gesture = LayerTransformGesture(
            QPointF(scene_point),
            operation,
            AffineTransformGeometry(state.bounds, state.transform),
        )
        self._changed()
        return True

    def update_transform(
        self,
        scene_point: QPointF,
        modifiers: TransformModifiers,
    ) -> bool:
        """Update affine floating geometry without resampling source pixels."""
        session = self._session
        gesture = self._transform_gesture
        layer_transform = None if session is None else session.layer.transform
        if session is None or gesture is None or layer_transform is None:
            return False
        scene_transform = gesture.geometry.transform_for_drag(
            gesture.operation,
            gesture.origin,
            scene_point,
            modifiers,
        )
        layer_inverse = layer_transform.inverted()
        if scene_transform is None or layer_inverse is None:
            return False
        changed = session.set_fragment_transform(
            scene_transform.followed_by(layer_inverse)
        )
        if changed:
            self._preview_changed()
        return changed

    def finish_transform(
        self,
        scene_point: QPointF,
        modifiers: TransformModifiers,
    ) -> bool:
        """Release affine pointer ownership while retaining unresolved pixels."""
        if self._transform_gesture is None:
            return False
        changed = self.update_transform(scene_point, modifiers)
        self._transform_gesture = None
        self._preview_changed()
        return changed or self._session is not None

    def suspend_transform(self) -> bool:
        """Release affine pointer ownership without changing its preview."""
        had_gesture = self._transform_gesture is not None
        self._transform_gesture = None
        return had_gesture or self._session is not None

    def commit_transform(self) -> bool:
        """Resolve current affine pixels to their source as one history edit."""
        self._transform_gesture = None
        return self.anchor_to_source()

    def has_selection(self) -> bool:
        """Return whether the active scene owns nonempty pixel selection coverage."""
        return self._targets.has_selection()

    def has_movable_pixels(self) -> bool:
        """Return whether the selection contains editable selected-layer pixels."""
        return self._session is not None or self._targets.resolve_selected() is not None

    def can_begin(self, scene_point: QPointF) -> bool:
        """Return whether selected editable content can move from ``scene_point``."""
        if self._session is not None:
            return self._session.contains(scene_point)
        return self._targets.resolve_at(scene_point) is not None

    def begin(
        self,
        scene_point: QPointF,
        copy: bool = False,
        *,
        target: SelectedPixelMoveTarget | None = None,
    ) -> bool:
        """Begin selected-content movement when selection and policy permit it."""
        if self._session is not None:
            if not self._session.contains(scene_point):
                return False
            self._session.begin_drag(scene_point)
            return True
        resolved_target = target or self._targets.resolve_at(scene_point)
        if resolved_target is None or not coverage_contains(
            resolved_target.scene_coverage,
            scene_point,
        ):
            return False
        lift = resolved_target.owner.lift_coverage(
            resolved_target.layer,
            resolved_target.local_coverage,
        )
        selected = self._targets.selected_layer
        if lift is None or selected is None:
            return False
        self._session = FloatingPixelSession.create(
            resolved_target,
            lift,
            selected,
            copy=copy,
        )
        self._session.begin_drag(scene_point)
        self._changed()
        return True

    def update(self, scene_point: QPointF) -> bool:
        """Update quantized layer-local displacement without mutating pixels."""
        if self._session is None or not self._session.update_drag(scene_point):
            return False
        self._preview_changed()
        return True

    def finish(self, scene_point: QPointF) -> bool:
        """Finish one drag while retaining the unresolved floating edit."""
        if self._session is None:
            return False
        if not self._session.finish_drag(scene_point):
            return False
        self._settle_preview_transition()
        self._preview_changed()
        return True

    def suspend_drag(self) -> bool:
        """Release active pointer state without discarding the floating session."""
        return bool(self._session is not None and self._session.suspend_drag())

    def nudge(self, delta_x: int, delta_y: int) -> bool:
        """Displace floating pixels without resolving their destination."""
        if delta_x == 0 and delta_y == 0:
            return False
        if self._session is None and not self._begin_selected_session():
            return False
        self._session.nudge(delta_x, delta_y)
        self._settle_preview_transition()
        self._preview_changed()
        return True

    def anchor_to_source(self) -> bool:
        """Resolve floating pixels back into their original editable layer."""
        session = self._session
        if session is None:
            return False
        if not self._resolution.anchor_to_source(session):
            self.cancel()
            return False
        self._clear()
        return True

    def anchor_to(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Resolve floating pixels into a compatible editable destination layer."""
        session = self._session
        if session is None:
            return False
        if not self._resolution.anchor_to(session, scene_id, layer_id):
            return False
        self._clear()
        return True

    def promote_to_layer(self, label: str | None = None) -> uuid.UUID | None:
        """Resolve floating pixels into a newly created compatible layer."""
        session = self._session
        if session is None:
            return None
        layer_id = self._resolution.promote(session, label)
        if layer_id is not None:
            self._clear()
        return layer_id

    def cancel(self) -> bool:
        """Discard transient displacement without changing durable owners."""
        self._transform_gesture = None
        if self._session is None:
            return False
        self._clear()
        return True

    def _begin_selected_session(self) -> bool:
        """Lift the selected editable content for keyboard movement."""
        target = self._targets.resolve_selected()
        if target is None:
            return False
        lift = target.owner.lift_coverage(target.layer, target.local_coverage)
        selected = self._targets.selected_layer
        if lift is None or selected is None:
            return False
        self._session = FloatingPixelSession.create(
            target,
            lift,
            selected,
            copy=False,
        )
        return True

    def _clear(self) -> None:
        """Release transient session state and request presentation."""
        self._session = None
        self._transform_gesture = None
        self._preview_changed()

    def _settle_preview_transition(self) -> None:
        """Compose the exact durable candidate once after interactive movement."""
        session = self._session
        if session is None or session.delta == (0, 0):
            if session is not None:
                session.settled_transition = None
            return
        resolved = self._targets.resolve_layer(session.scene_id, session.layer_id)
        if resolved is None:
            session.settled_transition = None
            return
        _scene, layer, owner = resolved
        session.settled_transition = owner.preview_move(
            layer,
            session.lift,
            session.delta[0],
            session.delta[1],
            cut_source=session.cut_source,
        )

    def _changed(self) -> None:
        """Advance transient identity and request presentation."""
        if self._session is not None:
            self._session.advance_preview()
        self._preview_changed()
