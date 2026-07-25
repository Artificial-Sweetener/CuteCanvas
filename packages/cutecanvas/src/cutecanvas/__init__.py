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
"""Expose the typed CuteCanvas editor facade and its authoring values."""

# ruff: noqa: F822, PLE0604, PLE0605

from __future__ import annotations

from importlib import import_module
from typing import Any

from qpane.sdk import types as _public_types
from qpane.sdk import vector as _vector_types

from . import types as _editor_types

_VECTOR_TYPE_EXPORTS = (
    "TextFontResolution",
    "VectorFillRule",
    "VectorNodeRole",
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

_RENDER_TYPE_EXPORTS = (
    "CacheMode",
    "ComparisonOrientation",
    "DiagnosticRecord",
    "OverlayState",
    "SceneSnapshotOverlayLayer",
    "SceneSnapshotOverlayState",
)

_AUTHOR_VECTOR_EXPORTS = (
    "VectorDocumentSnapshot",
    "VectorMaskSnapshot",
    "VectorNodeSelectionSnapshot",
    "VectorObjectSnapshot",
    "VectorSelectionSnapshot",
    "VectorTextEditSnapshot",
)

__all__ = [
    *_RENDER_TYPE_EXPORTS,
    *_editor_types.__all__,
    *_VECTOR_TYPE_EXPORTS,
    *_AUTHOR_VECTOR_EXPORTS,
    "BrushDynamics",
    "BrushOperation",
    "BrushPreset",
    "CloneStampAlignment",
    "CloneStampFacade",
    "CloneStampSampleMode",
    "CloneStampSource",
    "CloneStampState",
    "CloneStampTransform",
    "CanvasComparison",
    "CanvasContentKind",
    "CanvasContentReference",
    "CanvasInteractionMode",
    "CanvasDocument",
    "CanvasDocumentRuntime",
    "CanvasPresentation",
    "CanvasPresentationContext",
    "CanvasPresentationKind",
    "CanvasPresentationProvider",
    "CanvasProjectionHandle",
    "CanvasProjectionRequest",
    "CanvasProjectionResult",
    "CanvasProjectionStatus",
    "CanvasSessionSnapshot",
    "CanvasViewSession",
    "CanvasWorkspace",
    "Config",
    "CoverageShapeOptions",
    "CoverageFacade",
    "CuteCanvas",
    "CompositionCollection",
    "CompositionHandle",
    "CompositionPersistenceFacade",
    "EditorFacade",
    "EffectsFacade",
    "HistoryFacade",
    "LayerEffectHandle",
    "LayerHandle",
    "LayerPresentationEffect",
    "LayerPresentationEffectKind",
    "LayerPresentationStyle",
    "LayerGeometryMode",
    "LayerGeometryPolicy",
    "MaskInfo",
    "PlacedAssetMode",
    "PlacedAssetStatus",
    "ResolvedCanvasContent",
    "SelectionFacade",
    "SnapPolicy",
    "ToolFacade",
]
__all__ = sorted(set(__all__) - {"QPane"})

_AUTHOR_SYMBOLS: dict[str, tuple[str, str]] = {
    "__version__": ("cutecanvas._version", "version"),
    "CuteCanvas": ("cutecanvas.canvas", "CuteCanvas"),
    "CanvasComparison": ("cutecanvas.document", "CanvasComparison"),
    "CanvasContentKind": ("cutecanvas.document", "CanvasContentKind"),
    "CanvasContentReference": (
        "cutecanvas.document",
        "CanvasContentReference",
    ),
    "CanvasInteractionMode": (
        "cutecanvas.editor.interaction_policy",
        "CanvasInteractionMode",
    ),
    "CanvasDocument": ("cutecanvas.document", "CanvasDocument"),
    "CanvasDocumentRuntime": ("cutecanvas.runtime", "CanvasDocumentRuntime"),
    "CanvasPresentation": ("cutecanvas.document", "CanvasPresentation"),
    "CanvasPresentationKind": (
        "cutecanvas.document",
        "CanvasPresentationKind",
    ),
    "CanvasSessionSnapshot": ("cutecanvas.document", "CanvasSessionSnapshot"),
    "CanvasViewSession": ("cutecanvas.document", "CanvasViewSession"),
    "CanvasPresentationContext": (
        "cutecanvas.presentation",
        "CanvasPresentationContext",
    ),
    "CanvasPresentationProvider": (
        "cutecanvas.presentation",
        "CanvasPresentationProvider",
    ),
    "CanvasWorkspace": ("cutecanvas.presentation", "CanvasWorkspace"),
    "CanvasProjectionHandle": ("cutecanvas.projection", "CanvasProjectionHandle"),
    "CanvasProjectionRequest": ("cutecanvas.projection", "CanvasProjectionRequest"),
    "CanvasProjectionResult": ("cutecanvas.projection", "CanvasProjectionResult"),
    "CanvasProjectionStatus": ("cutecanvas.projection", "CanvasProjectionStatus"),
    "ResolvedCanvasContent": ("cutecanvas.document", "ResolvedCanvasContent"),
    "CompositionCollection": ("cutecanvas.facade.handles", "CompositionCollection"),
    "CompositionHandle": ("cutecanvas.facade.handles", "CompositionHandle"),
    "CompositionPersistenceFacade": (
        "cutecanvas.facade.persistence",
        "CompositionPersistenceFacade",
    ),
    "LayerHandle": ("cutecanvas.facade.handles", "LayerHandle"),
    "LayerEffectHandle": ("cutecanvas.facade.handles", "LayerEffectHandle"),
    "LayerGeometryMode": (
        "cutecanvas.composition.geometry_policy",
        "LayerGeometryMode",
    ),
    "LayerGeometryPolicy": (
        "cutecanvas.composition.geometry_policy",
        "LayerGeometryPolicy",
    ),
    "EditorFacade": ("cutecanvas.facade.editor", "EditorFacade"),
    "EffectsFacade": ("cutecanvas.facade.effects", "EffectsFacade"),
    "HistoryFacade": ("cutecanvas.facade.editor", "HistoryFacade"),
    "SelectionFacade": ("cutecanvas.facade.editor", "SelectionFacade"),
    "ToolFacade": ("cutecanvas.facade.editor", "ToolFacade"),
    "Config": ("cutecanvas.core.config", "Config"),
    "CoverageShapeOptions": ("cutecanvas.coverage", "CoverageShapeOptions"),
    "CoverageFacade": ("cutecanvas.facade.editor", "CoverageFacade"),
    "LayerPresentationEffect": ("qpane", "LayerPresentationEffect"),
    "LayerPresentationEffectKind": ("qpane", "LayerPresentationEffectKind"),
    "LayerPresentationStyle": ("qpane", "LayerPresentationStyle"),
    "SnapPolicy": ("cutecanvas.snapping", "SnapPolicy"),
    "BrushDynamics": ("cutecanvas.painting", "BrushDynamics"),
    "BrushOperation": ("cutecanvas.painting", "BrushOperation"),
    "BrushPreset": ("cutecanvas.painting", "BrushPreset"),
    "CloneStampAlignment": (
        "cutecanvas.painting.clone_model",
        "CloneStampAlignment",
    ),
    "CloneStampFacade": (
        "cutecanvas.facade.clone_stamp",
        "CloneStampFacade",
    ),
    "CloneStampSampleMode": (
        "cutecanvas.painting.clone_model",
        "CloneStampSampleMode",
    ),
    "CloneStampSource": (
        "cutecanvas.painting.clone_model",
        "CloneStampSource",
    ),
    "CloneStampState": (
        "cutecanvas.painting.clone_model",
        "CloneStampState",
    ),
    "CloneStampTransform": (
        "cutecanvas.painting.clone_model",
        "CloneStampTransform",
    ),
    "MaskInfo": ("cutecanvas.masks.workflow", "MaskInfo"),
    "PlacedAssetMode": ("cutecanvas.placed.model", "PlacedAssetMode"),
    "PlacedAssetStatus": ("cutecanvas.placed.model", "PlacedAssetStatus"),
}


def __getattr__(name: str) -> Any:
    """Resolve authoring values locally and rendering values through CuteCanvas."""
    target = _AUTHOR_SYMBOLS.get(name)
    if target is not None:
        value = getattr(import_module(target[0]), target[1])
    elif name in _editor_types.__all__:
        value = getattr(_editor_types, name)
    elif name in _RENDER_TYPE_EXPORTS:
        value = getattr(_public_types, name)
    elif name in _VECTOR_TYPE_EXPORTS:
        value = getattr(_vector_types, name)
    elif name in _AUTHOR_VECTOR_EXPORTS:
        value = getattr(import_module("cutecanvas.vector.public"), name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Return the complete lazy public surface."""
    return sorted(__all__)
