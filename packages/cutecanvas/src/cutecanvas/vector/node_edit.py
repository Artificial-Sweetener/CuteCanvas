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
"""Transient node-edit sessions and single-command vector geometry commits."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath

from qpane.sdk.vector import (
    VectorNodeRole,
    VectorObject,
    VectorObjectKind,
    VectorPathCommandKind,
    object_contains,
    object_path,
)

from ..scene.layer_selection import SceneLayerSelectionController
from .editing import VectorEditService
from .projection import VectorDocumentProjection
from .public import VectorNodeSelectionSnapshot
from .selection import VectorObjectSelectionController
from .store import VectorAssetStore
from .targets import VectorAuthoringTarget, VectorAuthoringTargetResolver

_HANDLE_RADIUS_PX = 8.0


@dataclass(frozen=True, slots=True)
class VectorNodeHandle:
    """Describe one stable editable handle in document coordinates."""

    index: int
    role: VectorNodeRole
    point: QPointF


@dataclass(frozen=True, slots=True)
class VectorNodeOverlayState:
    """Carry detached panel-space feedback without editor authority."""

    path: QPainterPath
    handles: tuple[VectorNodeHandle, ...]
    selected_index: int | None


@dataclass(slots=True)
class _VectorNodeSession:
    """Retain one exact durable base and its current preview object."""

    target: VectorAuthoringTarget
    base: VectorObject
    preview: VectorObject
    node_index: int


class VectorNodeEditController:
    """Own node selection, transient previews, and atomic release commits."""

    def __init__(
        self,
        *,
        assets: VectorAssetStore,
        edits: VectorEditService,
        projection: VectorDocumentProjection,
        targets: VectorAuthoringTargetResolver,
        layer_selection: SceneLayerSelectionController,
        object_selection: VectorObjectSelectionController,
        changed: Callable[[], None],
        selection_changed: Callable[[], None],
    ) -> None:
        """Bind authoritative vector, selection, coordinate, and history owners."""
        self._assets = assets
        self._edits = edits
        self._projection = projection
        self._targets = targets
        self._layer_selection = layer_selection
        self._object_selection = object_selection
        self._changed = changed
        self._selection_changed = selection_changed
        self._selection: VectorNodeSelectionSnapshot | None = None
        self._session: _VectorNodeSession | None = None

    @property
    def selection(self) -> VectorNodeSelectionSnapshot | None:
        """Return the current immutable control-point selection."""
        return self._selection

    @property
    def editing(self) -> bool:
        """Return whether a node drag has unresolved preview geometry."""
        return self._session is not None

    def begin(self, panel_point: QPointF) -> bool:
        """Select an object or begin dragging its nearest visible handle."""
        if self._session is not None:
            if not self._session_is_current(self._session):
                self.cancel()
                return False
            self.update(panel_point)
            return True
        target = self._active_target()
        if target is None:
            return False
        item = self._selected_object(target)
        if item is not None:
            handle = self._nearest_handle(target, item, panel_point)
            if handle is not None:
                self._session = _VectorNodeSession(
                    target,
                    item,
                    item,
                    handle.index,
                )
                self._set_selection(target, item, handle)
                return True
        document_point = self._targets.panel_to_document(target, panel_point)
        document = self._assets.get(target.vector_id)
        if document_point is None or document is None:
            return False
        selected = next(
            (
                candidate
                for candidate in reversed(document.objects)
                if object_contains(candidate, document_point)
            ),
            None,
        )
        self._set_node_selection(None)
        if selected is None:
            self._object_selection.clear()
            return False
        self._object_selection.set(
            target.scene_id,
            target.layer_id,
            (selected.object_id,),
        )
        self._changed()
        return True

    def update(self, panel_point: QPointF) -> bool:
        """Update immediate semantic preview geometry without recording history."""
        session = self._session
        if session is None or not self._session_is_current(session):
            return False
        document_point = self._targets.panel_to_document(session.target, panel_point)
        if document_point is None:
            return False
        preview = _move_handle(session.base, session.node_index, document_point)
        if preview == session.preview:
            return True
        session.preview = preview
        self._projection.set_object_preview(session.target.vector_id, preview)
        self._changed()
        return True

    def finish(self, panel_point: QPointF) -> bool:
        """Commit the current preview once, or end an unchanged press cleanly."""
        session = self._session
        if session is None:
            return False
        self.update(panel_point)
        self._session = None
        changed = session.preview != session.base and self._edits.replace_object(
            session.target.scene_id,
            session.target.layer_id,
            session.target.vector_id,
            session.preview,
        )
        preview_cleared = self._projection.clear(session.target.vector_id)
        if preview_cleared and not changed:
            self._changed()
        return True

    def cancel(self) -> bool:
        """Discard unresolved preview geometry while retaining object selection."""
        session = self._session
        if session is None:
            return False
        self._session = None
        if self._projection.clear(session.target.vector_id):
            self._changed()
        return True

    def synchronize(self) -> bool:
        """Drop stale session or node state after external scene mutations."""
        session = self._session
        if session is not None and not self._session_is_current(session):
            self.cancel()
        target = self._active_target()
        item = None if target is None else self._selected_object(target)
        if target is None or item is None:
            return self._set_node_selection(None)
        selection = self._selection
        if selection is not None and (
            selection.scene_id != target.scene_id
            or selection.layer_id != target.layer_id
            or selection.object_id != item.object_id
            or selection.node_index >= len(_object_handles(item))
        ):
            return self._set_node_selection(None)
        return False

    def overlay_state(self) -> VectorNodeOverlayState | None:
        """Return current selected-object path and handles in panel coordinates."""
        target = self._active_target()
        item = None if target is None else self._selected_object(target, effective=True)
        if target is None or item is None:
            return None
        transform = self._targets.document_to_panel_transform(target)
        if transform is None:
            return None
        handles = tuple(
            VectorNodeHandle(
                handle.index,
                handle.role,
                transform.map(handle.point),
            )
            for handle in _object_handles(item)
        )
        selected_index = (
            None
            if self._selection is None or self._selection.object_id != item.object_id
            else self._selection.node_index
        )
        return VectorNodeOverlayState(
            transform.map(object_path(item)),
            handles,
            selected_index,
        )

    def _active_target(self) -> VectorAuthoringTarget | None:
        """Resolve the selected direct vector layer or vector-mask target."""
        selection = self._layer_selection.current
        return None if selection is None else self._targets.resolve(selection.layer_id)

    def _selected_object(
        self,
        target: VectorAuthoringTarget,
        *,
        effective: bool = False,
    ) -> VectorObject | None:
        """Resolve the single selected object for the current target."""
        selection = self._object_selection.selection
        if (
            selection is None
            or selection.scene_id != target.scene_id
            or selection.layer_id != target.layer_id
            or len(selection.object_ids) != 1
        ):
            return None
        document = (
            self._projection.document(target.vector_id)
            if effective
            else self._assets.get(target.vector_id)
        )
        return None if document is None else document.object(selection.object_ids[0])

    def _nearest_handle(
        self,
        target: VectorAuthoringTarget,
        item: VectorObject,
        panel_point: QPointF,
    ) -> VectorNodeHandle | None:
        """Return the closest handle inside the fixed panel-space hit radius."""
        candidates: list[tuple[float, VectorNodeHandle]] = []
        for handle in _object_handles(item):
            projected = self._targets.document_to_panel(target, handle.point)
            if projected is None:
                continue
            distance = math.hypot(
                projected.x() - panel_point.x(),
                projected.y() - panel_point.y(),
            )
            if distance <= _HANDLE_RADIUS_PX:
                candidates.append((distance, handle))
        return None if not candidates else min(candidates, key=lambda pair: pair[0])[1]

    def _session_is_current(self, session: _VectorNodeSession) -> bool:
        """Reject previews after target, document, or object identity changes."""
        target = self._active_target()
        document = self._assets.get(session.target.vector_id)
        return bool(
            target == session.target
            and document is not None
            and document.object(session.base.object_id) == session.base
        )

    def _set_selection(
        self,
        target: VectorAuthoringTarget,
        item: VectorObject,
        handle: VectorNodeHandle,
    ) -> None:
        """Publish one selected handle identity."""
        self._set_node_selection(
            VectorNodeSelectionSnapshot(
                target.scene_id,
                target.layer_id,
                item.object_id,
                handle.index,
                handle.role,
            )
        )

    def _set_node_selection(
        self,
        selection: VectorNodeSelectionSnapshot | None,
    ) -> bool:
        """Replace node selection and publish only meaningful changes."""
        if selection == self._selection:
            return False
        self._selection = selection
        self._selection_changed()
        return True


def _object_handles(item: VectorObject) -> tuple[VectorNodeHandle, ...]:
    """Derive stable editable handles from one semantic object."""
    transform = item.transform.to_qtransform()
    if item.kind is VectorObjectKind.SHAPE:
        x, y, width, height = item.local_bounds
        points = (
            QPointF(x, y),
            QPointF(x + width, y),
            QPointF(x + width, y + height),
            QPointF(x, y + height),
        )
        return tuple(
            VectorNodeHandle(index, VectorNodeRole.BOUNDS, transform.map(point))
            for index, point in enumerate(points)
        )
    handles: list[VectorNodeHandle] = []
    for command in item.path:
        for point_index, point in enumerate(command.points):
            role = (
                VectorNodeRole.CONTROL
                if command.kind
                in {VectorPathCommandKind.QUADRATIC, VectorPathCommandKind.CUBIC}
                and point_index < len(command.points) - 1
                else VectorNodeRole.ANCHOR
            )
            handles.append(VectorNodeHandle(len(handles), role, transform.map(point)))
    return tuple(handles)


def _move_handle(
    item: VectorObject,
    node_index: int,
    document_point: QPointF,
) -> VectorObject:
    """Return one object with exactly one semantic handle displaced."""
    inverse = item.transform.inverted()
    if inverse is None:
        return item
    local_point = inverse.map_point(document_point)
    if item.kind is VectorObjectKind.SHAPE:
        return _move_shape_handle(item, node_index, local_point)
    commands = list(item.path)
    current_index = 0
    for command_index, command in enumerate(commands):
        if node_index < current_index + len(command.points):
            point_index = node_index - current_index
            points = list(command.points)
            points[point_index] = QPointF(local_point)
            commands[command_index] = replace(command, points=tuple(points))
            all_points = tuple(point for value in commands for point in value.points)
            return replace(
                item,
                path=tuple(commands),
                local_bounds=_point_bounds(all_points),
            )
        current_index += len(command.points)
    return item


def _move_shape_handle(
    item: VectorObject,
    node_index: int,
    local_point: QPointF,
) -> VectorObject:
    """Resize one parametric shape against the opposing corner."""
    x, y, width, height = item.local_bounds
    corners = (
        QPointF(x, y),
        QPointF(x + width, y),
        QPointF(x + width, y + height),
        QPointF(x, y + height),
    )
    if not 0 <= node_index < len(corners):
        return item
    opposite = corners[(node_index + 2) % 4]
    bounds = QRectF(opposite, local_point).normalized()
    return replace(
        item,
        local_bounds=(bounds.x(), bounds.y(), bounds.width(), bounds.height()),
    )


def _point_bounds(points: tuple[QPointF, ...]) -> tuple[float, float, float, float]:
    """Return finite local bounds enclosing every command point."""
    left = min(point.x() for point in points)
    top = min(point.y() for point in points)
    right = max(point.x() for point in points)
    bottom = max(point.y() for point in points)
    return left, top, right - left, bottom - top
