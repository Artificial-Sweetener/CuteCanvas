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

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QLineF,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QImage,
    QTransform,
)
from PySide6.QtWidgets import QWidget
from qpane import (
    DiagnosticRecord as DiagnosticRecord,
)
from qpane import (
    LayerPresentationEffect as LayerPresentationEffect,
)
from qpane import (
    LayerPresentationEffectKind as LayerPresentationEffectKind,
)
from qpane import (
    LayerPresentationStyle as LayerPresentationStyle,
)
from qpane import (
    LinkedGroup as LinkedGroup,
)
from qpane import (
    PanelHitTest,
)
from qpane.sdk.catalog import ImageMap
from qpane.sdk.concurrency import TaskExecutorProtocol, ThreadPolicy
from typing_extensions import Self

from .composition.geometry_policy import LayerGeometryMode as LayerGeometryMode
from .composition.geometry_policy import LayerGeometryPolicy as LayerGeometryPolicy
from .core import (
    CursorProvider,
    OverlayDrawFn,
    SceneOverlayDrawFn,
    ToolFactory,
    ToolSignalBinder,
)
from .coverage import CoverageShapeOptions as CoverageShapeOptions
from .facade.editor import (
    CoverageFacade as CoverageFacade,
)
from .facade.editor import (
    EditorFacade as EditorFacade,
)
from .facade.editor import (
    HistoryFacade as HistoryFacade,
)
from .facade.editor import (
    SelectionFacade as SelectionFacade,
)
from .facade.editor import (
    ToolFacade as ToolFacade,
)
from .facade.effects import EffectsFacade as EffectsFacade
from .facade.handles import (
    DocumentCollection as DocumentCollection,
)
from .facade.handles import (
    DocumentHandle as DocumentHandle,
)
from .facade.handles import (
    LayerEffectHandle as LayerEffectHandle,
)
from .facade.handles import (
    LayerHandle as LayerHandle,
)
from .facade.persistence import (
    DocumentPersistenceFacade as DocumentPersistenceFacade,
)
from .masks.mask_undo import MaskUndoState
from .masks.workflow import MaskInfo as MaskInfo
from .snapping import SnapPolicy as SnapPolicy
from .types import CatalogSnapshot as CatalogSnapshot
from .types import MaskSavedPayload as MaskSavedPayload

class CacheMode(str, Enum):
    AUTO = "auto"
    HARD = "hard"

class PlaceholderScaleMode(str, Enum):
    AUTO = "auto"
    LOGICAL_FIT = "logical_fit"
    PHYSICAL_FIT = "physical_fit"
    RELATIVE_FIT = "relative_fit"

class ZoomMode(str, Enum):
    FIT = "fit"
    LOCKED_ZOOM = "locked_zoom"
    LOCKED_SIZE = "locked_size"

class ControlMode(str, Enum):
    CURSOR = "cursor"
    PANZOOM = "panzoom"
    MOVE = "move"
    TRANSFORM = "transform"
    DRAW_BRUSH = "draw-brush"
    SMART_SELECT = "smart-select"
    SELECT_RECTANGLE = "select-rectangle"
    SELECT_ELLIPSE = "select-ellipse"
    SELECT_LASSO = "select-lasso"
    VECTOR_SHAPE = "vector-shape"
    VECTOR_PATH = "vector-path"
    VECTOR_NODE = "vector-node"
    VECTOR_TEXT = "vector-text"

class ComparisonOrientation(str, Enum):
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"

class RasterExtentPolicy(str, Enum):
    FIXED = "fixed"
    EXPAND_ON_WRITE = "expand-on-write"
    UNBOUNDED = "unbounded"

class EditorCapability(str, Enum):
    SELECT_PIXELS = "select-pixels"
    EDIT_PIXELS = "edit-pixels"
    PAINT = "paint"
    MOVE_LAYERS = "move-layers"
    TRANSFORM_LAYERS = "transform-layers"

class EditorIntent(str, Enum):
    SELECT_PIXELS = "select-pixels"
    DELETE_PIXELS = "delete-pixels"
    PAINT = "paint"
    MOVE = "move"
    TRANSFORM = "transform"

class PixelSelectionMode(str, Enum):
    REPLACE = "replace"
    ADD = "add"
    SUBTRACT = "subtract"
    INTERSECT = "intersect"

class CoverageCoordinateSpace(str, Enum):
    TARGET = "target"
    NORMALIZED_TARGET = "normalized-target"

class BrushOperation(str, Enum):
    PAINT = "paint"
    ERASE = "erase"

