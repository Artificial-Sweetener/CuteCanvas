#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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
    """QPane should expose only its viewer and rendering SDK contract."""
    expected = {
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
        "CuteCanvas",
        "ControlMode",
        "EditorCapability",
        "EditorIntent",
        "PixelSelectionMode",
        "PaintTargetKind",
        "FloatingPixelMode",
        "MaskInfo",
        "PlacedAssetMode",
        "PlacedAssetStatus",
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
        assert editor.catalog() is not None
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
