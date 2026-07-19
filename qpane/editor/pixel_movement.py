#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Coordinate transient selected-raster movement and explicit resolution."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import QPoint, QPointF, QRect

from ..composition.edit_controller import CompositionEditController
from ..scene.layer_selection import SceneLayerSelectionController
from ..scene.model import SceneDescriptor
from ..scene.mutations import SceneMutationCoordinator
from ..scene.pixel_move_preview import RasterPixelMovePreview
from ..scene.pixel_owners import LayerPixelOwnerRegistry
from ..selection import PixelSelectionService, PixelSelectionState
from .floating_history import FloatingPixelHistory
from .floating_layers import FloatingLayerPromotionRegistry
from .floating_resolution import FloatingPixelResolutionOwner
from .floating_session import FloatingPixelSession
from .pixel_move_target import SelectedPixelMoveTargetResolver
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

    @property
    def active(self) -> bool:
        """Return whether selected content is floating unresolved."""
        return self._session is not None

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
        preview = self.preview_state
        bounds = None if preview is None else preview.coverage.bounds
        return None if bounds is None else bounds.to_qrect()

    @property
    def preview_state(self) -> PixelSelectionState | None:
        """Return translated render-only selection coverage during a session."""
        return None if self._session is None else self._session.preview_state

    @property
    def raster_preview(self) -> RasterPixelMovePreview | None:
        """Return transient render geometry without copying source pixels."""
        return None if self._session is None else self._session.raster_preview

    def has_selection(self) -> bool:
        """Return whether the active scene owns nonempty pixel selection coverage."""
        return self._targets.has_selection()

    def can_begin(self, scene_point: QPointF) -> bool:
        """Return whether selected editable content can move from ``scene_point``."""
        if self._session is not None:
            return self._session.contains(scene_point)
        return self._targets.resolve_at(scene_point) is not None

    def begin(self, scene_point: QPointF, copy: bool = False) -> bool:
        """Begin selected-content movement when selection and policy permit it."""
        if self._session is not None:
            if not self._session.contains(scene_point):
                return False
            self._session.begin_drag(scene_point)
            return True
        target = self._targets.resolve_at(scene_point)
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
            copy=copy,
        )
        self._session.begin_drag(scene_point)
        self._changed()
        return True

    def update(self, scene_point: QPointF) -> bool:
        """Update quantized layer-local displacement without mutating pixels."""
        if self._session is None or not self._session.update_drag(scene_point):
            return False
        self._compose_preview_transition()
        self._preview_changed()
        return True

    def finish(self, scene_point: QPointF) -> bool:
        """Finish one drag while retaining the unresolved floating edit."""
        if self._session is None:
            return False
        previous_delta = self._session.delta
        if not self._session.finish_drag(scene_point):
            return False
        if self._session.delta != previous_delta:
            self._compose_preview_transition()
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
        self._compose_preview_transition()
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
        self._preview_changed()

    def _compose_preview_transition(self) -> None:
        """Refresh the exact immutable-source transition for current displacement."""
        session = self._session
        if session is None or session.delta == (0, 0):
            if session is not None:
                session.preview_transition = None
            return
        resolved = self._targets.resolve_layer(session.scene_id, session.layer_id)
        if resolved is None:
            session.preview_transition = None
            return
        _scene, layer, owner = resolved
        session.preview_transition = owner.preview_move(
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
