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
"""Vector tool policy and semantic gesture commit coordination."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF
from qpane.sdk.scene import SceneDescriptor
from qpane.sdk.vector import (
    VectorPathCommand,
    VectorPathCommandKind,
    VectorShapeKind,
    VectorStyle,
    object_contains,
)

from ..scene.layer_selection import SceneLayerSelectionController
from .editing import VectorEditService
from .selection import VectorObjectSelectionController
from .store import VectorAssetStore
from .targets import VectorAuthoringTarget, VectorAuthoringTargetResolver


class VectorInteractionController:
    """Own transient vector-tool options and route gestures to document owners."""

    def __init__(
        self,
        *,
        assets: VectorAssetStore,
        edits: VectorEditService,
        layer_selection: SceneLayerSelectionController,
        object_selection: VectorObjectSelectionController,
        current_scene: Callable[[], SceneDescriptor | None],
        options_changed: Callable[[], None],
        targets: VectorAuthoringTargetResolver,
    ) -> None:
        """Bind authoritative document, selection, and coordinate owners."""
        self._assets = assets
        self._edits = edits
        self._layer_selection = layer_selection
        self._object_selection = object_selection
        self._current_scene = current_scene
        self._options_changed = options_changed
        self._targets = targets
        self._shape = VectorShapeKind.RECTANGLE
        self._style = VectorStyle()

    @property
    def shape(self) -> VectorShapeKind:
        """Return the active parametric shape kind."""
        return self._shape

    @property
    def style(self) -> VectorStyle:
        """Return the immutable active vector style."""
        return self._style

    def set_shape(self, shape: VectorShapeKind) -> bool:
        """Replace the shape-tool kind and publish contextual UI state."""
        normalized = VectorShapeKind(shape)
        if normalized is self._shape:
            return False
        self._shape = normalized
        self._options_changed()
        return True

    def set_style(self, style: VectorStyle) -> bool:
        """Replace the immutable creation style."""
        normalized = VectorStyle(
            fill=style.fill,
            stroke=style.stroke,
            stroke_width=style.stroke_width,
            opacity=style.opacity,
            join=style.join,
            cap=style.cap,
            dash_pattern=style.dash_pattern,
            fill_rule=style.fill_rule,
        )
        if normalized == self._style:
            return False
        self._style = normalized
        self._options_changed()
        return True

    def panel_to_active_source(self, point: QPointF) -> QPointF | None:
        """Map a panel point into the selected editable vector layer."""
        target = self._target()
        if target is None:
            return None
        return self._targets.panel_to_document(target, point)

    def commit_shape(self, begin: QPointF, end: QPointF) -> uuid.UUID | None:
        """Commit one normalized parametric shape from local source points."""
        target = self._target()
        bounds = QRectF(begin, end).normalized()
        if target is None or bounds.isEmpty():
            return None
        layer_id, vector_id = target.layer_id, target.vector_id
        object_id = self._edits.add_shape(
            target.scene_id,
            layer_id,
            vector_id,
            self._shape,
            bounds,
            self._style,
        )
        if object_id is not None:
            self._object_selection.set(target.scene_id, layer_id, (object_id,))
        return object_id

    def commit_path(
        self,
        points: tuple[QPointF, ...],
        *,
        closed: bool,
    ) -> uuid.UUID | None:
        """Commit one polyline path while preserving every sampled node."""
        target = self._target()
        if target is None or len(points) < 2:
            return None
        commands = [
            VectorPathCommand(VectorPathCommandKind.MOVE, (QPointF(points[0]),))
        ]
        commands.extend(
            VectorPathCommand(VectorPathCommandKind.LINE, (QPointF(point),))
            for point in points[1:]
        )
        if closed and len(points) >= 3:
            commands.append(VectorPathCommand(VectorPathCommandKind.CLOSE))
        layer_id, vector_id = target.layer_id, target.vector_id
        object_id = self._edits.add_path(
            target.scene_id,
            layer_id,
            vector_id,
            tuple(commands),
            self._style,
        )
        if object_id is not None:
            self._object_selection.set(target.scene_id, layer_id, (object_id,))
        return object_id

    def select_at(self, panel_point: QPointF) -> bool:
        """Select the topmost exact vector object under a panel point."""
        target = self._target()
        source_point = self.panel_to_active_source(panel_point)
        if target is None or source_point is None:
            return False
        layer_id, vector_id = target.layer_id, target.vector_id
        document = self._assets.get(vector_id)
        if document is None:
            return False
        object_id = next(
            (
                item.object_id
                for item in reversed(document.objects)
                if object_contains(item, source_point)
            ),
            None,
        )
        return (
            self._object_selection.clear()
            if object_id is None
            else self._object_selection.set(target.scene_id, layer_id, (object_id,))
        )

    def _target(self) -> VectorAuthoringTarget | None:
        """Resolve selected direct or vector-mask authoring context."""
        scene = self._current_scene()
        selection = self._layer_selection.current
        if scene is None or selection is None or selection.scene_id != scene.scene_id:
            return None
        return self._targets.resolve(selection.layer_id)
