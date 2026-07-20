#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Shared semantic Qt drawing for immutable vector document revisions."""

from __future__ import annotations

import uuid
from collections.abc import Set as AbstractSet

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter, QPainterPath, QPainterPathStroker

from .geometry import object_local_path
from .model import VectorDocument, VectorObject
from .public import VectorObjectKind
from .style_adapter import brush_for_style, configure_stroker, pen_for_style
from .text_layout import SemanticTextLayoutCache, draw_semantic_text


def draw_vector_document(
    painter: QPainter,
    document: VectorDocument,
    object_ids: AbstractSet[uuid.UUID] | None = None,
    text_layouts: SemanticTextLayoutCache | None = None,
) -> None:
    """Draw one document through the caller's existing painter transform."""
    for item in document.objects:
        if object_ids is not None and item.object_id not in object_ids:
            continue
        painter.save()
        try:
            painter.setOpacity(item.style.opacity)
            if item.kind is VectorObjectKind.TEXT and item.text is not None:
                bounds = QRectF(*item.local_bounds)
                painter.setTransform(item.transform.to_qtransform(), True)
                if text_layouts is None:
                    draw_semantic_text(painter, item.text, bounds)
                else:
                    product = text_layouts.picture_product(item.text, bounds)
                    painter.drawPicture(0, 0, product.picture)
                continue
            painter.setBrush(brush_for_style(item.style))
            painter.setPen(pen_for_style(item.style))
            painter.setTransform(item.transform.to_qtransform(), True)
            painter.drawPath(object_local_path(item))
        finally:
            painter.restore()


def painted_object_path(
    item: VectorObject,
    text_layouts: SemanticTextLayoutCache | None = None,
) -> QPainterPath:
    """Return exact transformed fill and stroke geometry with visible alpha."""
    local_path = object_local_path(item, text_layouts)
    if item.kind is VectorObjectKind.TEXT:
        return item.transform.to_qtransform().map(local_path)
    painted = QPainterPath()
    style = item.style
    if style.opacity > 0.0 and style.fill is not None and style.fill.alpha() > 0:
        painted.addPath(local_path)
    if (
        style.opacity > 0.0
        and style.stroke is not None
        and style.stroke.alpha() > 0
        and style.stroke_width > 0.0
    ):
        stroker = QPainterPathStroker()
        configure_stroker(stroker, style)
        painted.addPath(stroker.createStroke(local_path))
    return item.transform.to_qtransform().map(painted)


def painted_document_path(
    document: VectorDocument,
    object_ids: AbstractSet[uuid.UUID] | None = None,
    text_layouts: SemanticTextLayoutCache | None = None,
) -> QPainterPath:
    """Return the union of visible semantic object geometry in document space."""
    path = QPainterPath()
    for item in document.objects:
        if object_ids is None or item.object_id in object_ids:
            path.addPath(painted_object_path(item, text_layouts))
    return path
