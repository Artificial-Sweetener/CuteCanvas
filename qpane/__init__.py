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

"""Expose the host-facing QPane package surface via lazy-loaded collaborators."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "BrushDynamics",
    "BrushOperation",
    "BrushPreset",
    "CacheMode",
    "CatalogEntry",
    "CatalogMutationEvent",
    "CatalogSnapshot",
    "ComparisonDividerState",
    "ComparisonOrientation",
    "ComparisonState",
    "CompositionEntry",
    "CompositionLayerEntry",
    "CompositionSnapshot",
    "Config",
    "ControlMode",
    "DiagnosticRecord",
    "DiagnosticsDomain",
    "EditorCapability",
    "EditorIntent",
    "ExtensionTool",
    "ExtensionToolSignals",
    "FloatingPixelMode",
    "LinkedGroup",
    "MaskInfo",
    "MaskSavedPayload",
    "OverlayState",
    "PaintTargetKind",
    "PixelSelectionMode",
    "PlacedAssetMode",
    "PlacedAssetStatus",
    "PlaceholderScaleMode",
    "QPane",
    "QPaneCatalogImageLayerRequest",
    "QPaneCompositionPolicy",
    "QPaneEditorOperationState",
    "QPaneEditorPolicy",
    "QPaneFloatingPixelEditState",
    "QPaneLayerInteractionPolicy",
    "QPaneLayerSelectionState",
    "QPanePaintTargetState",
    "QPanePixelSelectionState",
    "QPanePlacedAssetState",
    "QPaneRasterSurfaceState",
    "QPaneScene",
    "QPaneSceneClip",
    "QPaneSceneHit",
    "QPaneSceneLayer",
    "QPaneSceneOverlayLayer",
    "QPaneSceneOverlayState",
    "QPaneSceneRequest",
    "QPaneSceneTemplate",
    "QPaneSceneTemplateBindings",
    "QPaneTemplateLayer",
    "QPaneTextFontResolution",
    "QPaneVectorDocumentState",
    "QPaneVectorMaskState",
    "QPaneVectorNodeSelectionState",
    "QPaneVectorObjectState",
    "QPaneVectorSelectionState",
    "QPaneVectorTextEditState",
    "RasterExtentPolicy",
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
    "ZoomMode",
    "__version__",
]
_LAZY_SYMBOLS: dict[str, tuple[str, str]] = {
    "QPane": ("qpane.qpane", "QPane"),
    "Config": ("qpane.core.config", "Config"),
    "CatalogMutationEvent": ("qpane.catalog.catalog", "CatalogMutationEvent"),
    "CacheMode": ("qpane.types", "CacheMode"),
    "PlaceholderScaleMode": ("qpane.types", "PlaceholderScaleMode"),
    "ZoomMode": ("qpane.types", "ZoomMode"),
    "DiagnosticsDomain": ("qpane.types", "DiagnosticsDomain"),
    "EditorCapability": ("qpane.types", "EditorCapability"),
    "EditorIntent": ("qpane.types", "EditorIntent"),
    "ControlMode": ("qpane.types", "ControlMode"),
    "ComparisonOrientation": ("qpane.types", "ComparisonOrientation"),
    "CatalogEntry": ("qpane.types", "CatalogEntry"),
    "LinkedGroup": ("qpane.types", "LinkedGroup"),
    "ComparisonState": ("qpane.types", "ComparisonState"),
    "ComparisonDividerState": ("qpane.types", "ComparisonDividerState"),
    "CompositionEntry": ("qpane.types", "CompositionEntry"),
    "CompositionLayerEntry": ("qpane.types", "CompositionLayerEntry"),
    "CompositionSnapshot": ("qpane.types", "CompositionSnapshot"),
    "DiagnosticRecord": ("qpane.types", "DiagnosticRecord"),
    "OverlayState": ("qpane.types", "OverlayState"),
    "PixelSelectionMode": ("qpane.types", "PixelSelectionMode"),
    "PaintTargetKind": ("qpane.types", "PaintTargetKind"),
    "BrushDynamics": ("qpane.painting", "BrushDynamics"),
    "BrushOperation": ("qpane.painting", "BrushOperation"),
    "BrushPreset": ("qpane.painting", "BrushPreset"),
    "PlacedAssetMode": ("qpane.placed.model", "PlacedAssetMode"),
    "PlacedAssetStatus": ("qpane.placed.model", "PlacedAssetStatus"),
    "FloatingPixelMode": ("qpane.types", "FloatingPixelMode"),
    "MaskInfo": ("qpane.types", "MaskInfo"),
    "MaskSavedPayload": ("qpane.types", "MaskSavedPayload"),
    "CatalogSnapshot": ("qpane.types", "CatalogSnapshot"),
    "QPaneScene": ("qpane.types", "QPaneScene"),
    "QPaneSceneLayer": ("qpane.types", "QPaneSceneLayer"),
    "QPaneSceneRequest": ("qpane.types", "QPaneSceneRequest"),
    "QPaneCatalogImageLayerRequest": ("qpane.types", "QPaneCatalogImageLayerRequest"),
    "QPaneCompositionPolicy": ("qpane.types", "QPaneCompositionPolicy"),
    "QPaneLayerInteractionPolicy": ("qpane.types", "QPaneLayerInteractionPolicy"),
    "QPaneEditorOperationState": ("qpane.types", "QPaneEditorOperationState"),
    "QPaneEditorPolicy": ("qpane.types", "QPaneEditorPolicy"),
    "QPaneLayerSelectionState": ("qpane.types", "QPaneLayerSelectionState"),
    "QPaneFloatingPixelEditState": (
        "qpane.types",
        "QPaneFloatingPixelEditState",
    ),
    "QPanePixelSelectionState": ("qpane.types", "QPanePixelSelectionState"),
    "QPanePlacedAssetState": ("qpane.types", "QPanePlacedAssetState"),
    "QPanePaintTargetState": ("qpane.types", "QPanePaintTargetState"),
    "QPaneRasterSurfaceState": ("qpane.types", "QPaneRasterSurfaceState"),
    "RasterExtentPolicy": ("qpane.types", "RasterExtentPolicy"),
    "QPaneSceneTemplate": ("qpane.types", "QPaneSceneTemplate"),
    "QPaneTemplateLayer": ("qpane.types", "QPaneTemplateLayer"),
    "QPaneSceneTemplateBindings": ("qpane.types", "QPaneSceneTemplateBindings"),
    "QPaneSceneClip": ("qpane.types", "QPaneSceneClip"),
    "QPaneSceneHit": ("qpane.types", "QPaneSceneHit"),
    "QPaneSceneOverlayState": ("qpane.types", "QPaneSceneOverlayState"),
    "QPaneSceneOverlayLayer": ("qpane.types", "QPaneSceneOverlayLayer"),
    "QPaneVectorDocumentState": ("qpane.vector", "QPaneVectorDocumentState"),
    "QPaneTextFontResolution": ("qpane.vector", "QPaneTextFontResolution"),
    "QPaneVectorMaskState": ("qpane.vector", "QPaneVectorMaskState"),
    "QPaneVectorNodeSelectionState": (
        "qpane.vector",
        "QPaneVectorNodeSelectionState",
    ),
    "QPaneVectorObjectState": ("qpane.vector", "QPaneVectorObjectState"),
    "QPaneVectorSelectionState": ("qpane.vector", "QPaneVectorSelectionState"),
    "QPaneVectorTextEditState": ("qpane.vector", "QPaneVectorTextEditState"),
    "VectorFillRule": ("qpane.vector", "VectorFillRule"),
    "VectorObjectKind": ("qpane.vector", "VectorObjectKind"),
    "VectorNodeRole": ("qpane.vector", "VectorNodeRole"),
    "VectorPathCommand": ("qpane.vector", "VectorPathCommand"),
    "VectorPathCommandKind": ("qpane.vector", "VectorPathCommandKind"),
    "VectorShapeKind": ("qpane.vector", "VectorShapeKind"),
    "VectorStrokeCap": ("qpane.vector", "VectorStrokeCap"),
    "VectorStrokeJoin": ("qpane.vector", "VectorStrokeJoin"),
    "VectorStyle": ("qpane.vector", "VectorStyle"),
    "VectorParagraphStyle": ("qpane.vector", "VectorParagraphStyle"),
    "VectorTextAlignment": ("qpane.vector", "VectorTextAlignment"),
    "VectorTextContent": ("qpane.vector", "VectorTextContent"),
    "VectorTextDirection": ("qpane.vector", "VectorTextDirection"),
    "VectorTextSpan": ("qpane.vector", "VectorTextSpan"),
    "VectorTextStyle": ("qpane.vector", "VectorTextStyle"),
    "ExtensionToolSignals": ("qpane.tools.base", "ExtensionToolSignals"),
    "ExtensionTool": ("qpane.tools.base", "ExtensionTool"),
    "__version__": ("qpane._version", "version"),
}


def __getattr__(name: str) -> Any:
    """Lazily import public symbols to keep ``import qpane`` lightweight."""
    target = _LAZY_SYMBOLS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__} has no attribute {name}")
    module = import_module(target[0])
    value = getattr(module, target[1])
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Return the sorted public attributes including lazy-loaded entries."""
    return sorted(__all__ + [key for key in globals() if not key.startswith("_")])
