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
import uuid
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget

from .catalog import ViewerCatalog as ViewerCatalog
from .catalog import ViewerCatalogEntry as ViewerCatalogEntry
from .catalog import ViewerPlaceholderState as ViewerPlaceholderState
from .catalog import ViewerPrefetchSnapshot as ViewerPrefetchSnapshot
from .concurrency import TaskExecutorProtocol, ThreadPolicy
from .core import Config as Config
from .core import Diagnostics as Diagnostics
from .core import DiagnosticsProvider, OverlayDrawFn, SceneOverlayDrawFn
from .core import DiagnosticsSnapshot as DiagnosticsSnapshot
from .hybrid import HybridCombineMode as HybridCombineMode
from .hybrid import HybridDocument as HybridDocument
from .hybrid import HybridPresentationStyle as HybridPresentationStyle
from .hybrid import HybridRasterPrimitive as HybridRasterPrimitive
from .hybrid import HybridRasterSampler as HybridRasterSampler
from .hybrid import HybridVectorPrimitive as HybridVectorPrimitive
from .inspection import InspectionRegion as InspectionRegion
from .inspection import InspectionStateStore as InspectionStateStore
from .inspection import InspectionTarget as InspectionTarget
from .inspection import InspectionUpdate as InspectionUpdate
from .inspection import InspectionViewState as InspectionViewState
from .inspection import InspectionZoomMode as InspectionZoomMode
from .inspection import ProjectedViewport as ProjectedViewport
from .inspection import capture_inspection as capture_inspection
from .inspection import project_inspection as project_inspection
from .interaction import CursorInteractionPort as CursorInteractionPort
from .interaction import CursorTool as CursorTool
from .interaction import NavigationInteractionPort as NavigationInteractionPort
from .interaction import PanZoomTool as PanZoomTool
from .interaction import PointerDeviceKind as PointerDeviceKind
from .interaction import PointerInputController as PointerInputController
from .interaction import PointerInputPort as PointerInputPort
from .interaction import PointerPhase as PointerPhase
from .interaction import PointerSample as PointerSample
from .interaction import ToolInputProfile as ToolInputProfile
from .interaction import ToolManager as ToolManager
from .interaction import ToolManagerSignals as ToolManagerSignals
from .interaction import TouchGestureArena as TouchGestureArena
from .interaction import TouchGestureKind as TouchGestureKind
from .interaction import TouchNavigationPort as TouchNavigationPort
from .interaction import TouchNavigationSession as TouchNavigationSession
from .interaction import ViewerTool as ViewerTool
from .interaction import ViewerToolSignals as ViewerToolSignals
from .rendering.coordinates import PanelHitTest as PanelHitTest
from .rendering.scene_coordinates import LayerLocalPoint as LayerLocalPoint
from .rendering.scene_coordinates import LayerSourcePoint as LayerSourcePoint
from .rendering.scene_coordinates import PanelPoint as PanelPoint
from .rendering.scene_coordinates import SceneCoordinateSystem as SceneCoordinateSystem
from .rendering.scene_coordinates import ScenePoint as ScenePoint
from .rendering.sdk import (
    HybridSource as HybridSource,
)
from .rendering.sdk import (
    RasterHitTestProvider as RasterHitTestProvider,
)
from .rendering.sdk import (
    RasterSource as RasterSource,
)
from .rendering.sdk import (
    RasterSourceProvider as RasterSourceProvider,
)
from .rendering.sdk import (
    RenderLayer as RenderLayer,
)
from .rendering.sdk import (
    RenderScene as RenderScene,
)
from .rendering.sdk import (
    SparseRasterSourceProvider as SparseRasterSourceProvider,
)
from .rendering.sdk import (
    VectorSource as VectorSource,
)
from .rendering.viewport import ViewportZoomMode as ViewportZoomMode
from .scene.affine import LayerTransform as LayerTransform
from .scene.model import (
    BlendMode as BlendMode,
)
from .scene.model import (
    ClipCoordinateSpace as ClipCoordinateSpace,
)
from .scene.model import (
    LayerClip as LayerClip,
)
from .scene.presentation_effects import (
    LayerPresentationEffect as LayerPresentationEffect,
)
from .scene.presentation_effects import (
    LayerPresentationEffectKind as LayerPresentationEffectKind,
)
from .scene.presentation_effects import (
    LayerPresentationStyle as LayerPresentationStyle,
)
from .scene.raster import RasterBounds as RasterBounds
from .scene.render_plan import SceneRenderPlan
from .scene.source_capabilities import (
    RasterProductPolicy as RasterProductPolicy,
)
from .scene.source_capabilities import (
    RasterSourcePatch as RasterSourcePatch,
)
from .sdk.ui import OutboundDragPayload as OutboundDragPayload
from .sdk.ui import OutboundMimeItem as OutboundMimeItem
from .types import CacheMode as CacheMode
from .types import ComparisonDividerState as ComparisonDividerState
from .types import ComparisonOrientation as ComparisonOrientation
from .types import ComparisonState as ComparisonState
from .types import DiagnosticRecord as DiagnosticRecord
from .types import LinkedGroup as LinkedGroup
from .types import SceneSnapshotOverlayLayer as SceneSnapshotOverlayLayer
from .types import SceneSnapshotOverlayState as SceneSnapshotOverlayState
from .types import ZoomMode as ZoomMode
from .vector import (
    VectorDocument as VectorDocument,
)
from .vector import (
    VectorFillRule as VectorFillRule,
)
from .vector import (
    VectorObject as VectorObject,
)
from .vector import (
    VectorObjectKind as VectorObjectKind,
)
from .vector import (
    VectorParagraphStyle as VectorParagraphStyle,
)
from .vector import (
    VectorPathCommand as VectorPathCommand,
)
from .vector import (
    VectorPathCommandKind as VectorPathCommandKind,
)
from .vector import (
    VectorShapeKind as VectorShapeKind,
)
from .vector import (
    VectorStrokeCap as VectorStrokeCap,
)
from .vector import (
    VectorStrokeJoin as VectorStrokeJoin,
)
from .vector import (
    VectorStyle as VectorStyle,
)
from .vector import (
    VectorTextAlignment as VectorTextAlignment,
)
from .vector import (
    VectorTextContent as VectorTextContent,
)
from .vector import (
    VectorTextDirection as VectorTextDirection,
)
from .vector import (
    VectorTextSpan as VectorTextSpan,
)
from .vector import (
    VectorTextStyle as VectorTextStyle,
)

