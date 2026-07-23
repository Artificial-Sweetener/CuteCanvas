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
"""Resolution-independent vector representation and rendering values."""

from .model import VectorDocument, VectorObject
from .public import (
    VectorFillRule,
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

__all__ = (
    "VectorDocument",
    "VectorFillRule",
    "VectorObject",
    "VectorObjectKind",
    "VectorParagraphStyle",
    "VectorPathCommand",
    "VectorPathCommandKind",
    "VectorShapeKind",
    "VectorStrokeCap",
    "VectorStrokeJoin",
    "VectorStyle",
    "VectorTextAlignment",
    "VectorTextContent",
    "VectorTextDirection",
    "VectorTextSpan",
    "VectorTextStyle",
)
