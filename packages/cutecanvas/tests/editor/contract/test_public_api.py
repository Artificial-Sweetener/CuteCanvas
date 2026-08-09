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
"""Ensure both independently published packages expose focused APIs."""

from __future__ import annotations

import cutecanvas
import pytest
import qpane
from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QColor, QImage


def test_qpane_public_api_symbols() -> None:
    """QPane should expose only its viewer, rendering, and execution contract."""
    expected = {
        "BackendSubmission",
        "BilinearLayerTransform",
        "BlendMode",
        "CacheMode",
        "CancellationToken",
        "ClipCoordinateSpace",
        "CompletionDispatcher",
        "ComparisonDividerState",
        "ComparisonOrientation",
        "ComparisonState",
        "Config",
        "CursorInteractionPort",
        "CursorTool",
        "DefaultExecutionPolicy",
        "DelayHandle",
        "DelayScheduler",
        "DiagnosticRecord",
        "DiagnosticsSubscription",
        "Diagnostics",
        "DiagnosticsSnapshot",
        "ExecutionBackend",
        "ExecutionBackendCapabilities",
        "ExecutionDiagnosticsProvider",
        "ExecutionFailurePhase",
        "ExecutionHandle",
        "ExecutionJob",
        "ExecutionLeaseRelease",
        "ExecutionOutcome",
        "ExecutionProgressReporter",
        "ExecutionRejected",
        "ExecutionRejectionReason",
        "ExecutionRequest",
        "ExecutionUrgency",
        "ExecutionRequirements",
        "ExecutionResource",
        "ExecutionRuntime",
        "ExecutionScope",
        "ExecutionSnapshot",
        "ExecutionState",
        "ExecutionTagValue",
        "ExecutionTaskContext",
        "ExecutionTimings",
        "HybridCombineMode",
        "HybridDocument",
        "HybridPresentationStyle",
        "HybridRasterPrimitive",
        "HybridRasterSampler",
        "HybridSource",
        "HybridVectorPrimitive",
        "IncompleteRowAlignment",
        "InspectionRegion",
        "InspectionStateStore",
        "InspectionTarget",
        "InspectionUpdate",
        "InspectionViewState",
        "InspectionZoomMode",
        "InlineDispatcher",
        "LayerClip",
        "LayerLocalPoint",
        "LayerMapping",
        "LayerPresentationEffect",
        "LayerPresentationEffectKind",
        "LayerPresentationStyle",
        "LayerTransform",
        "LayerSourcePoint",
        "LinkedGroup",
        "NavigationInteractionPort",
        "OutboundDragPayload",
        "OutboundMimeItem",
        "PanZoomTool",
        "PanelHitTest",
        "PanelPoint",
        "PointerDeviceKind",
        "PointerInputController",
        "PointerInputPort",
        "PointerPhase",
        "PointerSample",
        "PiecewiseLayerTransform",
        "ProjectedViewport",
        "ProjectiveLayerTransform",
        "QPane",
        "QtDelayScheduler",
        "QtOwnerDispatcher",
        "RasterBounds",
        "RasterHitTestProvider",
        "RasterProductPolicy",
        "RasterSource",
        "RasterSourcePatch",
        "RasterSourceProvider",
        "ResponsiveGridLayout",
        "ResponsiveGridPolicy",
        "ResponsiveGridSnapshot",
        "ResponsiveGridTopology",
        "RenderLayer",
        "RenderScene",
        "RetryCategorySnapshot",
        "RetryContext",
        "RetryController",
        "RetryPolicy",
        "RetrySchedulingError",
        "RetrySnapshot",
        "SceneSnapshotOverlayLayer",
        "SceneSnapshotOverlayState",
        "SceneCoordinateSystem",
        "ScenePoint",
        "SparseRasterSourceProvider",
        "ToolInputProfile",
        "ToolManager",
        "ToolManagerSignals",
        "TouchGestureArena",
        "TouchGestureKind",
        "TouchNavigationPort",
        "TouchNavigationSession",
        "TriangularLayerMappingPatch",
        "TileSizeSetting",
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
        "capture_inspection",
        "create_default_execution_runtime",
        "create_native_execution_runtime",
        "execution_detail_records",
        "execution_summary_records",
        "project_inspection",
        "retry_detail_records",
        "retry_summary_records",
    }
    assert set(qpane.__all__) == expected
    for symbol in expected:
        assert hasattr(qpane, symbol)


def test_cutecanvas_public_api_symbols() -> None:
    """CuteCanvas should add editor concepts without exporting QPane's widget."""
    expected = {
        "BrushDynamics",
        "BrushOperation",
        "BrushPreset",
        "CoverageCoordinateSpace",
        "CoverageFacade",
        "CanvasComparison",
        "CanvasContentKind",
        "CanvasContentReference",
        "CanvasDocument",
        "CanvasOverlayDrawFn",
        "CanvasDisplayScale",
        "CanvasOverlayState",
        "CanvasRenderVariant",
        "CanvasViewportInteraction",
        "CanvasViewportSource",
        "CanvasViewportSpec",
        "DragSubject",
        "DiagnosticsSubscription",
        "DocumentPersistenceSnapshot",
        "ExecutionBackend",
        "ExecutionRuntime",
        "ExecutionSnapshot",
        "EmbeddedImageExportSnapshot",
        "CanvasInteractionMode",
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
        "CloneStampTransform",
        "CuteCanvas",
        "ControlMode",
        "EditorCapability",
        "EditorIntent",
        "PixelSelectionMode",
        "PaintTargetKind",
        "FloatingPixelMode",
        "MaskInfo",
        "MaskExportSnapshot",
        "OutboundDragPayload",
        "OutboundMimeItem",
        "OutboundMimeProvider",
        "PlacedAssetMode",
        "PlacedAssetStatus",
        "ResolvedCanvasContent",
        "warmSamDependencies",
    }
    assert expected.issubset(set(cutecanvas.__all__))
    assert "QPane" not in cutecanvas.__all__
    for symbol in expected:
        assert hasattr(cutecanvas, symbol)


def test_qpane_mounts_a_scene_through_the_public_sdk(qapp) -> None:
    """The standalone viewer should render its own public scene model."""
    image = QImage(QSize(64, 48), QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor("royalblue"))
    source = qpane.RasterSource.from_image(image)
    scene = qpane.RenderScene(
        canvas=QRectF(0.0, 0.0, 64.0, 48.0),
        layers=(qpane.RenderLayer(source),),
    )
    viewer = qpane.QPane()
    try:
        assert viewer.setScene(scene)
        assert viewer.scene() == scene
        assert viewer.currentZoom() > 0.0
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_cutecanvas_accessors_remain_curated(qapp) -> None:
    """The editor facade should expose supported boundaries, not internals."""
    editor = cutecanvas.CuteCanvas(features=())
    try:
        assert editor.editor.compositions is not None
        assert editor.view() is not None
        assert editor.diagnostics() is not None
        assert editor.availableControlModes()
        assert editor.maskFeatureAvailable() is False
        assert editor.samFeatureAvailable() is False
        with pytest.raises(AttributeError):
            _ = editor.tools  # type: ignore[attr-defined]
        with pytest.raises(AttributeError):
            _ = editor.masks  # type: ignore[attr-defined]
    finally:
        editor.deleteLater()
        qapp.processEvents()