__version__: str

class QPane(QWidget):
    sceneChanged: Signal
    zoomChanged: Signal
    controlModeChanged: Signal
    dragOutRequested: Signal
    diagnosticsOverlayToggled: Signal
    diagnosticsDomainToggled: Signal
    catalogChanged: Signal
    catalogSelectionChanged: Signal
    comparisonChanged: Signal
    linkGroupsChanged: Signal
    placeholderChanged: Signal
    settings: Config
    CONTROL_MODE_PANZOOM: str
    CONTROL_MODE_CURSOR: str

    def __init__(
        self,
        *,
        config: Config | None = ...,
        task_executor: TaskExecutorProtocol | None = ...,
        thread_policy: ThreadPolicy | Mapping[str, Any] | None = ...,
    ) -> None: ...
    def setScene(self, scene: RenderScene | None, *, fit: bool = ...) -> bool: ...
    def scene(self) -> RenderScene | None: ...
    @property
    def currentImage(self) -> QImage | None: ...
    @property
    def currentImagePath(self) -> Path | None: ...
    def copyCurrentImageToClipboard(self) -> bool: ...
    def setImage(self, image: QImage, *, fit: bool = ...) -> RasterSource: ...
    def clear(self) -> None: ...
    def setZoomFit(self) -> None: ...
    def setZoom1To1(self, anchor: QPointF | None = ...) -> None: ...
    def applyZoom(self, zoom: float, anchor: QPointF | None = ...) -> None: ...
    def currentZoom(self) -> float: ...
    def currentPan(self) -> QPointF: ...
    def setPan(self, pan: QPointF) -> None: ...
    def setPanZoomLocked(self, locked: bool) -> None: ...
    def panZoomLocked(self) -> bool: ...
    def applySettings(
        self,
        config: Config | None = ...,
        **overrides: object,
    ) -> None: ...
    def registerTool(
        self,
        mode: str,
        factory: Callable[[], ViewerTool],
        *,
        dependencies: Callable[[], object] | None = ...,
    ) -> None: ...
    def unregisterTool(self, mode: str) -> None: ...
    def setControlMode(self, mode: str) -> None: ...
    def controlMode(self) -> str: ...
    def availableControlModes(self) -> tuple[str, ...]: ...
    def catalog(self) -> ViewerCatalog: ...
    def addImage(
        self,
        image: QImage,
        *,
        label: str = ...,
        path: Path | None = ...,
        source_id: uuid.UUID | None = ...,
        select: bool = ...,
    ) -> ViewerCatalogEntry: ...
    def selectCatalogImage(self, entry_id: uuid.UUID) -> bool: ...
    def selectNextImage(self) -> bool: ...
    def selectPreviousImage(self) -> bool: ...
    def removeCatalogImage(self, entry_id: uuid.UUID) -> ViewerCatalogEntry: ...
    def clearCatalog(self) -> None: ...
    def linkedImageGroups(self) -> tuple[LinkedGroup, ...]: ...
    def setLinkedImageGroups(self, groups: Iterable[LinkedGroup]) -> None: ...
    def setAllImagesLinked(self, enabled: bool) -> None: ...
    def catalogPrefetchState(self) -> ViewerPrefetchSnapshot: ...
    def placeholderState(self) -> ViewerPlaceholderState: ...
    def setPlaceholderImage(
        self,
        image: QImage | None,
        *,
        path: Path | None = ...,
    ) -> None: ...
    def compareWithNextImage(self) -> bool: ...
    def setComparisonImage(self, entry_id: uuid.UUID) -> None: ...
    def clearComparison(self) -> None: ...
    def setComparisonSplit(
        self,
        position: float,
        orientation: ComparisonOrientation | str | None = ...,
    ) -> None: ...
    def comparisonState(self) -> ComparisonState: ...
    def setComparisonDividerInteractive(self, enabled: bool) -> None: ...
    def comparisonDividerInteractive(self) -> bool: ...
    def comparisonDividerState(self) -> ComparisonDividerState: ...
    def diagnostics(self) -> Diagnostics: ...
    def gatherDiagnostics(self) -> DiagnosticsSnapshot: ...
    def createStatusOverlay(self, *, parent: QWidget | None = ...) -> QWidget: ...
    def setDiagnosticsOverlayEnabled(self, enabled: bool) -> None: ...
    def diagnosticsOverlayEnabled(self) -> bool: ...
    def diagnosticsDomains(self) -> tuple[str, ...]: ...
    def setDiagnosticsDomainEnabled(self, domain: str, enabled: bool) -> None: ...
    def diagnosticsDomainEnabled(self, domain: str) -> bool: ...
    def registerDiagnosticsProvider(
        self,
        provider: DiagnosticsProvider,
        *,
        domain: str = ...,
        detail: bool = ...,
    ) -> None: ...
    def registerOverlay(self, name: str, draw_fn: OverlayDrawFn) -> None: ...
    def unregisterOverlay(self, name: str) -> None: ...
    def registerSceneOverlay(
        self,
        name: str,
        draw_fn: SceneOverlayDrawFn,
    ) -> None: ...
    def unregisterSceneOverlay(self, name: str) -> None: ...
    def addLayerPresentationEffect(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        style: LayerPresentationStyle,
        *,
        effect_id: uuid.UUID | None = ...,
    ) -> uuid.UUID: ...
    def updateLayerPresentationEffect(
        self,
        effect_id: uuid.UUID,
        style: LayerPresentationStyle,
    ) -> bool: ...
    def removeLayerPresentationEffect(self, effect_id: uuid.UUID) -> bool: ...
    def clearLayerPresentationEffects(
        self,
        *,
        scene_id: uuid.UUID | None = ...,
        layer_id: uuid.UUID | None = ...,
    ) -> int: ...
    def layerPresentationEffects(self) -> tuple[LayerPresentationEffect, ...]: ...
    def calculateRenderPlan(
        self,
        *,
        use_pan: QPointF | None = ...,
    ) -> SceneRenderPlan | None: ...
    def physicalViewportRect(self) -> QRectF: ...
    def panelHitTest(self, point: QPoint | QPointF) -> PanelHitTest | None: ...
    def coordinateSystem(self) -> SceneCoordinateSystem: ...
    def minimumSizeHint(self) -> QSize: ...
