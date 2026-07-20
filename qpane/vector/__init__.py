#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Resolution-independent vector document, rendering, and editing domain."""

from .model import VectorDocument, VectorObject
from .public import (
    QPaneTextFontResolution,
    QPaneVectorDocumentState,
    QPaneVectorMaskState,
    QPaneVectorNodeSelectionState,
    QPaneVectorObjectState,
    QPaneVectorSelectionState,
    QPaneVectorTextEditState,
    VectorFillRule,
    VectorNodeRole,
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
from .source_reference import VectorDocumentReference
from .store import VectorAssetStore

__all__ = (
    "QPaneTextFontResolution",
    "QPaneVectorDocumentState",
    "QPaneVectorMaskState",
    "QPaneVectorNodeSelectionState",
    "QPaneVectorObjectState",
    "QPaneVectorSelectionState",
    "QPaneVectorTextEditState",
    "VectorAssetStore",
    "VectorDocument",
    "VectorDocumentReference",
    "VectorFillRule",
    "VectorNodeRole",
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
