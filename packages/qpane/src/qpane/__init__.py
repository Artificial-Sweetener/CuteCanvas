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
"""Expose QPane's focused viewer and declarative raster/vector rendering SDK."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "BlendMode",
    "CacheMode",
    "ClipCoordinateSpace",
    "ComparisonDividerState",
    "ComparisonOrientation",
    "ComparisonState",
    "Config",
    "CursorInteractionPort",
    "CursorTool",
    "DiagnosticRecord",
    "Diagnostics",
    "DiagnosticsSnapshot",
    "HybridCombineMode",
    "HybridDocument",
    "HybridPresentationStyle",
    "HybridRasterPrimitive",
    "HybridRasterSampler",
    "HybridSource",
    "HybridVectorPrimitive",
    "LayerClip",
    "LayerPresentationEffect",
    "LayerPresentationEffectKind",
    "LayerPresentationStyle",
    "LayerTransform",
    "LinkedGroup",
    "NavigationInteractionPort",
    "PanZoomTool",
    "PanelHitTest",
    "PointerDeviceKind",
    "PointerInputController",
    "PointerInputPort",
    "PointerPhase",
    "PointerSample",
    "QPane",
    "RasterBounds",
    "RasterHitTestProvider",
    "RasterProductPolicy",
    "RasterSource",
    "RasterSourcePatch",
    "RasterSourceProvider",
    "RenderLayer",
    "RenderScene",
    "SceneSnapshotOverlayLayer",
    "SceneSnapshotOverlayState",
    "SparseRasterSourceProvider",
    "ToolInputProfile",
    "ToolManager",
    "ToolManagerSignals",
    "TouchGestureArena",
    "TouchGestureKind",
    "TouchNavigationPort",
    "TouchNavigationSession",
    "VectorDocument",
    "VectorFillRule",
    "VectorObject",
    "VectorObjectKind",
    "VectorParagraphStyle",
    "VectorPathCommand",
    "VectorPathCommandKind",
    "VectorShapeKind",
    "VectorSource",
    "VectorStrokeCap",
    "VectorStrokeJoin",
    "VectorStyle",
    "VectorTextAlignment",
    "VectorTextContent",
    "VectorTextDirection",
    "VectorTextSpan",
    "VectorTextStyle",
    "ViewerCatalog",
    "ViewerCatalogEntry",
    "ViewerPlaceholderState",
    "ViewerPrefetchSnapshot",
    "ViewerTool",
    "ViewerToolSignals",
    "ViewportZoomMode",
    "ZoomMode",
    "__version__",
]

_LAZY_SYMBOLS: dict[str, tuple[str, str]] = {
    "QPane": ("qpane.viewer", "QPane"),
    "Config": ("qpane.core.config", "Config"),
    "CacheMode": ("qpane.types", "CacheMode"),
    "ClipCoordinateSpace": ("qpane.scene.model", "ClipCoordinateSpace"),
    "ComparisonDividerState": ("qpane.types", "ComparisonDividerState"),
    "ComparisonOrientation": ("qpane.types", "ComparisonOrientation"),
    "ComparisonState": ("qpane.types", "ComparisonState"),
    "ZoomMode": ("qpane.types", "ZoomMode"),
    "ViewportZoomMode": ("qpane.rendering.viewport", "ViewportZoomMode"),
    "BlendMode": ("qpane.scene.model", "BlendMode"),
    "LayerClip": ("qpane.scene.model", "LayerClip"),
    "LayerPresentationEffect": (
        "qpane.scene.presentation_effects",
        "LayerPresentationEffect",
    ),
    "LayerPresentationEffectKind": (
        "qpane.scene.presentation_effects",
        "LayerPresentationEffectKind",
    ),
    "LayerPresentationStyle": (
        "qpane.scene.presentation_effects",
        "LayerPresentationStyle",
    ),
    "LayerTransform": ("qpane.scene.affine", "LayerTransform"),
    "PanelHitTest": ("qpane.rendering.coordinates", "PanelHitTest"),
    "PointerDeviceKind": ("qpane.interaction", "PointerDeviceKind"),
    "PointerInputController": ("qpane.interaction", "PointerInputController"),
    "PointerInputPort": ("qpane.interaction", "PointerInputPort"),
    "PointerPhase": ("qpane.interaction", "PointerPhase"),
    "PointerSample": ("qpane.interaction", "PointerSample"),
    "CursorInteractionPort": ("qpane.interaction", "CursorInteractionPort"),
    "CursorTool": ("qpane.interaction", "CursorTool"),
    "DiagnosticRecord": ("qpane.types", "DiagnosticRecord"),
    "Diagnostics": ("qpane.core", "Diagnostics"),
    "DiagnosticsSnapshot": ("qpane.core", "DiagnosticsSnapshot"),
    "NavigationInteractionPort": (
        "qpane.interaction",
        "NavigationInteractionPort",
    ),
    "PanZoomTool": ("qpane.interaction", "PanZoomTool"),
    "ToolInputProfile": ("qpane.interaction", "ToolInputProfile"),
    "ToolManager": ("qpane.interaction", "ToolManager"),
    "ToolManagerSignals": ("qpane.interaction", "ToolManagerSignals"),
    "TouchGestureArena": ("qpane.interaction", "TouchGestureArena"),
    "TouchGestureKind": ("qpane.interaction", "TouchGestureKind"),
    "TouchNavigationPort": ("qpane.interaction", "TouchNavigationPort"),
    "TouchNavigationSession": ("qpane.interaction", "TouchNavigationSession"),
    "ViewerTool": ("qpane.interaction", "ViewerTool"),
    "ViewerToolSignals": ("qpane.interaction", "ViewerToolSignals"),
    "ViewerCatalog": ("qpane.catalog", "ViewerCatalog"),
    "ViewerCatalogEntry": ("qpane.catalog", "ViewerCatalogEntry"),
    "ViewerPlaceholderState": ("qpane.catalog", "ViewerPlaceholderState"),
    "ViewerPrefetchSnapshot": ("qpane.catalog", "ViewerPrefetchSnapshot"),
    "LinkedGroup": ("qpane.types", "LinkedGroup"),
    "HybridCombineMode": ("qpane.hybrid", "HybridCombineMode"),
    "HybridDocument": ("qpane.hybrid", "HybridDocument"),
    "HybridPresentationStyle": ("qpane.hybrid", "HybridPresentationStyle"),
    "HybridRasterPrimitive": ("qpane.hybrid", "HybridRasterPrimitive"),
    "HybridRasterSampler": ("qpane.hybrid", "HybridRasterSampler"),
    "HybridVectorPrimitive": ("qpane.hybrid", "HybridVectorPrimitive"),
    "HybridSource": ("qpane.rendering.sdk", "HybridSource"),
    "RasterBounds": ("qpane.scene.raster", "RasterBounds"),
    "RasterProductPolicy": (
        "qpane.scene.source_capabilities",
        "RasterProductPolicy",
    ),
    "RasterSourcePatch": (
        "qpane.scene.source_capabilities",
        "RasterSourcePatch",
    ),
    "RasterHitTestProvider": ("qpane.rendering.sdk", "RasterHitTestProvider"),
    "RasterSource": ("qpane.rendering.sdk", "RasterSource"),
    "RasterSourceProvider": ("qpane.rendering.sdk", "RasterSourceProvider"),
    "RenderLayer": ("qpane.rendering.sdk", "RenderLayer"),
    "RenderScene": ("qpane.rendering.sdk", "RenderScene"),
    "SceneSnapshotOverlayLayer": (
        "qpane.types",
        "SceneSnapshotOverlayLayer",
    ),
    "SceneSnapshotOverlayState": (
        "qpane.types",
        "SceneSnapshotOverlayState",
    ),
    "SparseRasterSourceProvider": (
        "qpane.rendering.sdk",
        "SparseRasterSourceProvider",
    ),
    "VectorSource": ("qpane.rendering.sdk", "VectorSource"),
    "VectorDocument": ("qpane.vector", "VectorDocument"),
    "VectorObject": ("qpane.vector", "VectorObject"),
    "VectorFillRule": ("qpane.vector", "VectorFillRule"),
    "VectorObjectKind": ("qpane.vector", "VectorObjectKind"),
    "VectorParagraphStyle": ("qpane.vector", "VectorParagraphStyle"),
    "VectorPathCommand": ("qpane.vector", "VectorPathCommand"),
    "VectorPathCommandKind": ("qpane.vector", "VectorPathCommandKind"),
    "VectorShapeKind": ("qpane.vector", "VectorShapeKind"),
    "VectorStrokeCap": ("qpane.vector", "VectorStrokeCap"),
    "VectorStrokeJoin": ("qpane.vector", "VectorStrokeJoin"),
    "VectorStyle": ("qpane.vector", "VectorStyle"),
    "VectorTextAlignment": ("qpane.vector", "VectorTextAlignment"),
    "VectorTextContent": ("qpane.vector", "VectorTextContent"),
    "VectorTextDirection": ("qpane.vector", "VectorTextDirection"),
    "VectorTextSpan": ("qpane.vector", "VectorTextSpan"),
    "VectorTextStyle": ("qpane.vector", "VectorTextStyle"),
    "__version__": ("qpane._version", "version"),
}


def __getattr__(name: str) -> Any:
    """Load public values without importing the widget or Qt workers eagerly."""
    target = _LAZY_SYMBOLS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(target[0]), target[1])
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Return the complete lazy public surface."""
    return sorted(__all__)