@dataclass(frozen=True, slots=True)
class BrushDynamics:
    pressure_size: float = ...
    pressure_opacity: float = ...
    minimum_pressure_ratio: float = ...
    pressure_gamma: float = ...
    position_jitter: float = ...
    size_jitter: float = ...
    angle_jitter: float = ...
    rotation_angle: float = ...
    tilt_angle: float = ...
    tangential_opacity: float = ...

@dataclass(frozen=True, slots=True)
class BrushPreset:
    name: str = ...
    size: float = ...
    hardness: float = ...
    opacity: float = ...
    flow: float = ...
    spacing: float = ...
    smoothing: float = ...
    angle: float = ...
    texture_strength: float = ...
    texture_scale: float = ...
    texture_seed: int = ...
    dynamics: BrushDynamics = ...

class PaintTargetKind(str, Enum):
    LAYER = "layer"
    PIXEL_SELECTION = "pixel-selection"

class FloatingPixelMode(str, Enum):
    CUT = "cut"
    COPY = "copy"

class PlacedAssetMode(str, Enum):
    EMBEDDED = "embedded"
    LINKED = "linked"

class PlacedAssetStatus(str, Enum):
    READY = "ready"
    LOADING = "loading"
    MISSING = "missing"
    ERROR = "error"

class VectorObjectKind(str, Enum):
    PATH = "path"
    SHAPE = "shape"
    TEXT = "text"

class VectorShapeKind(str, Enum):
    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"

class VectorPathCommandKind(str, Enum):
    MOVE = "move"
    LINE = "line"
    QUADRATIC = "quadratic"
    CUBIC = "cubic"
    CLOSE = "close"

class VectorFillRule(str, Enum):
    WINDING = "winding"
    EVEN_ODD = "even-odd"

class VectorStrokeJoin(str, Enum):
    MITER = "miter"
    ROUND = "round"
    BEVEL = "bevel"

class VectorStrokeCap(str, Enum):
    FLAT = "flat"
    ROUND = "round"
    SQUARE = "square"

class VectorNodeRole(str, Enum):
    ANCHOR = "anchor"
    CONTROL = "control"
    BOUNDS = "bounds"

