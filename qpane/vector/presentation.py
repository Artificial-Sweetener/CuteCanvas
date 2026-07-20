#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Detached public snapshots for authoritative vector documents."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QRectF

from .model import VectorDocument
from .public import (
    QPaneVectorDocumentState,
    QPaneVectorObjectState,
    QPaneVectorSelectionState,
)
from .selection import VectorObjectSelection


def document_state(
    scene_id: uuid.UUID,
    layer_id: uuid.UUID,
    document: VectorDocument,
) -> QPaneVectorDocumentState:
    """Return a fully detached public document revision."""
    return QPaneVectorDocumentState(
        scene_id=scene_id,
        layer_id=layer_id,
        vector_id=document.vector_id,
        revision=document.revision,
        objects=tuple(
            QPaneVectorObjectState(
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
) -> QPaneVectorSelectionState:
    """Return one detached public vector-object selection."""
    return QPaneVectorSelectionState(
        scene_id=public_scene_id,
        layer_id=selection.layer_id,
        object_ids=selection.object_ids,
    )


def _rect(bounds: tuple[float, float, float, float]) -> QRectF:
    """Return detached Qt rectangle geometry."""
    return QRectF(*bounds)
