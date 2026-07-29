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
"""Bind one canvas viewport to detachable normalized inspection state."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Protocol

from PySide6.QtCore import QPointF, QRectF, QSizeF
from qpane.sdk.inspection import (
    InspectionTarget,
    InspectionUpdate,
    InspectionViewState,
    InspectionZoomMode,
    capture_inspection,
    project_inspection,
)
from qpane.sdk.rendering import ViewportZoomMode

from .session import CanvasSessionSnapshot, CanvasViewSession


class InspectionViewport(Protocol):
    """Describe the supported QPane viewport operations used by the binding."""

    zoom: float
    pan: QPointF
    zoom_mode: ViewportZoomMode

    def get_zoom_mode(self) -> ViewportZoomMode:
        """Return the active zoom interpretation."""
        ...

    def setZoomFit(self) -> None:
        """Fit current content in the viewport."""
        ...

    def setZoomAndPan(self, zoom: float, pan: QPointF) -> None:
        """Apply one exact viewport transform."""
        ...


class SessionInspectionBinding:
    """Synchronize one viewport without putting navigation in document state."""

    def __init__(
        self,
        *,
        session: CanvasViewSession,
        viewport: InspectionViewport,
        target_bounds: Callable[[uuid.UUID], QRectF | None],
        viewport_size: Callable[[], QSizeF],
    ) -> None:
        """Bind explicit session, viewport, geometry, and viewport-size owners."""
        self._session = session
        self._viewport = viewport
        self._target_bounds = target_bounds
        self._viewport_size = viewport_size
        self._target_id: uuid.UUID | None = None
        self._inspection_token: uuid.UUID | None = None
        self._applying = False
        self._publication_suspensions = 0
        self._session_unsubscribe = session.subscribe(self._session_changed)
        self.refresh_target()

    def refresh_target(self, *, restore: bool = True) -> None:
        """Rebind the active composition and optionally restore its view state."""
        target_id = self._session.active_composition_id
        if target_id != self._target_id:
            if self._inspection_token is not None:
                self._session.inspection.unsubscribe(self._inspection_token)
            self._target_id = target_id
            self._inspection_token = (
                None
                if target_id is None
                else self._session.inspection.subscribe(
                    target_id,
                    self._apply_update,
                )
            )
        if not restore or target_id is None:
            return
        state = self._session.inspection.state_for(target_id)
        if state is not None:
            self._apply_state(target_id, state)

    def publish(self) -> None:
        """Capture viewport state and publish it to explicitly linked targets."""
        target = self._target()
        if self._applying or self._publication_suspensions or target is None:
            return
        viewport_size = self._viewport_size()
        if (
            viewport_size.width() <= 0.0
            or viewport_size.height() <= 0.0
            or float(self._viewport.zoom) <= 0.0
        ):
            return
        state = capture_inspection(
            target,
            viewport_size,
            zoom=float(self._viewport.zoom),
            pan=self._viewport.pan,
            zoom_mode=_inspection_zoom_mode(self._viewport.get_zoom_mode()),
        )
        self._session.inspection.update(
            target.target_id,
            state,
            source_subscription=self._inspection_token,
        )

    @contextmanager
    def suspend_publication(self) -> Iterator[None]:
        """Suppress intermediate geometry signals during atomic view setup."""
        self._publication_suspensions += 1
        try:
            yield
        finally:
            self._publication_suspensions -= 1

    def close(self) -> None:
        """Release session and inspection subscriptions idempotently."""
        self._session_unsubscribe()
        if self._inspection_token is not None:
            self._session.inspection.unsubscribe(self._inspection_token)
            self._inspection_token = None
        self._target_id = None

    def _session_changed(self, _snapshot: CanvasSessionSnapshot) -> None:
        """Restore linked inspection when an existing or first-time target activates."""
        self.refresh_target(restore=True)

    def _apply_update(self, update: InspectionUpdate) -> None:
        """Project one accepted linked update into this target's viewport."""
        if update.target_id != self._target_id:
            return
        self._apply_state(update.target_id, update.state)

    def _apply_state(
        self,
        target_id: uuid.UUID,
        state: InspectionViewState,
    ) -> None:
        """Apply a normalized state without recursively publishing it."""
        bounds = self._target_bounds(target_id)
        viewport_size = self._viewport_size()
        if (
            bounds is None
            or viewport_size.width() <= 0.0
            or viewport_size.height() <= 0.0
        ):
            return
        self._applying = True
        try:
            if state.zoom_mode is InspectionZoomMode.FIT:
                self._viewport.setZoomFit()
                return
            projected = project_inspection(
                InspectionTarget(target_id, bounds),
                viewport_size,
                state,
            )
            self._viewport.zoom_mode = ViewportZoomMode.CUSTOM
            self._viewport.setZoomAndPan(projected.zoom, projected.pan)
            if projected.zoom_mode is InspectionZoomMode.ONE_TO_ONE:
                self._viewport.zoom_mode = ViewportZoomMode.ONE_TO_ONE
        finally:
            self._applying = False

    def _target(self) -> InspectionTarget | None:
        """Return the active target only when its positive bounds are available."""
        target_id = self._target_id
        if target_id is None:
            return None
        bounds = self._target_bounds(target_id)
        if bounds is None:
            return None
        return InspectionTarget(target_id, bounds)


def _inspection_zoom_mode(mode: ViewportZoomMode) -> InspectionZoomMode:
    """Convert the renderer viewport mode to source-neutral inspection state."""
    if mode is ViewportZoomMode.FIT:
        return InspectionZoomMode.FIT
    if mode is ViewportZoomMode.ONE_TO_ONE:
        return InspectionZoomMode.ONE_TO_ONE
    return InspectionZoomMode.CUSTOM
