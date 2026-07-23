#    QPane - High-performance PySide6 image viewer
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
"""Supported semantic vector values, geometry, drawing, and text layout."""

from ..vector import (
    VectorDocument,
    VectorFillRule,
    VectorObject,
    VectorObjectKind,
    VectorParagraphStyle,
    VectorPathCommand,
    VectorPathCommandKind,
    VectorShapeKind,
    VectorStrokeCap,
    VectorStrokeJoin,
    VectorStyle,
    VectorTextAlignment,
    VectorTextContent,
    VectorTextDirection,
    VectorTextSpan,
    VectorTextStyle,
)
from ..vector.drawing import draw_vector_document, painted_document_path
from ..vector.geometry import object_contains, object_path
from ..vector.public import TextFontResolution, VectorNodeRole
from ..vector.snapshot import VectorPresentationSnapshot
from ..vector.text_layout import SemanticTextLayoutCache, text_caret_rect

__all__ = (
    "SemanticTextLayoutCache",
    "TextFontResolution",
    "VectorDocument",
    "VectorFillRule",
    "VectorNodeRole",
    "VectorObject",
    "VectorObjectKind",
    "VectorParagraphStyle",
    "VectorPathCommand",
    "VectorPathCommandKind",
    "VectorPresentationSnapshot",
    "VectorShapeKind",
    "VectorStrokeCap",
    "VectorStrokeJoin",
    "VectorStyle",
    "VectorTextAlignment",
    "VectorTextContent",
    "VectorTextDirection",
    "VectorTextSpan",
    "VectorTextStyle",
    "draw_vector_document",
    "object_contains",
    "object_path",
    "painted_document_path",
    "text_caret_rect",
)