class VectorTextAlignment(str, Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"

class VectorTextDirection(str, Enum):
    AUTO = "auto"
    LEFT_TO_RIGHT = "left-to-right"
    RIGHT_TO_LEFT = "right-to-left"

@dataclass(frozen=True, slots=True)
class VectorPathCommand:
    kind: VectorPathCommandKind
    points: tuple[QPointF, ...] = ...

@dataclass(frozen=True, slots=True)
class VectorStyle:
    fill: QColor | None = ...
    stroke: QColor | None = ...
    stroke_width: float = ...
    opacity: float = ...
    join: VectorStrokeJoin = ...
    cap: VectorStrokeCap = ...
    dash_pattern: tuple[float, ...] = ...
    fill_rule: VectorFillRule = ...

@dataclass(frozen=True, slots=True)
class VectorTextStyle:
    families: tuple[str, ...] = ...
    font_size: float = ...
    weight: int = ...
    italic: bool = ...
    letter_spacing: float = ...
    color: QColor = ...

@dataclass(frozen=True, slots=True)
class VectorTextSpan:
    start: int
    length: int
    style: VectorTextStyle

@dataclass(frozen=True, slots=True)
class VectorParagraphStyle:
    alignment: VectorTextAlignment = ...
    direction: VectorTextDirection = ...
    line_height: float = ...

@dataclass(frozen=True, slots=True)
class VectorTextContent:
    text: str
    style: VectorTextStyle = ...
    spans: tuple[VectorTextSpan, ...] = ...
    paragraph: VectorParagraphStyle = ...

@dataclass(frozen=True, slots=True)
class TextFontResolution:
    requested_families: tuple[str, ...]
    resolved_family: str
    exact_match: bool

@dataclass(frozen=True, slots=True)
class VectorTextEditSnapshot:
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    object_id: uuid.UUID
    text: str
    cursor: int
    is_new: bool

class VectorObjectSnapshot:
    object_id: uuid.UUID
    kind: VectorObjectKind
    bounds: QRectF
    transform: QTransform
    style: VectorStyle
    shape_kind: VectorShapeKind | None
    path: tuple[VectorPathCommand, ...]
    text: VectorTextContent | None

class VectorDocumentSnapshot:
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    vector_id: uuid.UUID
    revision: int
    objects: tuple[VectorObjectSnapshot, ...]

class VectorSelectionSnapshot:
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    object_ids: tuple[uuid.UUID, ...]

class VectorMaskSnapshot:
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    vector_id: uuid.UUID
    object_ids: tuple[uuid.UUID, ...]
    transform: QTransform
    inverted: bool

class VectorNodeSelectionSnapshot:
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    object_id: uuid.UUID
    node_index: int
    role: VectorNodeRole

class DiagnosticsDomain(str, Enum):
    CACHE: str
    SWAP: str
    MASK: str
    EXECUTOR: str
    RETRY: str
    SAM: str

class CatalogEntry:
    image: QImage
    path: Path | None

class OverlayState:
    zoom: float
    qpane_rect: QRect
    source_image: QImage
    transform: QTransform
    current_pan: QPointF
    physical_viewport_rect: QRectF

class CompositionLayerClip:
    coordinate_space: str
    rect: QRectF

class CompositionPolicy:
    removable: bool
    comparison_enabled: bool
    def __init__(
        self,
        removable: bool = True,
        comparison_enabled: bool = True,
    ) -> None: ...

class LayerPolicy:
    selectable: bool
    movable: bool
    pixel_editable: bool
    reorderable: bool
    removable: bool

class EditorPolicy:
    capabilities: frozenset[EditorCapability]

class EditorOperationState:
    intent: EditorIntent
    allowed: bool
    denial: str | None
    alternatives: tuple[str, ...]
    scene_id: uuid.UUID | None
    layer_id: uuid.UUID | None

class CompositionLayerEntry:
    layer_id: uuid.UUID
    source_kind: str
    source_id: uuid.UUID
    label: str | None
    role: str
    visible: bool
    opacity: float
    interaction: LayerPolicy
    transform: QTransform

class LayerSelectionSnapshot:
    scene_id: uuid.UUID
    layer_id: uuid.UUID

class PlacedAssetSnapshot:
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    asset_id: uuid.UUID
    mode: PlacedAssetMode
    status: PlacedAssetStatus
    source_path: Path | None
    error: str | None
    keep_fallback: bool
    content_revision: int
    generation: int

class PaintTargetSnapshot:
    scene_id: uuid.UUID
    kind: PaintTargetKind
    layer_id: uuid.UUID | None
    source_kind: str | None

class RasterSurfaceSnapshot:
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    bounds: QRect
    extent_policy: RasterExtentPolicy
    content_revision: int
    structure_revision: int
    pending_request_id: uuid.UUID | None

class PixelSelectionSnapshot:
    scene_id: uuid.UUID
    revision: int
    bounds: QRect | None
    coverage: QImage | None
    @property
    def has_selection(self) -> bool: ...

class FloatingPixelSnapshot:
    scene_id: uuid.UUID
    source_layer_id: uuid.UUID
    mode: FloatingPixelMode
    offset: QPoint
    bounds: QRect | None

class LayerSnapshot:
    layer_id: uuid.UUID
    image_id: uuid.UUID | None
    placement: QRectF
    visible: bool
    opacity: float
    tint: QColor | None
    clip: CompositionLayerClip | None
    hit_test: bool
    role: str
    metadata: Mapping[str, object]
    interaction: LayerPolicy
    source_kind: str
    source_id: uuid.UUID | None
    label: str | None
    transform: QTransform

class CatalogLayerRequest:
    layer_id: uuid.UUID
    image_id: uuid.UUID
    placement: QRectF
    visible: bool
    opacity: float
    clip: CompositionLayerClip | None
    hit_test: bool
    role: str
    metadata: Mapping[str, object]
    interaction: LayerPolicy

class CompositionRequest:
    composition_id: uuid.UUID | None
    title: str | None
    bounds: QRectF
    layers: tuple[CatalogLayerRequest, ...]

class TemplateLayer:
    layer_id: uuid.UUID
    source_slot: str
    placement: QRectF
    visible: bool
    opacity: float
    clip: CompositionLayerClip | None
    hit_test: bool
    role: str
    metadata: Mapping[str, object]
    interaction: LayerPolicy

class CompositionTemplate:
    template_id: uuid.UUID
    bounds: QRectF
    layers: tuple[TemplateLayer, ...]
    title: str | None

class TemplateBindings:
    composition_id: uuid.UUID | None
    title: str | None
    catalog_images: Mapping[str, uuid.UUID]
    metadata: Mapping[str, Mapping[str, object]]

class SceneSnapshot:
    composition_id: uuid.UUID
    scene_id: uuid.UUID
    title: str
    bounds: QRectF
    layers: tuple[LayerSnapshot, ...]

class LayerHit:
    composition_id: uuid.UUID
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    image_id: uuid.UUID
    role: str
    metadata: Mapping[str, object]
    panel_point: QPointF
    scene_point: QPointF
    source_point: QPointF

class SceneSnapshotOverlayLayer:
    layer_id: uuid.UUID
    source_id: uuid.UUID | None
    role: str
    label: str | None
    metadata: Mapping[str, object]
    placement: QRectF
    source_size: QSize
    transform: QTransform
    panel_bounds: QRectF
    visible: bool

class SceneSnapshotOverlayState:
    zoom: float
    qpane_rect: QRect
    physical_viewport_rect: QRectF
    scene_id: uuid.UUID
    scene_bounds: QRectF
    layers: tuple[SceneSnapshotOverlayLayer, ...]

class ComparisonState:
    enabled: bool
    source_id: uuid.UUID | None
    source_path: Path | None
    source_kind: str | None
    split_position: float
    orientation: ComparisonOrientation

class ComparisonDividerState:
    enabled: bool
    interactive: bool
    hovered: bool
    dragging: bool
    orientation: ComparisonOrientation
    hit_width: float
    full_segment: QLineF | None
    visible_segment: QLineF | None

class CompositionEntry:
    composition_id: uuid.UUID
    kind: str
    title: str
    source_image_ids: tuple[uuid.UUID, ...]
    current_image_id: uuid.UUID | None
    comparison: ComparisonState
    scene_layer_count: int
    scene_bounds: QRectF | None
    layers: tuple[CompositionLayerEntry, ...]
    policy: CompositionPolicy

class CompositionSnapshot:
    compositions: dict[uuid.UUID, CompositionEntry]
    order: tuple[uuid.UUID, ...]
    current_composition_id: uuid.UUID | None

class Config:
    def __init__(self, **overrides: Any) -> None: ...
    @staticmethod
    def feature_descriptors() -> Mapping[str, object]: ...
    def configure(self, config_obj: object | None = ..., **kwargs: Any) -> Self: ...
    def copy(self) -> Self: ...
    def as_dict(self) -> dict[str, Any]: ...

class CuteCanvas(QWidget):
    CONTROL_MODE_PANZOOM: str
    CONTROL_MODE_CURSOR: str
    CONTROL_MODE_MOVE: str
    CONTROL_MODE_TRANSFORM: str
    CONTROL_MODE_DRAW_BRUSH: str
    CONTROL_MODE_PAINT_BUCKET: str
    CONTROL_MODE_SMART_SELECT: str
    CONTROL_MODE_SELECT_RECTANGLE: str
    CONTROL_MODE_SELECT_ELLIPSE: str
    CONTROL_MODE_SELECT_LASSO: str
    CONTROL_MODE_MASK_RECTANGLE: str
    CONTROL_MODE_MASK_ELLIPSE: str
    CONTROL_MODE_MASK_LASSO: str
    CONTROL_MODE_VECTOR_SHAPE: str
    CONTROL_MODE_VECTOR_PATH: str
    CONTROL_MODE_VECTOR_NODE: str
    CONTROL_MODE_VECTOR_TEXT: str

    imageLoaded: Signal
    zoomChanged: Signal
    viewportRectChanged: Signal
    maskSaved: Signal
    maskUndoStackChanged: Signal
    currentImageChanged: Signal
    catalogChanged: Signal
    catalogSelectionChanged: Signal
    linkGroupsChanged: Signal
    diagnosticsOverlayToggled: Signal
    diagnosticsDomainToggled: Signal
    comparisonChanged: Signal
    compositionChanged: Signal
    compositionSelectionChanged: Signal
    sceneChanged: Signal
    sceneEditHistoryChanged: Signal
    pixelSelectionChanged: Signal
    paintTargetChanged: Signal
    brushPresetChanged: Signal
    paintColorChanged: Signal
    vectorSelectionChanged: Signal
    vectorNodeSelectionChanged: Signal
    vectorToolOptionsChanged: Signal
    vectorTextEditChanged: Signal
    vectorRequestCompleted: Signal
    floatingPixelEditChanged: Signal
    selectedLayerChanged: Signal
    editorPolicyChanged: Signal
    rasterBoundsRequestCompleted: Signal
    placedAssetRequestCompleted: Signal
    samCheckpointStatusChanged: Signal
    samCheckpointProgress: Signal

    def __init__(
        self,
        *,
        config: Config | None = ...,
        features: Iterable[str] | None = ...,
        task_executor: TaskExecutorProtocol | None = ...,
        thread_policy: ThreadPolicy | Mapping[str, Any] | None = ...,
        config_strict: bool = ...,
        **kwargs: Any,
    ) -> None: ...
    @staticmethod
    def imageMapFromLists(
        images: Iterable[QImage],
        paths: Iterable[Path | None] | None = ...,
        ids: Iterable[uuid.UUID] | None = ...,
    ) -> ImageMap: ...
    @staticmethod
    def fitSceneRect(source_size: QSize, target_rect: QRectF) -> QRectF: ...
    @staticmethod
    def fillSceneRect(source_size: QSize, target_rect: QRectF) -> QRectF: ...
    @property
    def settings(self) -> Config: ...
    @settings.setter
    def settings(self, new_settings: Config) -> None: ...
    @property
    def installedFeatures(self) -> tuple[str, ...]: ...
    @property
    def editor(self) -> EditorFacade: ...
    def placeholderActive(self) -> bool: ...
    @property
    def currentImage(self) -> QImage | None: ...
    @property
    def currentImagePath(self) -> Path | None: ...
    @property
    def allImages(self) -> list[QImage]: ...
    @property
    def allImagePaths(self) -> list[Path | None]: ...
    def imagePath(self, image_id: uuid.UUID | None) -> Path | None: ...
    def currentImageID(self) -> uuid.UUID | None: ...
    def imageIDs(self) -> list[uuid.UUID]: ...
    def hasImages(self) -> bool: ...
    def linkedGroups(self) -> tuple[LinkedGroup, ...]: ...
    def currentCompositionID(self) -> uuid.UUID | None: ...
    def compositionIDs(self) -> list[uuid.UUID]: ...
    def getCompositionSnapshot(self) -> CompositionSnapshot: ...
    def activeMaskID(self) -> uuid.UUID | None: ...
    def maskIDsForImage(self, image_id: uuid.UUID | None = ...) -> list[uuid.UUID]: ...
    def listMasksForImage(
        self, image_id: uuid.UUID | None = ...
    ) -> tuple[MaskInfo, ...]: ...
    def getActiveMaskImage(self) -> QImage | None: ...
    def getMaskUndoState(self, mask_id: uuid.UUID) -> MaskUndoState | None: ...
    def diagnosticsOverlayEnabled(self) -> bool: ...
    def diagnosticsDomains(self) -> tuple[str, ...]: ...
    def diagnosticsDomainEnabled(self, domain: str | DiagnosticsDomain) -> bool: ...
    def maskFeatureAvailable(self) -> bool: ...
    def samFeatureAvailable(self) -> bool: ...
    def samCheckpointReady(self) -> bool: ...
    def samCheckpointPath(self) -> Path | None: ...
    def refreshSamFeature(self) -> tuple[bool, str]: ...
    def availableControlModes(self) -> tuple[str, ...]: ...
    def getControlMode(self) -> str: ...
    def currentZoom(self) -> float: ...
    def currentViewportRect(self) -> QRectF: ...
    def setZoomFit(self) -> None: ...
    def setZoom1To1(self, anchor: QPoint | QPointF | None = ...) -> None: ...
    def applyZoom(
        self,
        requested_zoom: float,
        anchor: QPoint | QPointF | None = ...,
    ) -> None: ...
    def panelHitTest(self, panel_pos: QPoint) -> PanelHitTest | None: ...
    def applySettings(
        self, *, config: Config | None = ..., **overrides: Any
    ) -> None: ...
    def editorPolicy(self) -> EditorPolicy: ...
    def setEditorPolicy(self, policy: EditorPolicy) -> bool: ...
    def editorOperationState(
        self,
        intent: EditorIntent,
        panel_pos: QPoint | QPointF | None = ...,
    ) -> EditorOperationState: ...
    def setDiagnosticsOverlayEnabled(self, enabled: bool) -> None: ...
    def setDiagnosticsDomainEnabled(
        self, domain: str | DiagnosticsDomain, enabled: bool
    ) -> None: ...
    def registerOverlay(
        self,
        name: str,
        draw_fn: OverlayDrawFn,
    ) -> None: ...
    def unregisterOverlay(self, name: str) -> None: ...
    def contentOverlays(self) -> Mapping[str, OverlayDrawFn]: ...
    def composeScene(
        self,
        request: CompositionRequest,
        *,
        activate: bool = ...,
        fit_view: bool = ...,
    ) -> uuid.UUID: ...
    def createComposition(
        self,
        bounds: QRectF,
        *,
        title: str = "Untitled",
        policy: CompositionPolicy | None = None,
        fit_view: bool = True,
    ) -> uuid.UUID: ...
    def createCompositionFromImage(
        self,
        image_id: uuid.UUID,
        *,
        title: str | None = None,
        interaction: LayerPolicy | None = None,
        policy: CompositionPolicy | None = None,
        fit_view: bool = True,
    ) -> uuid.UUID: ...
    def addCatalogImageLayer(
        self,
        image_id: uuid.UUID,
        *,
        placement: QRectF | None = None,
        label: str | None = None,
        interaction: LayerPolicy | None = None,
    ) -> uuid.UUID | None: ...
    def setCompositionPolicy(
        self,
        composition_id: uuid.UUID,
        policy: CompositionPolicy,
    ) -> bool: ...
    def composeSceneFromTemplate(
        self,
        template: CompositionTemplate,
        bindings: TemplateBindings,
        *,
        activate: bool = ...,
        fit_view: bool = ...,
    ) -> uuid.UUID: ...
    def currentScene(self) -> SceneSnapshot | None: ...
    def sceneHitTest(self, panel_pos: QPoint) -> LayerHit | None: ...
    def layerTransform(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> QTransform | None: ...
    def layerLocalBounds(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> QRectF | None: ...
    def layerGeometryPolicy(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> LayerGeometryPolicy | None: ...
    def setLayerGeometryPolicy(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        policy: LayerGeometryPolicy,
    ) -> bool: ...
    def setLayerInteractionPolicy(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        policy: LayerPolicy,
    ) -> bool: ...
    def setLayerVisible(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        visible: bool,
    ) -> bool: ...
    def translateLayer(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        offset: QPointF,
    ) -> bool: ...
    def centerLayer(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        *,
        horizontally: bool = ...,
        vertically: bool = ...,
    ) -> bool: ...
    def selectedLayer(self) -> LayerSelectionSnapshot | None: ...
    def setSelectedLayer(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> bool: ...
    def clearSelectedLayer(self) -> bool: ...
    def placeEmbeddedAsset(
        self,
        image: QImage,
        *,
        placement: QRectF | None = ...,
        label: str | None = ...,
        interaction: LayerPolicy | None = ...,
    ) -> uuid.UUID | None: ...
    def placeLinkedAsset(
        self,
        path: Path,
        *,
        placement: QRectF | None = ...,
        label: str | None = ...,
        interaction: LayerPolicy | None = ...,
        keep_fallback: bool = ...,
    ) -> uuid.UUID | None: ...
    def duplicatePlacedAsset(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> uuid.UUID | None: ...
    def placedAssetState(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> PlacedAssetSnapshot | None: ...
    def refreshPlacedAsset(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> uuid.UUID | None: ...
    def relinkPlacedAsset(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        path: Path,
    ) -> uuid.UUID | None: ...
    def embedPlacedAsset(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> bool: ...
    def rasterizePlacedAsset(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        pixel_size: QSize | None = ...,
    ) -> uuid.UUID | None: ...
    def setLayerPlacement(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        placement: QRectF,
    ) -> bool: ...
    def setLayerTransform(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        transform: QTransform,
    ) -> bool: ...
    def setLayerIndex(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        index: int,
    ) -> bool: ...
    def removeLayer(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool: ...
    def rasterSurfaceState(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> RasterSurfaceSnapshot | None: ...
    def createVectorLayer(
        self,
        size: QSize | None = ...,
        *,
        label: str = ...,
    ) -> uuid.UUID | None: ...
    def vectorDocumentState(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> VectorDocumentSnapshot | None: ...
    def setVectorMask(
        self,
        scene_id: uuid.UUID,
        vector_layer_id: uuid.UUID,
        target_layer_id: uuid.UUID,
        object_ids: Iterable[uuid.UUID] | None = ...,
        *,
        inverted: bool = ...,
    ) -> bool: ...
    def vectorMaskState(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> VectorMaskSnapshot | None: ...
    def clearVectorMask(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool: ...
    def addVectorShape(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        shape: VectorShapeKind,
        bounds: QRectF,
        style: VectorStyle | None = ...,
    ) -> uuid.UUID | None: ...
    def addVectorPath(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        commands: Iterable[VectorPathCommand],
        style: VectorStyle | None = ...,
    ) -> uuid.UUID | None: ...
    def addVectorText(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        bounds: QRectF,
        content: VectorTextContent,
    ) -> uuid.UUID | None: ...
    def updateVectorText(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
        *,
        bounds: QRectF | None = ...,
        content: VectorTextContent | None = ...,
    ) -> bool: ...
    def beginVectorTextEdit(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
    ) -> bool: ...
    def vectorTextEditState(self) -> VectorTextEditSnapshot | None: ...
    def commitVectorTextEdit(self) -> bool: ...
    def cancelVectorTextEdit(self) -> bool: ...
    def vectorTextStyle(self) -> VectorTextStyle: ...
    def setVectorTextStyle(self, style: VectorTextStyle) -> bool: ...
    def vectorParagraphStyle(self) -> VectorParagraphStyle: ...
    def setVectorParagraphStyle(self, style: VectorParagraphStyle) -> bool: ...
    def vectorTextFontResolutions(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
    ) -> tuple[TextFontResolution, ...]: ...
    def convertVectorTextToPaths(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
    ) -> uuid.UUID | None: ...
    def updateVectorObject(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
        *,
        transform: QTransform | None = ...,
        style: VectorStyle | None = ...,
    ) -> bool: ...
    def removeVectorObject(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
    ) -> bool: ...
    def reorderVectorObject(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
        index: int,
    ) -> bool: ...
    def vectorSelectionState(self) -> VectorSelectionSnapshot | None: ...
    def vectorNodeSelectionState(self) -> VectorNodeSelectionSnapshot | None: ...
    def setSelectedVectorObjects(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_ids: Iterable[uuid.UUID],
    ) -> bool: ...
    def clearVectorSelection(self) -> bool: ...
    def vectorToolShape(self) -> VectorShapeKind: ...
    def setVectorToolShape(self, shape: VectorShapeKind) -> bool: ...
    def vectorToolStyle(self) -> VectorStyle: ...
    def setVectorToolStyle(self, style: VectorStyle) -> bool: ...
    def convertVectorToPixelSelection(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_ids: Iterable[uuid.UUID] | None = ...,
        mode: PixelSelectionMode = ...,
    ) -> uuid.UUID | None: ...
    def rasterizeVectorLayer(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        pixel_size: QSize | None = ...,
    ) -> uuid.UUID | None: ...
    def addEditableRasterLayer(
        self,
        image: QImage,
        *,
        placement: QRectF | None = ...,
        label: str | None = ...,
        interaction: LayerPolicy | None = ...,
        extent_policy: RasterExtentPolicy = ...,
    ) -> uuid.UUID | None: ...
    def createPaintLayer(
        self,
        size: QSize | None = ...,
        *,
        label: str = ...,
        extent_policy: RasterExtentPolicy = ...,
    ) -> uuid.UUID | None: ...
    def paintTargetState(self) -> PaintTargetSnapshot | None: ...
    def setPaintTarget(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool: ...
    def setPixelSelectionPaintTarget(self) -> bool: ...
    def clearPaintTarget(self) -> bool: ...
    def brushPreset(self) -> BrushPreset: ...
    def setBrushPreset(self, preset: BrushPreset) -> bool: ...
    def paintColor(self) -> QColor: ...
    def setPaintColor(self, color: QColor) -> bool: ...
    def fillSelection(self) -> bool: ...
    def paintBucketOptions(self) -> tuple[int, bool, bool]: ...
    def configurePaintBucket(
        self,
        *,
        tolerance: int | None = ...,
        contiguous: bool | None = ...,
        antialias: bool | None = ...,
    ) -> bool: ...
    def coverageShapeOptions(self) -> CoverageShapeOptions: ...
    def configureCoverageShapes(
        self,
        *,
        feather_radius: float | None = ...,
    ) -> bool: ...
    def addCoverageShape(
        self,
        shape: VectorShapeKind,
        bounds: QRectF,
        mode: PixelSelectionMode = ...,
        *,
        feather_radius: float | None = ...,
        coordinate_space: CoverageCoordinateSpace = ...,
    ) -> uuid.UUID | None: ...
    def addCoveragePolygon(
        self,
        points: Iterable[QPointF],
        mode: PixelSelectionMode = ...,
        *,
        feather_radius: float | None = ...,
        coordinate_space: CoverageCoordinateSpace = ...,
    ) -> uuid.UUID | None: ...
    def addCoverageImage(
        self,
        coverage: QImage,
        bounds: QRect,
        mode: PixelSelectionMode = ...,
    ) -> uuid.UUID | None: ...
    def rasterizeMaskCoverage(self, mask_id: uuid.UUID) -> bool: ...
    def snapPolicy(self) -> SnapPolicy: ...
    def configureSnapping(
        self,
        *,
        enabled: bool | None = ...,
        canvas: bool | None = ...,
        layers: bool | None = ...,
        selections: bool | None = ...,
        guides: bool | None = ...,
        grid: bool | None = ...,
        threshold_device_pixels: float | None = ...,
        release_device_pixels: float | None = ...,
    ) -> bool: ...
    def setSnapGuides(
        self,
        *,
        vertical: Iterable[float] = ...,
        horizontal: Iterable[float] = ...,
    ) -> bool: ...
    def setSnapGrid(self, origin: QPointF, spacing: QPointF) -> bool: ...
    def setBrushSize(self, size: int) -> None: ...
    def editableRasterLayerImage(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> QImage | None: ...
    def setRasterExtentPolicy(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        policy: RasterExtentPolicy,
    ) -> bool: ...
    def requestRasterBounds(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        bounds: QRect,
    ) -> uuid.UUID | None: ...
    def pixelSelectionState(self) -> PixelSelectionSnapshot | None: ...
    def setPixelSelection(
        self,
        coverage: QImage,
        bounds: QRect,
        mode: PixelSelectionMode = ...,
    ) -> bool: ...
    def clearPixelSelection(self) -> bool: ...
    def selectAllPixels(self) -> bool: ...
    def invertPixelSelection(self) -> bool: ...
    def selectLayerCoverage(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        mode: PixelSelectionMode = ...,
    ) -> bool: ...
    def deleteSelectedPixels(self) -> bool: ...
    def floatingPixelEditState(self) -> FloatingPixelSnapshot | None: ...
    def anchorFloatingPixels(
        self,
        scene_id: uuid.UUID | None = ...,
        layer_id: uuid.UUID | None = ...,
    ) -> bool: ...
    def promoteFloatingPixels(self, label: str | None = ...) -> uuid.UUID | None: ...
    def cancelFloatingPixels(self) -> bool: ...
    def sceneEditUndoAvailable(self) -> bool: ...
    def sceneEditRedoAvailable(self) -> bool: ...
    def undoSceneEdit(self) -> bool: ...
    def redoSceneEdit(self) -> bool: ...
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
    def registerSceneOverlay(
        self,
        name: str,
        draw_fn: SceneOverlayDrawFn,
    ) -> None: ...
    def unregisterSceneOverlay(self, name: str) -> None: ...
    def sceneOverlays(self) -> Mapping[str, SceneOverlayDrawFn]: ...
    def overlaysSuspended(self) -> bool: ...
    def overlaysResumePending(self) -> bool: ...
    def resumeOverlays(self) -> None: ...
    def resumeOverlaysAndUpdate(self) -> None: ...
    def maybeResumeOverlays(self) -> None: ...
    def registerCursorProvider(self, mode: str, provider: CursorProvider) -> None: ...
    def unregisterCursorProvider(self, mode: str) -> None: ...
    def registerTool(
        self,
        mode: str,
        factory: ToolFactory,
        *,
        on_connect: ToolSignalBinder | None = ...,
        on_disconnect: ToolSignalBinder | None = ...,
    ) -> None: ...
    def unregisterTool(self, mode: str) -> None: ...
    def setImagesByID(
        self,
        image_map: ImageMap,
        current_id: uuid.UUID,
    ) -> None: ...
    def clearImages(self) -> None: ...
    def removeImageByID(self, image_id: uuid.UUID) -> None: ...
    def removeImagesByID(self, image_ids: list[uuid.UUID]) -> None: ...
    def setCurrentImageID(self, image_id: uuid.UUID | None) -> None: ...
    def setAllImagesLinked(self, enabled: bool) -> None: ...
    def setLinkedGroups(self, groups: Iterable[LinkedGroup]) -> None: ...
    def compose(
        self,
        *,
        images: Iterable[uuid.UUID],
        title: str | None = ...,
    ) -> uuid.UUID: ...
    def openComposition(self, composition_id: uuid.UUID) -> None: ...
    def removeComposition(self, composition_id: uuid.UUID) -> None: ...
    def getCatalogSnapshot(self) -> CatalogSnapshot: ...
    def createBlankMask(self, size: QSize) -> uuid.UUID | None: ...
    def loadMaskFromFile(self, path: str) -> uuid.UUID | None: ...
    def removeMaskFromImage(self, image_id: uuid.UUID, mask_id: uuid.UUID) -> bool: ...
    def setActiveMaskID(self, mask_id: uuid.UUID | None) -> bool: ...
    def setMaskProperties(
        self,
        mask_id: uuid.UUID,
        color: QColor | None = ...,
        opacity: float | None = ...,
    ) -> bool: ...
    def prefetchMaskOverlays(
        self, image_id: uuid.UUID | None, *, reason: str = ...
    ) -> bool: ...
    def cycleMasksForward(self) -> bool: ...
    def cycleMasksBackward(self) -> bool: ...
    def undoMaskEdit(self) -> bool: ...
    def redoMaskEdit(self) -> bool: ...
    def setControlMode(
        self,
        mode: str,
    ) -> None: ...
    def setComparisonImageID(self, image_id: uuid.UUID) -> None: ...
    def clearComparisonImage(self) -> None: ...
    def setComparisonSplit(
        self,
        position: float,
        orientation: ComparisonOrientation | str | None = ...,
    ) -> None: ...
    def comparisonState(self) -> ComparisonState: ...
    def comparisonDividerInteractive(self) -> bool: ...
    def setComparisonDividerInteractive(self, enabled: bool) -> None: ...
    def comparisonDividerState(self) -> ComparisonDividerState: ...
