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
"""Detached public snapshots for authoritative vector documents."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QRectF

from qpane.sdk.vector import VectorDocument

from .public import (
    VectorDocumentSnapshot,
    VectorObjectSnapshot,
    VectorSelectionSnapshot,
)
from .selection import VectorObjectSelection


def document_state(
    scene_id: uuid.UUID,
    layer_id: uuid.UUID,
    document: VectorDocument,
) -> VectorDocumentSnapshot:
    """Return a fully detached public document revision."""
    return VectorDocumentSnapshot(
        scene_id=scene_id,
        layer_id=layer_id,
        vector_id=document.vector_id,
        revision=document.revision,
        objects=tuple(
            VectorObjectSnapshot(
                object_id=item.object_id,
                kind=item.kind,
                bounds=_rect(item.local_bounds),
                transform=item.transform.to_qtransform(),
                style=item.style,
                shape_kind=item.shape_kind,
                path=item.path,
                text=item.text,
            )
            for item in document.objects
        ),
    )


def selection_state(
    public_scene_id: uuid.UUID,
    selection: VectorObjectSelection,
) -> VectorSelectionSnapshot:
    """Return one detached public vector-object selection."""
    return VectorSelectionSnapshot(
        scene_id=public_scene_id,
        layer_id=selection.layer_id,
        object_ids=selection.object_ids,
    )


def _rect(bounds: tuple[float, float, float, float]) -> QRectF:
    """Return detached Qt rectangle geometry."""
    return QRectF(*bounds)
