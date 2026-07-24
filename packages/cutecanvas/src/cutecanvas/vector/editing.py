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
"""Atomic vector object commands routed through composition chronology."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace

from PySide6.QtCore import QRectF
from PySide6.QtGui import QTransform
from qpane.sdk.scene import LayerTransform
from qpane.sdk.vector import (
    VectorDocument,
    VectorObject,
    VectorObjectKind,
    VectorPathCommand,
    VectorShapeKind,
    VectorStyle,
    VectorTextContent,
)

from ..composition.edit_controller import CompositionEditController
from ..resources import ProjectResourceReference
from .store import VectorAssetStore


@dataclass(frozen=True, slots=True)
class VectorDocumentEdit:
    """Retain one complete immutable document transition."""

    scope_id: uuid.UUID
    layer_id: uuid.UUID
    before: VectorDocument
    after: VectorDocument

    @property
    def retained_bytes(self) -> int:
        """Estimate immutable command and control-point retention."""
        return 512 + self.before.retained_bytes + self.after.retained_bytes

    @property
    def retained_resources(self) -> tuple[ProjectResourceReference, ...]:
        """Retain the document while this command remains replayable."""
        return (ProjectResourceReference(self.before.vector_id),)


class VectorEditService:
    """Own validated vector document mutation and exact history replay."""

    def __init__(
        self,
        *,
        assets: VectorAssetStore,
        edits: CompositionEditController,
        changed: Callable[[uuid.UUID], None],
    ) -> None:
        """Bind vector authority, composition history, and presentation."""
        self._assets = assets
        self._edits = edits
        self._changed = changed
        edits.register_handler(
            VectorDocumentEdit,
            undo=self._undo,
            redo=self._redo,
        )

    def add_shape(
        self,
        scope_id: uuid.UUID,
        layer_id: uuid.UUID,
        vector_id: uuid.UUID,
        shape: VectorShapeKind,
        bounds: QRectF,
        style: VectorStyle,
    ) -> uuid.UUID | None:
        """Add one parametric shape as a single atomic edit."""
        item = VectorObject(
            uuid.uuid4(),
            VectorObjectKind.SHAPE,
            (bounds.x(), bounds.y(), bounds.width(), bounds.height()),
            LayerTransform(),
            style,
            shape_kind=VectorShapeKind(shape),
        )
        return (
            item.object_id
            if self._apply(
                scope_id, layer_id, vector_id, lambda document: document.add(item)
            )
            else None
        )

    def add_path(
        self,
        scope_id: uuid.UUID,
        layer_id: uuid.UUID,
        vector_id: uuid.UUID,
        commands: tuple[VectorPathCommand, ...],
        style: VectorStyle,
    ) -> uuid.UUID | None:
        """Add one durable command-based path as a single edit."""
        points = tuple(point for command in commands for point in command.points)
        if not points:
            return None
        left = min(point.x() for point in points)
        top = min(point.y() for point in points)
        right = max(point.x() for point in points)
        bottom = max(point.y() for point in points)
        item = VectorObject(
            uuid.uuid4(),
            VectorObjectKind.PATH,
            (left, top, right - left, bottom - top),
            LayerTransform(),
            style,
            path=commands,
        )
        return (
            item.object_id
            if self._apply(
                scope_id, layer_id, vector_id, lambda document: document.add(item)
            )
            else None
        )

    def add_text(
        self,
        scope_id: uuid.UUID,
        layer_id: uuid.UUID,
        vector_id: uuid.UUID,
        bounds: QRectF,
        content: VectorTextContent,
    ) -> uuid.UUID | None:
        """Add one editable semantic text object as a single edit."""
        if bounds.isEmpty():
            return None
        item = VectorObject(
            uuid.uuid4(),
            VectorObjectKind.TEXT,
            (bounds.x(), bounds.y(), bounds.width(), bounds.height()),
            LayerTransform(),
            VectorStyle(fill=None, stroke=None, stroke_width=0.0),
            text=content,
        )
        return (
            item.object_id
            if self._apply(
                scope_id,
                layer_id,
                vector_id,
                lambda document: document.add(item),
            )
            else None
        )

    def update_text(
        self,
        scope_id: uuid.UUID,
        layer_id: uuid.UUID,
        vector_id: uuid.UUID,
        object_id: uuid.UUID,
        *,
        bounds: QRectF | None = None,
        content: VectorTextContent | None = None,
    ) -> bool:
        """Replace semantic text content and/or its layout box atomically."""

        def mutate(document: VectorDocument) -> VectorDocument:
            """Return the revision with the requested semantic text fields."""
            item = document.object(object_id)
            if item is None or item.kind is not VectorObjectKind.TEXT:
                return document
            updated = replace(
                item,
                local_bounds=(
                    item.local_bounds
                    if bounds is None
                    else (bounds.x(), bounds.y(), bounds.width(), bounds.height())
                ),
                text=item.text if content is None else content,
            )
            return document.replace_object(updated)

        if bounds is not None and bounds.isEmpty():
            return False
        return self._apply(scope_id, layer_id, vector_id, mutate)

    def commit_document(
        self,
        scope_id: uuid.UUID,
        layer_id: uuid.UUID,
        before: VectorDocument,
        after: VectorDocument,
    ) -> bool:
        """Commit one controller-owned durable-base transition atomically."""
        if (
            before.vector_id != after.vector_id
            or before == after
            or self._assets.get(before.vector_id) != before
            or not self._assets.replace(after)
        ):
            return False
        self._edits.record_applied(
            VectorDocumentEdit(scope_id, layer_id, before, after)
        )
        self._changed(before.vector_id)
        return True

    def update_object(
        self,
        scope_id: uuid.UUID,
        layer_id: uuid.UUID,
        vector_id: uuid.UUID,
        object_id: uuid.UUID,
        *,
        transform: QTransform | None = None,
        style: VectorStyle | None = None,
    ) -> bool:
        """Replace selected object transform and/or style atomically."""

        def mutate(document: VectorDocument) -> VectorDocument:
            """Build the updated object without mutating prior revisions."""
            item = document.object(object_id)
            if item is None:
                return document
            updated = replace(
                item,
                transform=(
                    item.transform
                    if transform is None
                    else LayerTransform.from_qtransform(transform)
                ),
                style=item.style if style is None else style,
            )
            return document.replace_object(updated)

        return self._apply(scope_id, layer_id, vector_id, mutate)

    def remove_object(
        self,
        scope_id: uuid.UUID,
        layer_id: uuid.UUID,
        vector_id: uuid.UUID,
        object_id: uuid.UUID,
    ) -> bool:
        """Remove one object atomically."""
        return self._apply(
            scope_id,
            layer_id,
            vector_id,
            lambda document: document.remove(object_id),
        )

    def replace_object(
        self,
        scope_id: uuid.UUID,
        layer_id: uuid.UUID,
        vector_id: uuid.UUID,
        item: VectorObject,
    ) -> bool:
        """Commit one complete replacement object as a single history edit."""
        return self._apply(
            scope_id,
            layer_id,
            vector_id,
            lambda document: document.replace_object(item),
        )

    def reorder_object(
        self,
        scope_id: uuid.UUID,
        layer_id: uuid.UUID,
        vector_id: uuid.UUID,
        object_id: uuid.UUID,
        index: int,
    ) -> bool:
        """Move one object within document z-order atomically."""
        return self._apply(
            scope_id,
            layer_id,
            vector_id,
            lambda document: document.reorder(object_id, index),
        )

    def _apply(
        self,
        scope_id: uuid.UUID,
        layer_id: uuid.UUID,
        vector_id: uuid.UUID,
        mutation: Callable[[VectorDocument], VectorDocument],
    ) -> bool:
        """Apply and record one immutable document transition."""
        before = self._assets.get(vector_id)
        if before is None:
            return False
        after = mutation(before)
        if after == before or not self._assets.replace(after):
            return False
        self._edits.record_applied(
            VectorDocumentEdit(scope_id, layer_id, before, after)
        )
        self._changed(vector_id)
        return True

    def _undo(self, command: object) -> bool:
        """Restore one exact prior document revision."""
        return self._restore(command, use_after=False)

    def _redo(self, command: object) -> bool:
        """Restore one exact subsequent document revision."""
        return self._restore(command, use_after=True)

    def _restore(self, command: object, *, use_after: bool) -> bool:
        """Replay one retained immutable vector document."""
        if not isinstance(command, VectorDocumentEdit):
            return False
        document = command.after if use_after else command.before
        if self._assets.get(document.vector_id) is None:
            self._assets.restore(document)
        else:
            self._assets.replace(document)
        self._changed(document.vector_id)
        return True
