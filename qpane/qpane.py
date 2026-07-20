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

"""QPane widget facade coordinating rendering, catalog, mask, and tool APIs."""

import logging
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import replace
from math import isclose, isfinite
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from PySide6.QtCore import (
    QEvent,
    QLineF,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QScreen,
    QTabletEvent,
    QTouchEvent,
    QTransform,
    QWheelEvent,
    QWindow,
)
from PySide6.QtWidgets import QWidget

from . import ui
from .cache import (
    CacheCoordinator,
)
from .cache.registry import CacheRegistry
from .catalog import Catalog, CatalogMutationEvent, ImageMap, LinkManager
from .catalog.source_reference import CatalogImageReference
from .compare import (
    CompareDividerInteraction,
    CompareService,
    ComparisonChange,
    ComparisonChangeKind,
)
from .composition import (
    CompositionRecord,
    CompositionService,
)
from .composition.layers import CompositionLayerInstance
from .composition.public_policy import (
    internal_document_policy,
    internal_layer_policy,
    public_layer_policy,
)
from .composition.scene_adapter import CompositionSceneAdapter
from .concurrency import TaskExecutorProtocol, ThreadPolicy
from .core import (
    Config,
    CursorProvider,
    DiagnosticsSnapshot,
    FeatureFailure,
    FeatureFallbacks,
    OverlayDrawFn,
    QPaneHooks,
    QPaneState,
    SceneOverlayDrawFn,
    ToolFactory,
    ToolSignalBinder,
)
from .core.diagnostics_broker import Diagnostics
from .coverage import CoverageCombineMode, CoverageSnapshot
from .editor import (
    EditorInteractionCoordinator,
    EditorMovementInteraction,
    EditorOperation,
    EditorOperationResolver,
    EditorPolicyController,
    FloatingLayerPromotionRegistry,
    LayerSelectionProjectionCache,
    SelectedPixelMovementController,
)
from .editor.composition_root import (
    EditorCompositionRoot,
    EditorRootCallbacks,
    EditorRootInputs,
)
from .editor.transform_interaction import EditorTransformInteraction
from .masks.coordinates import ActiveMaskLayerCoordinates
from .masks.descriptor_factory import MaskLayerDescriptorFactory
from .masks.floating_layers import MaskFloatingLayerOwner
from .masks.paint_target import MaskCoveragePaintTargetOwner
from .masks.pixel_edits import (
    MaskLayerPixelMutationOwner,
    MaskPixelRenderSynchronizer,
)
from .masks.resource_lifecycle import MaskResourceLifecycleOwner
from .masks.source_reference import MaskAssetReference
from .masks.source_resolver import MaskSourceCapabilities
from .masks.workflow import MaskActivationSyncResult, MaskInfo, Masks
from .painting import (
    BrushPreset,
    PaintingCoordinator,
    PaintTargetIdentity,
)
from .placed.rasterization import PlacedAssetRasterizationService
from .placed.source_reference import PlacedAssetReference
from .placed.store import PlacedAssetStore
from .placed.workflow import PlacedAssetCompletion, PlacedAssetWorkflow
from .raster.assets import EditableRasterAssetStore
from .raster.floating_layers import EditableRasterFloatingLayerOwner
from .raster.image_conversion import (
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_grayscale8,
)
from .raster.layers import (
    EditableRasterLayerController,
)
from .raster.source_reference import EditableRasterReference
from .rendering import (
    RenderingPresenter,
    View,
    ViewportZoomMode,
)
from .rendering.coordinates import PanelHitTest
from .scene.affine import LayerTransform
from .scene.layer_assembly import CompositionLayerSceneAssembler
from .scene.layer_selection import SceneLayerSelection, SceneLayerSelectionController
from .scene.model import LayerDescriptor, LayerInteractionPolicy, LayerPlacement
from .scene.movement_interaction import SceneLayerMovementInteraction
from .scene.mutations import SceneMutationCoordinator
from .scene.pixel_edits import LayerPixelMutationCoordinator
from .scene.pixel_owners import LayerPixelOwnerRegistry
from .scene.raster import RasterBounds
from .scene.raster_mutations import (
    RasterBoundsCompletion,
    RasterLayerMutationCoordinator,
)
from .scene.registry import SceneProviderRegistry
from .scene.render_plan import RasterLayerRenderItem, SceneLayerHitTestResult
from .scene.source_capabilities import LayerSourceCapabilities
from .scene.transform_preview import SceneLayerTransformPreview
from .scene.transform_session import SceneLayerTransformController
from .selection import PixelSelectionService, PixelSelectionState
from .swap import SwapDelegate
from .tools import Tools
from .tools.base import ExtensionTool, ExtensionToolSignals
from .tools.delegate import ToolInteractionDelegate
from .types import (
    CatalogEntry,
    CatalogSnapshot,
    ComparisonDividerState,
    ComparisonOrientation,
    ComparisonState,
    CompositionSnapshot,
    DiagnosticsDomain,
    EditorIntent,
    FloatingPixelMode,
    LinkedGroup,
    PaintTargetKind,
    PixelSelectionMode,
    QPaneCompositionPolicy,
    QPaneEditorOperationState,
    QPaneEditorPolicy,
    QPaneFloatingPixelEditState,
    QPaneLayerInteractionPolicy,
    QPaneLayerSelectionState,
    QPanePaintTargetState,
    QPanePixelSelectionState,
    QPanePlacedAssetState,
    QPaneRasterSurfaceState,
    QPaneScene,
    QPaneSceneClip,
    QPaneSceneHit,
    QPaneSceneLayer,
    QPaneSceneRequest,
    QPaneSceneTemplate,
    QPaneSceneTemplateBindings,
    RasterExtentPolicy,
)
from .ui.diagnostics_controller import DiagnosticsOverlayController
from .ui.editor_overlays import EditorOverlayPresenter
from .vector.conversion import (
    VectorConversionCompletion,
    VectorConversionKind,
)
from .vector.facade import VectorHostFacade
from .vector.interaction import VectorInteractionController
from .vector.node_edit import VectorNodeEditController
from .vector.node_tool import VECTOR_NODE_MODE
from .vector.public import (
    QPaneTextFontResolution,
    QPaneVectorDocumentState,
    QPaneVectorMaskState,
    QPaneVectorNodeSelectionState,
    QPaneVectorSelectionState,
    QPaneVectorTextEditState,
    VectorParagraphStyle,
    VectorPathCommand,
    VectorShapeKind,
    VectorStyle,
    VectorTextContent,
    VectorTextStyle,
)
from .vector.text_edit import VectorTextEditController
from .vector.text_tool import VECTOR_TEXT_MODE
from .vector.tools import VECTOR_PATH_MODE, VECTOR_SHAPE_MODE

if TYPE_CHECKING:
    from .autosave import AutosaveManager
    from .masks.mask import MaskLayer
    from .masks.mask_service import MaskService
    from .masks.mask_undo import MaskUndoState
    from .rendering import Renderer
    from .sam.manager import SamManager
logger = logging.getLogger(__name__)

__all__ = ["ExtensionTool", "ExtensionToolSignals", "QPane"]


class QPane(QWidget):
    """QWidget facade that routes rendering, catalog, mask, and tool orchestration."""

    # ========================================================================
    # Public API
    # ========================================================================
    CONTROL_MODE_PANZOOM = Tools.CONTROL_MODE_PANZOOM
    CONTROL_MODE_CURSOR = Tools.CONTROL_MODE_CURSOR
    CONTROL_MODE_MOVE = Tools.CONTROL_MODE_MOVE
    CONTROL_MODE_TRANSFORM = Tools.CONTROL_MODE_TRANSFORM
    CONTROL_MODE_DRAW_BRUSH = Tools.CONTROL_MODE_DRAW_BRUSH
    CONTROL_MODE_SMART_SELECT = Tools.CONTROL_MODE_SMART_SELECT
    CONTROL_MODE_SELECT_RECTANGLE = Tools.CONTROL_MODE_SELECT_RECTANGLE
    CONTROL_MODE_SELECT_ELLIPSE = Tools.CONTROL_MODE_SELECT_ELLIPSE
    CONTROL_MODE_SELECT_LASSO = Tools.CONTROL_MODE_SELECT_LASSO
    CONTROL_MODE_VECTOR_SHAPE = VECTOR_SHAPE_MODE
    CONTROL_MODE_VECTOR_PATH = VECTOR_PATH_MODE
    CONTROL_MODE_VECTOR_NODE = VECTOR_NODE_MODE
    CONTROL_MODE_VECTOR_TEXT = VECTOR_TEXT_MODE
    imageLoaded: Signal = Signal(Path)
    """Emit the current image path after a swap applies; empty when unknown."""
    zoomChanged: Signal = Signal(float)
    """Emit the viewport zoom factor when view state changes."""
    viewportRectChanged: Signal = Signal(QRectF)
    """Emit the physical viewport rectangle whenever its size changes."""
    maskSaved: Signal = Signal(str, str)
    """Emit ``mask_id`` and file path after a mask autosave completes."""
    maskUndoStackChanged: Signal = Signal(uuid.UUID)
    """Emit the mask UUID when its undo stack mutates."""
    currentImageChanged: Signal = Signal(uuid.UUID)
    """Emit the active image UUID after navigation completes."""
    catalogChanged: Signal = Signal(CatalogMutationEvent)
    """Emit catalog mutation events describing the latest change."""
    catalogSelectionChanged: Signal = Signal(object)
    """Emit the active image UUID or ``None`` when selection changes."""
    linkGroupsChanged: Signal = Signal()
    """Emit when linked-group definitions change."""
    diagnosticsOverlayToggled: Signal = Signal(bool)
    """Emit overlay visibility state when the diagnostics HUD toggles."""
    diagnosticsDomainToggled: Signal = Signal(str, bool)
    """Emit diagnostics domain ID and enabled state after detail toggles."""
    comparisonChanged: Signal = Signal(object)
    """Emit the comparison state after comparison rendering changes."""
    compositionChanged: Signal = Signal(object)
    """Emit the composition snapshot after composition records change."""
    compositionSelectionChanged: Signal = Signal(object)
    """Emit the active composition UUID or ``None`` when selection changes."""
    sceneChanged: Signal = Signal(object)
    """Emit the normalized active scene snapshot or ``None`` when it changes."""
    sceneEditHistoryChanged: Signal = Signal(bool, bool)
    """Emit composition-edit undo and redo availability after history changes."""
    pixelSelectionChanged: Signal = Signal(object)
    """Emit active composition pixel-selection state after it changes."""
    paintTargetChanged: Signal = Signal(object)
    """Emit the active generalized paint target or ``None`` after it changes."""
    brushPresetChanged: Signal = Signal(object)
    """Emit the detached immutable brush preset after it changes."""
    paintColorChanged: Signal = Signal(QColor)
    """Emit the detached color used by editable color-raster targets."""
    vectorSelectionChanged: Signal = Signal(object)
    """Emit vector-object selection or ``None`` independently of pixel selection."""
    vectorNodeSelectionChanged: Signal = Signal(object)
    """Emit vector control-point selection or ``None`` independently."""
    vectorToolOptionsChanged: Signal = Signal(object, object)
    """Emit active vector shape kind and immutable creation style."""
    vectorTextEditChanged: Signal = Signal(object)
    """Emit the active semantic text-edit state or ``None``."""
    vectorRequestCompleted: Signal = Signal(uuid.UUID, object, object, str, bool, str)
    """Emit request, scene, layer, conversion kind, success, and message."""
    floatingPixelEditChanged: Signal = Signal(object)
    """Emit unresolved floating-pixel state or ``None`` after it changes."""
    selectedLayerChanged: Signal = Signal(object)
    """Emit selected scene-layer identity or ``None`` after it changes."""
    editorPolicyChanged: Signal = Signal(object)
    """Emit the immutable editor capability policy after replacement."""
    rasterBoundsRequestCompleted: Signal = Signal(
        uuid.UUID, uuid.UUID, uuid.UUID, bool, str
    )
    """Emit request, scene, layer, success, and message after a bounds request."""
    placedAssetRequestCompleted: Signal = Signal(uuid.UUID, object, object, bool, str)
    """Emit request, scene, layer, success, and message after placed-asset work."""
    samCheckpointStatusChanged: Signal = Signal(str, object)
    """Emit checkpoint status and path updates for SAM readiness tracking.
    The payload is ``(status, path)``, where ``path`` is a ``Path`` and status
    values include ``downloading``, ``ready``, ``failed``, and ``missing``.
    """
    samCheckpointProgress: Signal = Signal(int, object)
    """Emit checkpoint download progress updates for SAM readiness tracking.
    The payload is ``(downloaded, total)``, where ``total`` may be ``None`` if
    the size is unknown.
    """

    def __init__(
        self,
        *,
        config: Config | None = None,
        features: Iterable[str] | None = None,
        task_executor: TaskExecutorProtocol | None = None,
        thread_policy: ThreadPolicy | Mapping[str, Any] | None = None,
        config_strict: bool = False,
        **kwargs,
    ):
        """Build the QPane widget and wire core collaborators.

        Args:
            config: Initial configuration snapshot to apply.
            features: Optional feature names to install (mask, sam, etc.).
            task_executor: Existing executor instance to reuse.
            thread_policy: Policy or mapping forwarded to the executor builder.
            config_strict: When ``True``, reject overrides targeting inactive
                feature namespaces instead of logging warnings.
            **kwargs: Configuration overrides forwarded to ``QPaneState``.
        """
        super().__init__()
        self._state = QPaneState(
            qpane=self,
            initial_config=config,
            config_overrides=kwargs,
            features=features,
            task_executor=task_executor,
            thread_policy=thread_policy,
            config_strict=config_strict,
        )
        self._diagnostics_manager = self._state.diagnostics
        self.original_image = QImage()
        self.interaction = ToolInteractionDelegate(self)
        self._hooks = QPaneHooks(self)
        self._view: View | None = None
        self._catalog: Catalog | None = None
        self._composition_service: CompositionService | None = None
        self._editable_raster_assets: EditableRasterAssetStore | None = None
        self._editable_raster_layers: EditableRasterLayerController | None = None
        self._placed_assets: PlacedAssetStore | None = None
        self._placed_asset_workflow: PlacedAssetWorkflow | None = None
        self._placed_asset_rasterization: PlacedAssetRasterizationService | None = None
        self._pixel_selection: PixelSelectionService | None = None
        self._painting: PaintingCoordinator | None = None
        self._vector_editor: VectorHostFacade | None = None
        self._vector_interaction: VectorInteractionController | None = None
        self._vector_nodes: VectorNodeEditController | None = None
        self._vector_text: VectorTextEditController | None = None
        self.compare_service: CompareService | None = None
        self._compare_interaction: CompareDividerInteraction | None = None
        self._composition_scene_adapter: CompositionSceneAdapter | None = None
        self._scene_mutations: SceneMutationCoordinator | None = None
        self._raster_mutations: RasterLayerMutationCoordinator | None = None
        self._layer_pixel_mutations: LayerPixelMutationCoordinator | None = None
        self._layer_pixel_owners: LayerPixelOwnerRegistry | None = None
        self._editor_interaction: EditorInteractionCoordinator | None = None
        self._selection_layer_projections = LayerSelectionProjectionCache()
        self._floating_layer_promotions = FloatingLayerPromotionRegistry()
        self._editor_policy = EditorPolicyController(self.editorPolicyChanged.emit)
        self._raster_floating_layer_owner: EditableRasterFloatingLayerOwner | None = (
            None
        )
        self._mask_floating_layer_owner: MaskFloatingLayerOwner | None = None
        self._mask_resource_lifecycle_owner: MaskResourceLifecycleOwner | None = None
        self._selected_pixel_movement: SelectedPixelMovementController | None = None
        self._editor_movement_interaction: EditorMovementInteraction | None = None
        self._operation_resolver: EditorOperationResolver | None = None
        self._last_floating_pixel_state: QPaneFloatingPixelEditState | None = None
        self._mask_raster_mutation_owner = None
        self._mask_pixel_edit_owner: MaskLayerPixelMutationOwner | None = None
        self._mask_paint_target_owner: MaskCoveragePaintTargetOwner | None = None
        self._raster_request_public_scenes: dict[uuid.UUID, uuid.UUID] = {}
        self._scene_selection = SceneLayerSelectionController(
            self._handle_selected_layer_changed
        )
        self._scene_transform_preview = SceneLayerTransformPreview()
        self._scene_movement: SceneLayerTransformController | None = None
        self._scene_movement_interaction: SceneLayerMovementInteraction | None = None
        self._scene_transform_interaction: EditorTransformInteraction | None = None
        self._active_mask_coordinates: ActiveMaskLayerCoordinates | None = None
        self._scene_provider_registry: SceneProviderRegistry | None = None
        self._source_capabilities: LayerSourceCapabilities | None = None
        self._composition_layer_assembler: CompositionLayerSceneAssembler | None = None
        self._mask_descriptor_factory: MaskLayerDescriptorFactory | None = None
        self._mask_source_capabilities: MaskSourceCapabilities | None = None
        self._masks: Masks | None = None
        self._tools: Tools | None = None
        self._is_blank = False
        self._diagnostics_overlay_controller: DiagnosticsOverlayController | None = None
        self._editor_overlays = EditorOverlayPresenter(self.update, self)
        self._tracked_window: QWindow | None = None
        self._tracked_screen: QScreen | None = None
        self._tracked_screen_connections: set[str] = set()
        self._last_screen_dpr = float(self.devicePixelRatioF())
        self._last_link_groups: tuple[tuple[uuid.UUID, tuple[uuid.UUID, ...]], ...] = ()
        self._last_viewport_rect: QRectF | None = None
        self._initial_view_signals_scheduled = False
        self._init_core_components()
        view = self.view()
        catalog = self.catalog()
        self._masks = Masks(
            qpane=self,
            catalog=catalog,
            swap_delegate=view.swap_delegate,
            cache_registry=self._state.cache_registry,
        )
        self._masks.register_diagnostics(self._diagnostics_manager)
        self._state.install_features()
        self.applyCacheSettings()
        self.interaction.initialize_widget_properties()
        self.interaction.connect_signals()
        self._catalog.applyConfig(self.settings)
        self._apply_diagnostics_overlay_preferences()
        self._wire_facade_signals()
        self.destroyed.connect(self._state.on_destroyed)
        self._schedule_initial_view_signals()

    @staticmethod
    def imageMapFromLists(
        images: Iterable[QImage],
        paths: Iterable[Path | None] | None = None,
        ids: Iterable[uuid.UUID] | None = None,
    ) -> ImageMap:
        """Build an ImageMap of CatalogEntry values from aligned iterables via the shared helper."""
        return Catalog.imageMapFromLists(images, paths=paths, ids=ids)

    @staticmethod
    def fitSceneRect(source_size: QSize, target_rect: QRectF) -> QRectF:
        """Return the largest centered aspect-preserving scene rect inside a target.

        Args:
            source_size: Source image size whose aspect ratio should be preserved.
            target_rect: Scene-coordinate slot that should contain the result.

        Returns:
            A detached ``QRectF`` centered inside ``target_rect``.

        Raises:
            ValueError: If ``source_size`` is empty or ``target_rect`` has
                negative dimensions.
        """
        return QPane._aspect_scene_rect(
            source_size,
            target_rect,
            cover=False,
        )

    @staticmethod
    def fillSceneRect(source_size: QSize, target_rect: QRectF) -> QRectF:
        """Return the smallest centered aspect-preserving scene rect covering a target.

        Args:
            source_size: Source image size whose aspect ratio should be preserved.
            target_rect: Scene-coordinate slot that should be covered.

        Returns:
            A detached ``QRectF`` centered on ``target_rect``. The result may
            extend outside ``target_rect``.

        Raises:
            ValueError: If ``source_size`` is empty or ``target_rect`` has
                negative dimensions.
        """
        return QPane._aspect_scene_rect(
            source_size,
            target_rect,
            cover=True,
        )

    @property
    def settings(self) -> Config:
        """Expose the active configuration snapshot managed by QPaneState."""
        state = getattr(self, "_state", None)
        if state is None:
            raise AttributeError("QPane settings accessed before initialization")
        return state.settings

    @settings.setter
    def settings(self, new_settings: Config) -> None:
        """Prevent direct mutation; callers must use applySettings."""
        raise AttributeError(
            "QPane.settings is read-only; call QPane.applySettings to change configuration"
        )

    @property
    def installedFeatures(self) -> tuple[str, ...]:
        """Expose the set of features successfully installed on this QPane."""
        return self._state.installed_features

    def placeholderActive(self) -> bool:
        """Return True when the placeholder policy is active."""
        return self.catalog().placeholderActive()

    @property
    def currentImage(self) -> QImage | None:
        """Return the selected catalog image, or None when absent."""
        catalog = self.catalog()
        return catalog.currentImage()

    @property
    def currentImagePath(self) -> Path | None:
        """Return the filesystem path for the current image, if any."""
        catalog = self.catalog()
        return catalog.currentImagePath()

    @property
    def allImages(self) -> list[QImage]:
        """Return a shallow copy of all original images currently held by this QPane."""
        catalog = self.catalog()
        return catalog.allImages()

    @property
    def allImagePaths(self) -> list[Path | None]:
        """Return a shallow copy of all file paths associated with images in this QPane."""
        catalog = self.catalog()
        return catalog.allImagePaths()

    def imagePath(self, image_id: uuid.UUID | None) -> Path | None:
        """Return the filesystem path for ``image_id`` when available."""
        catalog = self.catalog()
        return catalog.imagePath(image_id)

    def currentImageID(self) -> uuid.UUID | None:
        """Return the UUID of the currently selected image via the facade."""
        return self.catalog().currentImageID()

    def imageIDs(self) -> list[uuid.UUID]:
        """Return the ordered image IDs managed by the catalog via the facade."""
        return self.catalog().imageIDs()

    def hasImages(self) -> bool:
        """Return True when the catalog currently contains images."""
        return bool(self.catalog().imageIDs())

    def linkedGroups(self) -> tuple[LinkedGroup, ...]:
        """Return link groups paired with their stable identifiers via the facade."""
        return self.linkManager().getGroupRecords()

    def currentCompositionID(self) -> uuid.UUID | None:
        """Return the active composition UUID."""
        return self.compositionService().current_composition_id()

    def compositionIDs(self) -> list[uuid.UUID]:
        """Return composition UUIDs in browser order."""
        return list(self.compositionService().composition_ids())

    def getCompositionSnapshot(self) -> CompositionSnapshot:
        """Return a structured snapshot of composition browser state."""
        return self.compositionService().snapshot()

    def activeMaskID(self) -> uuid.UUID | None:
        """Return the active mask identifier when masking is available."""
        return self._masks_controller.getActiveMaskID()

    def maskIDsForImage(self, image_id: uuid.UUID | None = None) -> list[uuid.UUID]:
        """Return masks for an image adapter or the active composition."""
        return self._masks_controller.maskIDsForImage(image_id)

    def listMasksForImage(
        self, image_id: uuid.UUID | None = None
    ) -> tuple[MaskInfo, ...]:
        """Return mask rows for an image adapter or the active composition."""
        return self._masks_controller.listMasksForImage(image_id)

    def getActiveMaskImage(self) -> QImage | None:
        """Return the QImage for the currently active mask layer."""
        return self._masks_controller.get_active_mask_image()

    def getMaskUndoState(self, mask_id: uuid.UUID) -> "MaskUndoState | None":
        """Expose the current undo/redo depth for ``mask_id`` when available."""
        return self._masks_controller.get_mask_undo_state(mask_id)

    def diagnosticsOverlayEnabled(self) -> bool:
        """Return True when the diagnostics overlay is currently visible."""
        return self.diagnosticsOverlayController().overlayEnabled()

    def diagnosticsDomains(self) -> tuple[str, ...]:
        """Return diagnostics domains that expose detail-tier providers."""
        return self.diagnosticsOverlayController().domains()

    def diagnosticsDomainEnabled(self, domain: str | DiagnosticsDomain) -> bool:
        """Return True when detail-tier diagnostics for ``domain`` are active.

        Raises:
            ValueError: When the requested diagnostics domain is unavailable.
        """
        canonical = self._normalize_diagnostics_domain(domain)
        return self.diagnosticsOverlayController().domainEnabled(canonical)

    def maskFeatureAvailable(self) -> bool:
        """Return True when mask tooling is currently available."""
        return self._masks_controller.mask_feature_available()

    def samFeatureAvailable(self) -> bool:
        """Return True when SAM tooling is currently available."""
        return self._masks_controller.sam_feature_available()

    def samCheckpointReady(self) -> bool:
        """Return True when the SAM checkpoint is available on disk."""
        manager = self._sam_manager
        if manager is None:
            return False
        return manager.checkpointReady()

    def samCheckpointPath(self) -> Path | None:
        """Return the resolved SAM checkpoint path when SAM is available."""
        manager = self._sam_manager
        return None if manager is None else manager.checkpointPath()

    def refreshSamFeature(self) -> tuple[bool, str]:
        """Reinstall SAM tooling using the current configuration snapshot.

        Returns:
            Tuple of (success, message) describing the refresh result.

        Side effects:
            Detaches the active SAM manager and reinstalls the SAM feature.
        """
        if "sam" not in self.installedFeatures:
            return False, "SAM tools disabled in this mode."
        try:
            from .features import FeatureInstallError
            from .masks.sam_feature import install_sam_feature

            self._masks_controller.detachSamManager()
            install_sam_feature(self)
        except FeatureInstallError as exc:
            hint = f" {exc.hint}" if exc.hint else ""
            return False, f"SAM refresh failed: {exc}.{hint}".strip()
        except Exception as exc:  # noqa: BLE001 - SAM backend boundary
            return False, f"SAM refresh failed: {exc}."
        return True, "SAM refreshed."

    def availableControlModes(self) -> tuple[str, ...]:
        """Return registered control mode identifiers in activation order."""
        return self._tools_manager.available_modes()

    def getControlMode(self) -> str:
        """Return the name of the currently active control mode."""
        return self._tools_manager.get_control_mode()

    def currentZoom(self) -> float:
        """Return the current viewport zoom factor without accessing view internals elsewhere."""
        return float(self.view().viewport.zoom)

    def currentViewportRect(self) -> QRectF:
        """Return the cached physical viewport rectangle reported via ``viewportRectChanged``."""
        rect = self._last_viewport_rect
        return QRectF(rect) if rect is not None else self.physicalViewportRect()

    def setZoomFit(self) -> None:
        """Fit the current content to the viewport and recenter pan."""
        self.view().viewport.setZoomFit()

    def setZoom1To1(self, anchor: QPoint | QPointF | None = None) -> None:
        """Snap zoom to native scale while keeping ``anchor`` steady when provided."""
        self.view().viewport.setZoom1To1(anchor=anchor)

    def applyZoom(
        self,
        requested_zoom: float,
        anchor: QPoint | QPointF | None = None,
    ):
        """Clamp zoom requests and remap unity to the device-native scale.

        Args:
            requested_zoom: Desired zoom multiple in image-space units. Values above 10 are capped,
                and a request of 1.0 is converted to ``viewport.nativeZoom()`` so HiDPI displays
                render one image pixel per physical device pixel.
            anchor: Optional widget-space point to keep stationary while zooming.

        Side effects:
            Logs a warning and returns when no image is loaded or the viewport is locked; otherwise
            forwards the bounded zoom to ``viewport.applyZoom()``.
        """
        new_zoom = self._normalize_zoom_request(requested_zoom)
        if new_zoom is None:
            return
        self.view().viewport.applyZoom(new_zoom, anchor=anchor)

    def panelHitTest(self, panel_pos: QPoint) -> PanelHitTest | None:
        """Return panel hit-test metadata matching ``panel_pos`` when content is available."""
        return self.view().panel_hit_test(panel_pos)

    def applySettings(self, *, config: Config | None = None, **overrides) -> None:
        """Replace the active configuration snapshot and reconfigure services.

        Args:
            config: Optional configuration snapshot to apply.
            overrides: Configuration overrides forwarded to ``QPaneState``.

        Side effects:
            Refreshes mask autosave wiring, marks the view dirty, and schedules a repaint.

        Raises:
            ValueError: When strict config mode is enabled and overrides target
                inactive feature namespaces.
        """
        self._state.apply_settings(config=config, **overrides)
        self.refreshMaskAutosavePolicy()
        self._apply_diagnostics_overlay_preferences()
        self._refresh_screen_tracking()
        self.markDirty()
        self.update()

    def editorPolicy(self) -> QPaneEditorPolicy:
        """Return the immutable host capability policy for editor operations."""
        return self._editor_policy.policy

    def setEditorPolicy(self, policy: QPaneEditorPolicy) -> bool:
        """Replace independently composable editor capabilities.

        Args:
            policy: Complete immutable host capability policy.

        Returns:
            ``True`` when the policy changed.

        Raises:
            TypeError: If ``policy`` is not ``QPaneEditorPolicy``.

        Side effects:
            Cancels provisional gestures losslessly and emits ``editorPolicyChanged``.
        """
        if not isinstance(policy, QPaneEditorPolicy):
            raise TypeError("policy must be QPaneEditorPolicy")
        if policy == self._editor_policy.policy:
            return False
        self.interaction.cancel_active_editor_input()
        movement = self._editor_movement_interaction
        transform = self._scene_transform_interaction
        painting = self._painting
        if movement is not None:
            movement.cancel()
        if transform is not None:
            transform.cancel()
        if painting is not None:
            painting.cancel()
        changed = self._editor_policy.replace(policy)
        self.refreshCursor()
        self.update()
        return changed

    def editorOperationState(
        self,
        intent: EditorIntent,
        panel_pos: QPoint | QPointF | None = None,
    ) -> QPaneEditorOperationState:
        """Resolve one editor intent against current source, selection, and policy.

        Args:
            intent: Operation to inspect without mutating editor state.
            panel_pos: Optional widget position used for Move hit arbitration.

        Returns:
            Detached permission, denial, alternatives, and resolved identities.

        Raises:
            TypeError: If inputs use unsupported public types.
        """
        if not isinstance(intent, EditorIntent):
            raise TypeError("intent must be EditorIntent")
        if panel_pos is not None and not isinstance(panel_pos, (QPoint, QPointF)):
            raise TypeError("panel_pos must be QPoint, QPointF, or None")
        operation = EditorOperation(intent.value)
        scene_point = (
            None
            if panel_pos is None
            else self.view().panel_to_scene_point(QPointF(panel_pos))
        )
        candidate_layer_id = None
        if operation is EditorOperation.MOVE and panel_pos is not None:
            interaction = self._scene_movement_interaction
            candidate = (
                None
                if interaction is None
                else interaction.candidate_at(QPointF(panel_pos))
            )
            candidate_layer_id = None if candidate is None else candidate.hit.layer_id
        resolution = self.editorOperationResolver().resolve(
            operation,
            scene_point=scene_point,
            candidate_layer_id=candidate_layer_id,
        )
        return QPaneEditorOperationState(
            intent=intent,
            allowed=resolution.allowed,
            denial=None if resolution.allowed else resolution.denial.value,
            alternatives=tuple(value.value for value in resolution.alternatives),
            scene_id=resolution.scene_id,
            layer_id=resolution.layer_id,
        )

    def setDiagnosticsOverlayEnabled(self, enabled: bool) -> None:
        """Show or hide the diagnostics overlay via its controller."""
        self.diagnosticsOverlayController().setOverlayEnabled(enabled)

    def setDiagnosticsDomainEnabled(
        self, domain: str | DiagnosticsDomain, enabled: bool
    ) -> None:
        """Enable or disable detail-tier diagnostics providers for ``domain``.

        Raises:
            ValueError: When the requested diagnostics domain is unavailable.
        """
        canonical = self._normalize_diagnostics_domain(domain)
        self.diagnosticsOverlayController().setDomainEnabled(canonical, enabled)

    def registerOverlay(
        self,
        name: str,
        draw_fn: OverlayDrawFn,
    ) -> None:
        """Register a content-space overlay to be painted after rendered content.

        Raises:
            ValueError: If `name` is already present.
        """
        self.interaction.registerOverlay(name, draw_fn)

    def unregisterOverlay(self, name: str) -> None:
        """Remove a previously registered overlay.

        Missing entries are ignored so callers can always unregister during teardown.
        """
        self.interaction.unregisterOverlay(name)

    def contentOverlays(self) -> Mapping[str, OverlayDrawFn]:
        """Return a read-only snapshot of registered content overlays."""
        return self.interaction.content_overlays_snapshot()

    def composeScene(
        self,
        request: QPaneSceneRequest,
        *,
        activate: bool = True,
        fit_view: bool = True,
    ) -> uuid.UUID:
        """Create or replace a stored catalog-backed scene composition.

        Args:
            request: Scene composition request whose layers reference catalog image IDs.
            activate: Open the stored composition immediately when True.
            fit_view: Fit the composed scene bounds when activation occurs.

        Raises:
            TypeError: If request objects have invalid types.
            ValueError: If scene geometry, layer values, or replacement targets are invalid.
            KeyError: If a layer references an image ID outside the catalog.

        Side effects:
            Stores a composition record, optionally opens it, and emits
            composition and scene signals.
        """
        previous_active_id = self.currentCompositionID()
        record = self.compositionService().compose_scene(
            request,
            catalog_contains=self._image_catalog.containsImage,
            activate=activate,
        )
        self._emit_composition_changed()
        if activate:
            self._open_composition_record(record, fit_view=fit_view)
        elif record.composition_id == previous_active_id:
            self._refresh_active_scene_content(fit_view=fit_view)
        return record.composition_id

    def createComposition(
        self,
        bounds: QRectF,
        *,
        title: str = "Untitled",
        policy: QPaneCompositionPolicy | None = None,
        fit_view: bool = True,
    ) -> uuid.UUID:
        """Create and open an empty composition document.

        Args:
            bounds: Positive scene-space canvas bounds.
            title: Non-empty host-facing document title.
            policy: Optional document-level removal and comparison permissions.
            fit_view: Fit the new canvas in the viewport when True.

        Returns:
            The independent composition UUID.

        Side effects:
            Opens the document and emits composition and scene signals.
        """
        record = self.compositionService().create_composition(
            bounds,
            title=title,
            policy=internal_document_policy(policy or QPaneCompositionPolicy()),
        )
        self._emit_composition_changed()
        self._open_composition_record(record, fit_view=fit_view)
        return record.composition_id

    def createCompositionFromImage(
        self,
        image_id: uuid.UUID,
        *,
        title: str | None = None,
        interaction: QPaneLayerInteractionPolicy | None = None,
        policy: QPaneCompositionPolicy | None = None,
        fit_view: bool = True,
    ) -> uuid.UUID:
        """Create an independent composition seeded by a catalog resource.

        Args:
            image_id: Existing catalog resource used for canvas size and first layer.
            title: Optional document title derived from the catalog path when omitted.
            interaction: Host policy for the ordinary seeded layer.
            policy: Optional document-level removal and comparison permissions.
            fit_view: Fit the new canvas in the viewport when True.

        Returns:
            The independent composition UUID.

        Side effects:
            Opens the document and emits composition and scene signals.
        """
        if not isinstance(image_id, uuid.UUID):
            raise TypeError("image_id must be a UUID")
        if not self._image_catalog.containsImage(image_id):
            raise KeyError("image_id must exist in the catalog")
        if title is not None and not isinstance(title, str):
            raise TypeError("title must be a string or None")
        if interaction is not None and not isinstance(
            interaction,
            QPaneLayerInteractionPolicy,
        ):
            raise TypeError("interaction must be QPaneLayerInteractionPolicy or None")
        if policy is not None and not isinstance(policy, QPaneCompositionPolicy):
            raise TypeError("policy must be QPaneCompositionPolicy or None")
        path = self.imagePath(image_id)
        resolved_title = title or (path.name if path is not None else "Composition")
        record = self.compositionService().create_from_catalog_image(
            image_id,
            title=resolved_title,
            interaction=internal_layer_policy(
                interaction or QPaneLayerInteractionPolicy()
            ),
            policy=internal_document_policy(policy or QPaneCompositionPolicy()),
        )
        self._emit_composition_changed()
        self._open_composition_record(record, fit_view=fit_view)
        return record.composition_id

    def addCatalogImageLayer(
        self,
        image_id: uuid.UUID,
        *,
        placement: QRectF | None = None,
        label: str | None = None,
        interaction: QPaneLayerInteractionPolicy | None = None,
    ) -> uuid.UUID | None:
        """Place one shared catalog resource in the active composition.

        Args:
            image_id: Existing catalog resource to place.
            placement: Optional scene-space destination rectangle.
            label: Optional composition-local display label.
            interaction: Host policy for the new independent instance.

        Returns:
            The new layer UUID, or None when no composition is active.

        Side effects:
            Adds one undoable layer instance and refreshes the active scene.
        """
        if not isinstance(image_id, uuid.UUID):
            raise TypeError("image_id must be a UUID")
        if not self._image_catalog.containsImage(image_id):
            raise KeyError("image_id must exist in the catalog")
        if placement is not None and not isinstance(placement, QRectF):
            raise TypeError("placement must be a QRectF or None")
        if label is not None and not isinstance(label, str):
            raise TypeError("label must be a string or None")
        if interaction is not None and not isinstance(
            interaction,
            QPaneLayerInteractionPolicy,
        ):
            raise TypeError("interaction must be QPaneLayerInteractionPolicy or None")
        layer_id = self.compositionService().add_catalog_layer(
            image_id,
            placement=self._layer_placement(placement),
            interaction=internal_layer_policy(
                interaction or QPaneLayerInteractionPolicy()
            ),
            label=label,
        )
        if layer_id is not None:
            self._refresh_active_scene_content(fit_view=False)
        return layer_id

    def setCompositionPolicy(
        self,
        composition_id: uuid.UUID,
        policy: QPaneCompositionPolicy,
    ) -> bool:
        """Replace structural permissions for one composition document.

        Args:
            composition_id: Existing composition identity.
            policy: Host-selected removal and comparison permissions.

        Returns:
            True when document policy or comparison state changed.

        Side effects:
            Clears an existing comparison when comparison becomes disabled and
            emits composition state when a change occurs.
        """
        if not isinstance(composition_id, uuid.UUID):
            raise TypeError("composition_id must be a UUID")
        if not isinstance(policy, QPaneCompositionPolicy):
            raise TypeError("policy must be QPaneCompositionPolicy")
        record = self.compositionService().record(composition_id)
        changed = self.compositionService().set_document_policy(
            composition_id,
            internal_document_policy(
                policy,
                remove_if_catalog_resource_missing=(
                    record.policy.remove_if_catalog_resource_missing
                ),
            ),
        )
        if changed:
            self._emit_composition_changed()
            if self.currentCompositionID() == composition_id:
                self._handle_comparison_changed()
        return changed

    def composeSceneFromTemplate(
        self,
        template: QPaneSceneTemplate,
        bindings: QPaneSceneTemplateBindings,
        *,
        activate: bool = True,
        fit_view: bool = True,
    ) -> uuid.UUID:
        """Create or replace a stored scene composition from a host template.

        Args:
            template: Host-owned reusable template object.
            bindings: Catalog image bindings for this composition instance.
            activate: Open the stored composition immediately when True.
            fit_view: Fit the composed scene bounds when activation occurs.

        Side effects:
            Stores a composition record, optionally opens it, and emits
            composition and scene signals.
        """
        previous_active_id = self.currentCompositionID()
        record = self.compositionService().compose_scene_from_template(
            template,
            bindings,
            catalog_contains=self._image_catalog.containsImage,
            activate=activate,
        )
        self._emit_composition_changed()
        if activate:
            self._open_composition_record(record, fit_view=fit_view)
        elif record.composition_id == previous_active_id:
            self._refresh_active_scene_content(fit_view=fit_view)
        return record.composition_id

    def currentScene(self) -> QPaneScene | None:
        """Return the normalized scene snapshot for the active composition."""
        return self._current_scene_snapshot()

    def sceneHitTest(self, panel_pos: QPoint) -> QPaneSceneHit | None:
        """Return scene-layer hit metadata for ``panel_pos``."""
        adapter = self._composition_scene_adapter
        if adapter is None:
            return None
        return adapter.hit_from_result(self.view().scene_hit_test(panel_pos))

    def layerTransform(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> QTransform | None:
        """Return one active layer's detached exact local-to-scene transform.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the layer to inspect.

        Returns:
            A detached affine transform, or None when the layer is unavailable.

        Raises:
            TypeError: If either identifier is not a UUID.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        current_scene = self.currentScene()
        active_scene = self.sceneMutationCoordinator().active_scene()
        valid_scene_ids = {
            candidate
            for candidate in (
                None if current_scene is None else current_scene.scene_id,
                None if active_scene is None else active_scene.scene_id,
            )
            if candidate is not None
        }
        composition_id = self.currentCompositionID()
        if scene_id not in valid_scene_ids or composition_id is None:
            return None
        instance = self.compositionService().layers.layer(composition_id, layer_id)
        return None if instance is None else instance.transform.to_qtransform()

    def layerLocalBounds(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> QRectF | None:
        """Return one active layer's detached intrinsic local bounds.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the layer to inspect.

        Returns:
            Detached source-local bounds, or None when unavailable.

        Raises:
            TypeError: If either identifier is not a UUID.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        current_scene = self.currentScene()
        active_scene = self.sceneMutationCoordinator().active_scene()
        valid_scene_ids = {
            candidate
            for candidate in (
                None if current_scene is None else current_scene.scene_id,
                None if active_scene is None else active_scene.scene_id,
            )
            if candidate is not None
        }
        if active_scene is None or scene_id not in valid_scene_ids:
            return None
        layer = next(
            (
                candidate
                for candidate in active_scene.layers
                if candidate.layer_id == layer_id
            ),
            None,
        )
        bounds = None if layer is None else layer.raster_bounds
        return (
            None
            if bounds is None
            else QRectF(
                float(bounds.x),
                float(bounds.y),
                float(bounds.width),
                float(bounds.height),
            )
        )

    def setLayerInteractionPolicy(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        policy: QPaneLayerInteractionPolicy,
    ) -> bool:
        """Set direct-interaction permissions for an active scene layer.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the layer to update.
            policy: Selection and movement permissions to apply.

        Returns:
            True when the policy changed.

        Raises:
            TypeError: If identifiers or policy use unsupported types.

        Side effects:
            Refreshes active scene rendering and emits sceneChanged after a change.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not isinstance(policy, QPaneLayerInteractionPolicy):
            raise TypeError("policy must be QPaneLayerInteractionPolicy")
        coordinator = self.sceneMutationCoordinator()
        result = coordinator.set_interaction(
            self._resolve_public_scene_id(scene_id),
            layer_id,
            internal_layer_policy(policy),
        )
        if result.changed:
            self.view().invalidate_content_cache()
            self._handle_internal_scene_content_changed()
            self._emit_scene_changed()
        return result.changed

    def setLayerPlacement(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        placement: QRectF,
    ) -> bool:
        """Set absolute scene-space placement for a movable active layer.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the layer to move.
            placement: New scene-space layer rectangle.

        Returns:
            True when placement changed and one history command was recorded.

        Raises:
            TypeError: If identifiers or placement use unsupported types.
            ValueError: If placement dimensions or coordinates are invalid.

        Side effects:
            Refreshes scene rendering and emits scene/history signals after a change.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not isinstance(placement, QRectF):
            raise TypeError("placement must be a QRectF")
        if not self._anchor_floating_pixels_before_edit():
            return False
        resolved_scene_id = self._resolve_public_scene_id(scene_id)
        result = self.sceneMutationCoordinator().set_placement(
            resolved_scene_id,
            layer_id,
            LayerPlacement(
                placement.x(),
                placement.y(),
                placement.width(),
                placement.height(),
            ),
        )
        if result.changed:
            self._publish_scene_transform_change()
        return result.changed

    def setLayerTransform(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        transform: QTransform,
    ) -> bool:
        """Set one movable active layer's exact affine local-to-scene transform.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the layer to transform.
            transform: Finite, invertible affine local-to-scene mapping.

        Returns:
            True when geometry changed and one history command was recorded.

        Raises:
            TypeError: If identifiers or transform use unsupported types.
            ValueError: If the transform is projective, singular, or non-finite.

        Side effects:
            Refreshes scene rendering and emits scene/history signals after a change.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not isinstance(transform, QTransform):
            raise TypeError("transform must be a QTransform")
        normalized = LayerTransform.from_qtransform(QTransform(transform))
        if not normalized.is_invertible:
            raise ValueError("transform must be numerically invertible")
        if not self._anchor_floating_pixels_before_edit():
            return False
        result = self.sceneMutationCoordinator().set_transform(
            self._resolve_public_scene_id(scene_id),
            layer_id,
            normalized,
        )
        if result.changed:
            self._publish_scene_transform_change()
        return result.changed

    def setLayerIndex(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        index: int,
    ) -> bool:
        """Move one active layer to a bottom-to-top composition stack index.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the layer to reorder.
            index: Target render index, where zero is bottommost.

        Returns:
            True when order changed and one history command was recorded.

        Raises:
            TypeError: If identifiers or index use unsupported types.

        Side effects:
            Refreshes scene rendering and composition snapshots after a change.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not isinstance(index, int):
            raise TypeError("index must be an int")
        composition_id = self.currentCompositionID()
        active = self.sceneMutationCoordinator().active_scene()
        resolved_scene_id = self._resolve_public_scene_id(scene_id)
        if (
            active is None
            or composition_id is None
            or active.scene_id != resolved_scene_id
        ):
            return False
        if not self._anchor_floating_pixels_before_edit():
            return False
        changed = self.compositionService().set_layer_index(
            composition_id,
            layer_id,
            index,
        )
        if changed:
            self._refresh_active_scene_content(fit_view=False)
        return changed

    def removeLayer(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Remove one policy-enabled layer from the active composition.

        Args:
            scene_id: Public identifier for the active composition scene.
            layer_id: Stable identifier of the layer to remove.

        Returns:
            True when one undoable removal was applied.

        Side effects:
            Refreshes composition state, rendering, selection, and history signals.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        composition_id = self.currentCompositionID()
        scene = self.currentScene()
        if (
            composition_id is None
            or scene is None
            or scene.scene_id != scene_id
            or not self._anchor_floating_pixels_before_edit()
        ):
            return False
        changed = self.compositionService().remove_layer(
            composition_id,
            layer_id,
        )
        if changed:
            self._refresh_active_scene_content(fit_view=False)
        return changed

    def selectedLayer(self) -> QPaneLayerSelectionState | None:
        """Return selected layer identity in the active scene, if any."""
        selection = self.editorInteraction().selected_layer
        if selection is None:
            return None
        current_scene = self.currentScene()
        return QPaneLayerSelectionState(
            scene_id=(
                selection.scene_id if current_scene is None else current_scene.scene_id
            ),
            layer_id=selection.layer_id,
        )

    def setSelectedLayer(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Select one policy-enabled layer in the active scene."""
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not self._anchor_floating_pixels_before_edit():
            return False
        return self.editorInteraction().select_layer(
            self._resolve_public_scene_id(scene_id),
            layer_id,
        )

    def clearSelectedLayer(self) -> bool:
        """Clear selected-layer identity without changing pixel selection."""
        return bool(
            self._anchor_floating_pixels_before_edit()
            and self.editorInteraction().clear_selected_layer()
        )

    def placeEmbeddedAsset(
        self,
        image: QImage,
        *,
        placement: QRectF | None = None,
        label: str | None = None,
        interaction: QPaneLayerInteractionPolicy | None = None,
    ) -> uuid.UUID | None:
        """Place a detached non-destructive embedded image in the active scene.

        Args:
            image: Non-null raster copied into composition-owned asset storage.
            placement: Optional scene destination; source dimensions are used by default.
            label: Optional host-facing layer label.
            interaction: Host policy for selection and movement.

        Returns:
            The stable layer UUID, or ``None`` when no composition is active.

        Side effects:
            Records one scene edit and publishes updated scene state.
        """
        self._validate_placed_inputs(image, placement, label, interaction)
        workflow = self._placed_asset_workflow
        if workflow is None:
            return None
        normalized = interaction or QPaneLayerInteractionPolicy(
            selectable=True,
            movable=True,
        )
        return workflow.create_embedded(
            image,
            placement=self._layer_placement(placement),
            interaction=internal_layer_policy(normalized),
            label=label,
        )

    def placeLinkedAsset(
        self,
        path: Path,
        *,
        placement: QRectF | None = None,
        label: str | None = None,
        interaction: QPaneLayerInteractionPolicy | None = None,
        keep_fallback: bool = True,
    ) -> uuid.UUID | None:
        """Begin non-blocking placement of an externally linked image.

        Args:
            path: Filesystem image locator decoded away from the GUI thread.
            placement: Optional scene destination; source dimensions are used by default.
            label: Optional host-facing layer label.
            interaction: Host policy for selection and movement.
            keep_fallback: Whether composition archives retain last-known pixels.

        Returns:
            A request UUID, or ``None`` when no composition is active.

        Side effects:
            Emits ``placedAssetRequestCompleted`` exactly once for accepted work.
        """
        if not isinstance(path, Path):
            raise TypeError("path must be a pathlib.Path")
        self._validate_placed_inputs(None, placement, label, interaction)
        if not isinstance(keep_fallback, bool):
            raise TypeError("keep_fallback must be a bool")
        workflow = self._placed_asset_workflow
        if workflow is None:
            return None
        normalized = interaction or QPaneLayerInteractionPolicy(
            selectable=True,
            movable=True,
        )
        return workflow.create_linked(
            path,
            placement=self._layer_placement(placement),
            interaction=internal_layer_policy(normalized),
            label=label,
            keep_fallback=keep_fallback,
        )

    def duplicatePlacedAsset(
        self, scene_id: uuid.UUID, layer_id: uuid.UUID
    ) -> uuid.UUID | None:
        """Duplicate a placed layer while sharing its non-destructive source."""
        scope_id = self._placed_scope(scene_id, layer_id)
        workflow = self._placed_asset_workflow
        if scope_id is None or workflow is None:
            return None
        return workflow.duplicate(
            scope_id,
            layer_id,
            history_scope_id=self._resolve_public_scene_id(scene_id),
        )

    def placedAssetState(
        self, scene_id: uuid.UUID, layer_id: uuid.UUID
    ) -> QPanePlacedAssetState | None:
        """Return detached provenance and availability for one placed layer."""
        scope_id = self._placed_scope(scene_id, layer_id)
        workflow = self._placed_asset_workflow
        if scope_id is None or workflow is None:
            return None
        snapshot = workflow.snapshot_for_layer(scope_id, layer_id)
        instance = self.compositionService().layers.layer(scope_id, layer_id)
        source = None if instance is None else instance.source
        if snapshot is None or not isinstance(source, PlacedAssetReference):
            return None
        return QPanePlacedAssetState(
            scene_id=scene_id,
            layer_id=layer_id,
            asset_id=source.asset_id,
            mode=snapshot.mode,
            status=snapshot.status,
            source_path=snapshot.source_path,
            error=snapshot.error,
            keep_fallback=snapshot.keep_fallback,
            content_revision=snapshot.content_revision,
            generation=snapshot.generation,
        )

    def refreshPlacedAsset(
        self, scene_id: uuid.UUID, layer_id: uuid.UUID
    ) -> uuid.UUID | None:
        """Begin a non-blocking refresh from one placed layer's linked path."""
        scope_id = self._placed_scope(scene_id, layer_id)
        workflow = self._placed_asset_workflow
        return (
            None
            if scope_id is None or workflow is None
            else workflow.refresh(scope_id, layer_id)
        )

    def relinkPlacedAsset(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        path: Path,
    ) -> uuid.UUID | None:
        """Begin an undoable non-blocking reload from a replacement path."""
        if not isinstance(path, Path):
            raise TypeError("path must be a pathlib.Path")
        scope_id = self._placed_scope(scene_id, layer_id)
        workflow = self._placed_asset_workflow
        return (
            None
            if scope_id is None or workflow is None
            else workflow.relink(scope_id, layer_id, path)
        )

    def embedPlacedAsset(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Detach one linked placed source from its external path."""
        scope_id = self._placed_scope(scene_id, layer_id)
        workflow = self._placed_asset_workflow
        return bool(
            scope_id is not None
            and workflow is not None
            and workflow.embed(scope_id, layer_id)
        )

    def rasterizePlacedAsset(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        pixel_size: QSize | None = None,
    ) -> uuid.UUID | None:
        """Begin conversion of a placed source to an editable raster layer.

        Args:
            scene_id: Public identifier of the active scene.
            layer_id: Placed layer to replace atomically.
            pixel_size: Explicit output dimensions; source dimensions are the default.

        Returns:
            A request UUID, or ``None`` when the layer is not a current placed asset.

        Raises:
            TypeError: If identifiers or pixel size use unsupported types.
            ValueError: If output dimensions are empty or exceed the memory limit.

        Side effects:
            Emits ``placedAssetRequestCompleted`` exactly once for accepted work.
        """
        if pixel_size is not None and not isinstance(pixel_size, QSize):
            raise TypeError("pixel_size must be a QSize or None")
        scope_id = self._placed_scope(scene_id, layer_id)
        service = self._placed_asset_rasterization
        if scope_id is None or service is None:
            return None
        return service.request(
            scope_id,
            self._resolve_public_scene_id(scene_id),
            layer_id,
            pixel_size,
        )

    def rasterSurfaceState(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> QPaneRasterSurfaceState | None:
        """Return source-owned raster storage state for an active scene layer.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the raster layer to inspect.

        Returns:
            A detached raster state snapshot, or ``None`` for non-raster layers.

        Raises:
            TypeError: If either identifier is not a UUID.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        coordinator = self._raster_mutations
        if coordinator is None:
            return None
        state = coordinator.state(self._resolve_public_scene_id(scene_id), layer_id)
        if state is None:
            return None
        return QPaneRasterSurfaceState(
            scene_id=scene_id,
            layer_id=state.layer_id,
            bounds=state.bounds.to_qrect(),
            extent_policy=state.extent_policy,
            content_revision=state.content_revision,
            structure_revision=state.structure_revision,
            pending_request_id=state.pending_request_id,
        )

    def createVectorLayer(
        self,
        size: QSize | None = None,
        *,
        label: str = "Vector Layer",
    ) -> uuid.UUID | None:
        """Create an empty resolution-independent vector layer.

        Args:
            size: Document dimensions, or active scene dimensions when omitted.
            label: Non-empty host-facing layer label.

        Returns:
            The new layer UUID, or ``None`` when no scene is active.

        Side effects:
            Adds one movable vector layer as an undoable scene edit.
        """
        if size is not None and not isinstance(size, QSize):
            raise TypeError("size must be a QSize or None")
        if size is not None and (size.width() <= 0 or size.height() <= 0):
            raise ValueError("size dimensions must be positive")
        if not isinstance(label, str):
            raise TypeError("label must be a string")
        if not label.strip():
            raise ValueError("label must not be empty")
        editor = self._vector_editor_controller()
        return editor.create_layer(
            None if size is None else QSize(size),
            label=label,
            interaction=LayerInteractionPolicy(selectable=True, movable=True),
        )

    def vectorDocumentState(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> QPaneVectorDocumentState | None:
        """Return one vector layer's detached semantic document revision."""
        self._validate_vector_ids(scene_id, layer_id)
        return self._vector_editor_controller().document_state(scene_id, layer_id)

    def setVectorMask(
        self,
        scene_id: uuid.UUID,
        vector_layer_id: uuid.UUID,
        target_layer_id: uuid.UUID,
        object_ids: Iterable[uuid.UUID] | None = None,
        *,
        inverted: bool = False,
    ) -> bool:
        """Promote a vector layer into another layer's editable mask.

        Args:
            scene_id: Public identifier of the active scene.
            vector_layer_id: Vector layer whose document becomes the mask source.
            target_layer_id: Layer instance clipped by the vector geometry.
            object_ids: Exact mask objects, or every object when omitted.
            inverted: Whether geometry hides rather than reveals target content.

        Returns:
            True when one atomic layer-stack transition was recorded.

        Side effects:
            Removes the vector layer instance, selects the target, and retains the
            semantic document as its editable effect source.
        """
        self._validate_vector_ids(scene_id, vector_layer_id, target_layer_id)
        values = () if object_ids is None else tuple(object_ids)
        if any(not isinstance(object_id, uuid.UUID) for object_id in values):
            raise TypeError("object_ids must contain UUID values")
        if not isinstance(inverted, bool):
            raise TypeError("inverted must be a bool")
        return self._vector_editor_controller().attach_mask(
            scene_id,
            vector_layer_id,
            target_layer_id,
            values,
            inverted=inverted,
        )

    def vectorMaskState(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> QPaneVectorMaskState | None:
        """Return detached semantic vector-mask state for one layer."""
        self._validate_vector_ids(scene_id, layer_id)
        return self._vector_editor_controller().mask_state(scene_id, layer_id)

    def clearVectorMask(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Remove one layer's vector mask through composition chronology."""
        self._validate_vector_ids(scene_id, layer_id)
        return self._vector_editor_controller().clear_mask(scene_id, layer_id)

    def addVectorShape(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        shape: VectorShapeKind,
        bounds: QRectF,
        style: VectorStyle | None = None,
    ) -> uuid.UUID | None:
        """Add one editable parametric rectangle or ellipse."""
        self._validate_vector_ids(scene_id, layer_id)
        if not isinstance(shape, VectorShapeKind):
            raise TypeError("shape must be VectorShapeKind")
        if not isinstance(bounds, QRectF):
            raise TypeError("bounds must be a QRectF")
        if (
            not all(
                isfinite(value)
                for value in (bounds.x(), bounds.y(), bounds.width(), bounds.height())
            )
            or bounds.width() < 0.0
            or bounds.height() < 0.0
        ):
            raise ValueError("bounds must be finite with non-negative dimensions")
        if style is not None and not isinstance(style, VectorStyle):
            raise TypeError("style must be VectorStyle or None")
        return self._vector_editor_controller().add_shape(
            scene_id,
            layer_id,
            shape,
            QRectF(bounds),
            style or VectorStyle(),
        )

    def addVectorPath(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        commands: Iterable[VectorPathCommand],
        style: VectorStyle | None = None,
    ) -> uuid.UUID | None:
        """Add one durable command-based vector path."""
        self._validate_vector_ids(scene_id, layer_id)
        command_values = tuple(commands)
        if any(
            not isinstance(command, VectorPathCommand) for command in command_values
        ):
            raise TypeError("commands must contain VectorPathCommand values")
        if not command_values:
            raise ValueError("commands must not be empty")
        if style is not None and not isinstance(style, VectorStyle):
            raise TypeError("style must be VectorStyle or None")
        return self._vector_editor_controller().add_path(
            scene_id,
            layer_id,
            command_values,
            style or VectorStyle(),
        )

    def addVectorText(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        bounds: QRectF,
        content: VectorTextContent,
    ) -> uuid.UUID | None:
        """Add editable semantic Unicode text inside a layout box."""
        self._validate_vector_ids(scene_id, layer_id)
        if not isinstance(bounds, QRectF):
            raise TypeError("bounds must be a QRectF")
        if bounds.isEmpty() or not all(
            isfinite(value)
            for value in (bounds.x(), bounds.y(), bounds.width(), bounds.height())
        ):
            raise ValueError("bounds must be finite and non-empty")
        if not isinstance(content, VectorTextContent):
            raise TypeError("content must be VectorTextContent")
        return self._vector_editor_controller().add_text(
            scene_id, layer_id, QRectF(bounds), content
        )

    def updateVectorText(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
        *,
        bounds: QRectF | None = None,
        content: VectorTextContent | None = None,
    ) -> bool:
        """Atomically replace semantic text content or its layout box."""
        self._validate_vector_ids(scene_id, layer_id, object_id)
        if bounds is not None and not isinstance(bounds, QRectF):
            raise TypeError("bounds must be a QRectF or None")
        if bounds is not None and (
            bounds.isEmpty()
            or not all(
                isfinite(value)
                for value in (bounds.x(), bounds.y(), bounds.width(), bounds.height())
            )
        ):
            raise ValueError("bounds must be finite and non-empty")
        if content is not None and not isinstance(content, VectorTextContent):
            raise TypeError("content must be VectorTextContent or None")
        if bounds is None and content is None:
            return False
        return self._vector_editor_controller().update_text(
            scene_id,
            layer_id,
            object_id,
            bounds=None if bounds is None else QRectF(bounds),
            content=content,
        )

    def beginVectorTextEdit(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
    ) -> bool:
        """Begin in-place editing of one semantic text object."""
        self._validate_vector_ids(scene_id, layer_id, object_id)
        return self._vector_editor_controller().begin_text_edit(
            scene_id, layer_id, object_id
        )

    def vectorTextEditState(self) -> QPaneVectorTextEditState | None:
        """Return the active in-place semantic text session."""
        return self._vector_editor_controller().text_edit_state()

    def commitVectorTextEdit(self) -> bool:
        """Commit the active text session as one history transition."""
        return self._vector_text_controller().commit()

    def cancelVectorTextEdit(self) -> bool:
        """Discard the active text session without changing history."""
        return self._vector_text_controller().cancel()

    def vectorTextStyle(self) -> VectorTextStyle:
        """Return the current semantic text creation style."""
        return self._vector_text_controller().style

    def setVectorTextStyle(self, style: VectorTextStyle) -> bool:
        """Set the current text style and apply it to active text."""
        if not isinstance(style, VectorTextStyle):
            raise TypeError("style must be VectorTextStyle")
        return self._vector_text_controller().set_style(style)

    def vectorParagraphStyle(self) -> VectorParagraphStyle:
        """Return the current semantic paragraph policy."""
        return self._vector_text_controller().paragraph

    def setVectorParagraphStyle(self, style: VectorParagraphStyle) -> bool:
        """Set paragraph policy and apply it to active text."""
        if not isinstance(style, VectorParagraphStyle):
            raise TypeError("style must be VectorParagraphStyle")
        return self._vector_text_controller().set_paragraph(style)

    def vectorTextFontResolutions(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
    ) -> tuple[QPaneTextFontResolution, ...]:
        """Return requested-to-resolved font diagnostics for one text object."""
        self._validate_vector_ids(scene_id, layer_id, object_id)
        return self._vector_editor_controller().text_font_resolutions(
            scene_id, layer_id, object_id
        )

    def convertVectorTextToPaths(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
    ) -> uuid.UUID | None:
        """Begin conversion of semantic text to color-preserving glyph paths.

        Side effects:
            Emits ``vectorRequestCompleted`` exactly once for accepted work.
        """
        self._validate_vector_ids(scene_id, layer_id, object_id)
        return self._vector_editor_controller().convert_text_to_paths(
            scene_id, layer_id, object_id
        )

    def updateVectorObject(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
        *,
        transform: QTransform | None = None,
        style: VectorStyle | None = None,
    ) -> bool:
        """Atomically update one stable vector object's transform or style."""
        self._validate_vector_ids(scene_id, layer_id, object_id)
        if transform is not None and not isinstance(transform, QTransform):
            raise TypeError("transform must be a QTransform or None")
        if style is not None and not isinstance(style, VectorStyle):
            raise TypeError("style must be VectorStyle or None")
        if transform is None and style is None:
            return False
        return self._vector_editor_controller().update_object(
            scene_id,
            layer_id,
            object_id,
            transform=None if transform is None else QTransform(transform),
            style=style,
        )

    def removeVectorObject(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
    ) -> bool:
        """Remove one stable vector object through composition chronology."""
        self._validate_vector_ids(scene_id, layer_id, object_id)
        return self._vector_editor_controller().remove_object(
            scene_id,
            layer_id,
            object_id,
        )

    def reorderVectorObject(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_id: uuid.UUID,
        index: int,
    ) -> bool:
        """Move one vector object to a clamped document order index."""
        self._validate_vector_ids(scene_id, layer_id, object_id)
        if not isinstance(index, int):
            raise TypeError("index must be an int")
        return self._vector_editor_controller().reorder_object(
            scene_id,
            layer_id,
            object_id,
            index,
        )

    def vectorSelectionState(self) -> QPaneVectorSelectionState | None:
        """Return vector-object selection independently of pixel selection."""
        return self._vector_editor_controller().selection_state()

    def vectorNodeSelectionState(self) -> QPaneVectorNodeSelectionState | None:
        """Return the selected vector control point, independent of pixel selection."""
        return self._vector_editor_controller().node_selection_state()

    def setSelectedVectorObjects(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_ids: Iterable[uuid.UUID],
    ) -> bool:
        """Select existing objects within one active vector layer."""
        self._validate_vector_ids(scene_id, layer_id)
        values = tuple(object_ids)
        if any(not isinstance(object_id, uuid.UUID) for object_id in values):
            raise TypeError("object_ids must contain UUID values")
        return self._vector_editor_controller().set_selection(
            scene_id,
            layer_id,
            values,
        )

    def clearVectorSelection(self) -> bool:
        """Clear vector-object selection without changing pixel selection."""
        return self._vector_editor_controller().clear_selection()

    def vectorToolShape(self) -> VectorShapeKind:
        """Return the active parametric kind used by the vector shape tool."""
        return self._vector_interaction_controller().shape

    def setVectorToolShape(self, shape: VectorShapeKind) -> bool:
        """Select the parametric kind used by future shape-tool gestures."""
        if not isinstance(shape, VectorShapeKind):
            raise TypeError("shape must be VectorShapeKind")
        return self._vector_interaction_controller().set_shape(shape)

    def vectorToolStyle(self) -> VectorStyle:
        """Return the immutable style used by future vector objects."""
        return self._vector_interaction_controller().style

    def setVectorToolStyle(self, style: VectorStyle) -> bool:
        """Replace the style used by future shape and path gestures."""
        if not isinstance(style, VectorStyle):
            raise TypeError("style must be VectorStyle")
        return self._vector_interaction_controller().set_style(style)

    def convertVectorToPixelSelection(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        object_ids: Iterable[uuid.UUID] | None = None,
        mode: PixelSelectionMode = PixelSelectionMode.REPLACE,
    ) -> uuid.UUID | None:
        """Begin conversion of vector appearance into pixel selection.

        Args:
            scene_id: Public identifier of the active scene.
            layer_id: Vector layer containing the source objects.
            object_ids: Exact objects, the active object selection, or all objects.
            mode: Pixel-selection replacement or composition behavior.

        Returns:
            A request UUID, or ``None`` when the layer is not current vector content.

        Side effects:
            Emits ``vectorRequestCompleted`` exactly once for accepted work.
        """
        self._validate_vector_ids(scene_id, layer_id)
        if object_ids is None:
            values = None
        else:
            values = tuple(object_ids)
            if any(not isinstance(object_id, uuid.UUID) for object_id in values):
                raise TypeError("object_ids must contain UUID values")
        if not isinstance(mode, PixelSelectionMode):
            raise TypeError("mode must be PixelSelectionMode")
        if not self._anchor_floating_pixels_before_edit():
            return None
        return self._vector_editor_controller().convert_to_pixel_selection(
            scene_id,
            layer_id,
            values,
            CoverageCombineMode(mode.value),
        )

    def rasterizeVectorLayer(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        pixel_size: QSize | None = None,
    ) -> uuid.UUID | None:
        """Begin atomic conversion of a vector layer to editable pixels.

        Args:
            scene_id: Public identifier of the active scene.
            layer_id: Vector layer instance to replace.
            pixel_size: Explicit output dimensions or the document dimensions.

        Returns:
            A request UUID, or ``None`` when the layer is not current vector content.

        Side effects:
            Emits ``vectorRequestCompleted`` exactly once for accepted work.
        """
        self._validate_vector_ids(scene_id, layer_id)
        if pixel_size is not None and not isinstance(pixel_size, QSize):
            raise TypeError("pixel_size must be a QSize or None")
        return self._vector_editor_controller().rasterize_layer(
            scene_id,
            layer_id,
            None if pixel_size is None else QSize(pixel_size),
        )

    def addEditableRasterLayer(
        self,
        image: QImage,
        *,
        placement: QRectF | None = None,
        label: str | None = None,
        interaction: QPaneLayerInteractionPolicy | None = None,
        extent_policy: RasterExtentPolicy = RasterExtentPolicy.FIXED,
    ) -> uuid.UUID | None:
        """Add a detached editable color raster to the active image scene.

        Args:
            image: Non-null color raster copied into composition-owned storage.
            placement: Optional scene placement; source dimensions are used by default.
            label: Optional host-facing layer label.
            interaction: Host policy for selection, movement, and pixel editing.
            extent_policy: Fixed, expanding, or unbounded future write behavior.

        Returns:
            The stable layer UUID, or ``None`` when no catalog image is active.
        """
        if not isinstance(image, QImage):
            raise TypeError("image must be a QImage")
        if image.isNull():
            raise ValueError("image must not be null")
        if placement is not None and not isinstance(placement, QRectF):
            raise TypeError("placement must be a QRectF or None")
        if label is not None and not isinstance(label, str):
            raise TypeError("label must be a string or None")
        if interaction is not None and not isinstance(
            interaction, QPaneLayerInteractionPolicy
        ):
            raise TypeError("interaction must be QPaneLayerInteractionPolicy or None")
        if not isinstance(extent_policy, RasterExtentPolicy):
            raise TypeError("extent_policy must be RasterExtentPolicy")
        controller = self._editable_raster_layers
        if controller is None:
            return None
        normalized_interaction = interaction or QPaneLayerInteractionPolicy(
            selectable=True,
            movable=True,
            pixel_editable=True,
        )
        layer_id = controller.add(
            image,
            placement=placement,
            interaction=internal_layer_policy(normalized_interaction),
            label=label,
            extent_policy=extent_policy,
        )
        if layer_id is not None:
            self._handle_internal_scene_content_changed()
            self._emit_scene_changed()
        return layer_id

    def createPaintLayer(
        self,
        size: QSize | None = None,
        *,
        label: str = "Paint Layer",
        extent_policy: RasterExtentPolicy = RasterExtentPolicy.UNBOUNDED,
    ) -> uuid.UUID | None:
        """Create a transparent editable layer and select it for painting.

        Args:
            size: Initial pixel dimensions, or active scene dimensions when omitted.
            label: Host-facing layer label.
            extent_policy: Fixed or expanding future write behavior.

        Returns:
            The new layer UUID, or ``None`` when no active scene exists.

        Raises:
            TypeError: If arguments use unsupported public types.
            ValueError: If dimensions are not positive or the label is empty.

        Side effects:
            Adds and selects one scene layer and changes the active paint target.
        """
        if size is not None and not isinstance(size, QSize):
            raise TypeError("size must be a QSize or None")
        if not isinstance(label, str):
            raise TypeError("label must be a string")
        if not label.strip():
            raise ValueError("label must not be empty")
        if not isinstance(extent_policy, RasterExtentPolicy):
            raise TypeError("extent_policy must be RasterExtentPolicy")
        scene = self.currentScene()
        if scene is None:
            return None
        initial_size = (
            QSize(size)
            if size is not None
            else QSize(
                max(1, round(scene.bounds.width())),
                max(1, round(scene.bounds.height())),
            )
        )
        if initial_size.width() <= 0 or initial_size.height() <= 0:
            raise ValueError("size dimensions must be positive")
        image = QImage(initial_size, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor(0, 0, 0, 0))
        layer_id = self.addEditableRasterLayer(
            image,
            label=label,
            interaction=QPaneLayerInteractionPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
            extent_policy=extent_policy,
        )
        if layer_id is not None:
            self.setSelectedLayer(scene.scene_id, layer_id)
            self.setPaintTarget(scene.scene_id, layer_id)
        return layer_id

    def paintTargetState(self) -> QPanePaintTargetState | None:
        """Return the detached active generalized paint destination."""
        identity = self.paintingCoordinator().identity
        if identity is None:
            return None
        current_scene = self.currentScene()
        public_scene_id = (
            identity.scene_id if current_scene is None else current_scene.scene_id
        )
        source_kind = None
        if identity.layer_id is not None:
            resolved = self.sceneMutationCoordinator().find_layer(
                lambda layer: layer.scene_id == identity.scene_id
                and layer.layer_id == identity.layer_id
            )
            if resolved is None:
                return None
            source_kind = resolved[1].source.kind
        return QPanePaintTargetState(
            scene_id=public_scene_id,
            kind=identity.kind,
            layer_id=identity.layer_id,
            source_kind=source_kind,
        )

    def setPaintTarget(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Select one pixel-editable active scene layer as the brush target.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of a paint-capable layer.

        Returns:
            True when the target is valid and selected.

        Raises:
            TypeError: If either identifier is not a UUID.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        return self.paintingCoordinator().select_layer(
            self._resolve_public_scene_id(scene_id),
            layer_id,
        )

    def setPixelSelectionPaintTarget(self) -> bool:
        """Select the active composition's pixel-selection coverage for painting."""
        scene_id = self._active_resolved_scene_id()
        return bool(
            scene_id is not None
            and self.paintingCoordinator().select_pixel_selection(scene_id)
        )

    def clearPaintTarget(self) -> bool:
        """Cancel unresolved brush work and clear the generalized paint target."""
        return self.paintingCoordinator().clear()

    def brushPreset(self) -> BrushPreset:
        """Return the active immutable brush preset."""
        return self.paintingCoordinator().preset

    def setBrushPreset(self, preset: BrushPreset) -> bool:
        """Replace hardness, opacity, flow, spacing, and brush dynamics.

        Args:
            preset: Valid immutable brush configuration.

        Returns:
            True when the active preset changed.

        Raises:
            TypeError: If ``preset`` is not a ``BrushPreset``.
        """
        if not isinstance(preset, BrushPreset):
            raise TypeError("preset must be BrushPreset")
        if not self.paintingCoordinator().set_preset(preset):
            return False
        self.interaction.brush_size = max(1, round(preset.size))
        self.refreshCursor()
        self.brushPresetChanged.emit(preset)
        return True

    def paintColor(self) -> QColor:
        """Return the detached active color used by color paint targets."""
        return self.paintingCoordinator().color

    def setPaintColor(self, color: QColor) -> bool:
        """Set the detached active color used by color paint targets.

        Args:
            color: Valid Qt color, including alpha.

        Returns:
            True when the paint color changed.

        Raises:
            TypeError: If ``color`` is not a valid ``QColor``.
        """
        if not isinstance(color, QColor) or not color.isValid():
            raise TypeError("color must be a valid QColor")
        if not self.paintingCoordinator().set_color(color):
            return False
        detached = QColor(color)
        self.refreshCursor()
        self.paintColorChanged.emit(detached)
        return True

    def setBrushSize(self, size: int) -> None:
        """Set the shared brush diameter while preserving all other preset fields.

        Args:
            size: Positive brush diameter in target pixels; values below one clamp.

        Raises:
            TypeError: If ``size`` is not an integer.

        Side effects:
            Refreshes brush feedback and emits ``brushPresetChanged`` on change.
        """
        if not isinstance(size, int):
            raise TypeError("size must be an integer")
        normalized = max(1, size)
        self._masks_controller.set_brush_size(normalized)
        preset = replace(
            self.paintingCoordinator().preset,
            size=float(normalized),
        )
        if self.paintingCoordinator().set_preset(preset):
            self.brushPresetChanged.emit(preset)

    def editableRasterLayerImage(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> QImage | None:
        """Return detached pixels for an active editable raster layer."""
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        resolved_scene_id = self._resolve_public_scene_id(scene_id)
        resolved = self.sceneMutationCoordinator().find_layer(
            lambda layer: (
                layer.scene_id == resolved_scene_id and layer.layer_id == layer_id
            )
        )
        if resolved is None or not isinstance(
            resolved[1].source, EditableRasterReference
        ):
            return None
        assets = self._editable_raster_assets
        asset = None if assets is None else assets.get(resolved[1].source.raster_id)
        return None if asset is None else asset.surface.snapshot_qimage()

    def setRasterExtentPolicy(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        policy: RasterExtentPolicy,
    ) -> bool:
        """Set the write-extent policy for an active raster layer.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the raster layer to update.
            policy: Fixed or expand-on-write storage behavior.

        Returns:
            True when the source policy changed.

        Raises:
            TypeError: If identifiers or policy use unsupported types.

        Side effects:
            Emits ``sceneChanged`` without changing pixels, bounds, or placement.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not isinstance(policy, RasterExtentPolicy):
            raise TypeError("policy must be RasterExtentPolicy")
        if not self._anchor_floating_pixels_before_edit():
            return False
        coordinator = self._raster_mutations
        return bool(
            coordinator is not None
            and coordinator.set_extent_policy(
                self._resolve_public_scene_id(scene_id),
                layer_id,
                policy,
            )
        )

    def requestRasterBounds(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        bounds: QRect,
    ) -> uuid.UUID | None:
        """Request an asynchronous pad/crop of raster-local storage bounds.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the raster layer to resize.
            bounds: Positive integer bounds in layer-local coordinates.

        Returns:
            A request UUID when the source accepted work, otherwise ``None``.

        Raises:
            TypeError: If identifiers or bounds use unsupported types.
            ValueError: If bounds do not have positive dimensions.

        Side effects:
            Emits ``rasterBoundsRequestCompleted`` after the request terminates.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not isinstance(bounds, QRect):
            raise TypeError("bounds must be a QRect")
        if bounds.width() <= 0 or bounds.height() <= 0:
            raise ValueError("bounds dimensions must be positive")
        if not self._anchor_floating_pixels_before_edit():
            return None
        coordinator = self._raster_mutations
        if coordinator is None:
            return None
        request_id = coordinator.request_bounds(
            self._resolve_public_scene_id(scene_id),
            layer_id,
            RasterBounds.from_qrect(bounds),
        )
        if request_id is not None:
            self._raster_request_public_scenes[request_id] = scene_id
        return request_id

    def pixelSelectionState(self) -> QPanePixelSelectionState | None:
        """Return the active composition's detached pixel-selection state."""
        scene_id = self._active_resolved_scene_id()
        if scene_id is None:
            return None
        return self._public_pixel_selection_state(
            self.editorInteraction().pixel_selection_state(scene_id)
        )

    def setPixelSelection(
        self,
        coverage: QImage,
        bounds: QRect,
        mode: PixelSelectionMode = PixelSelectionMode.REPLACE,
    ) -> bool:
        """Combine grayscale coverage into the active composition selection.

        Args:
            coverage: Grayscale or color image interpreted as selection coverage.
            bounds: Scene-coordinate bounds occupied by ``coverage``.
            mode: Replacement, addition, subtraction, or intersection behavior.

        Returns:
            True when active selection state changed.

        Raises:
            TypeError: If inputs use unsupported public types.
            ValueError: If coverage is null or dimensions do not match bounds.
        """
        if not isinstance(coverage, QImage):
            raise TypeError("coverage must be a QImage")
        if not isinstance(bounds, QRect):
            raise TypeError("bounds must be a QRect")
        if not isinstance(mode, PixelSelectionMode):
            raise TypeError("mode must be PixelSelectionMode")
        if coverage.isNull():
            raise ValueError("coverage must not be null")
        if (
            coverage.size() != bounds.size()
            or bounds.width() <= 0
            or bounds.height() <= 0
        ):
            raise ValueError("coverage dimensions must match positive bounds")
        scene_id = self._active_resolved_scene_id()
        resolution = self.editorOperationResolver().resolve(
            EditorOperation.SELECT_PIXELS
        )
        if (
            scene_id is None
            or not resolution.allowed
            or not self._anchor_floating_pixels_before_edit()
        ):
            return False
        return self.editorInteraction().commit_pixel_selection(
            scene_id,
            CoverageSnapshot(
                bounds=RasterBounds.from_qrect(bounds),
                extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
                pixels=qimage_to_numpy_grayscale8(coverage),
            ),
            CoverageCombineMode(mode.value),
        )

    def clearPixelSelection(self) -> bool:
        """Clear pixel selection in the active composition."""
        scene_id = self._active_resolved_scene_id()
        return bool(
            scene_id is not None
            and self._anchor_floating_pixels_before_edit()
            and self.editorInteraction().clear_pixel_selection(scene_id)
        )

    def selectAllPixels(self) -> bool:
        """Select every pixel inside the active scene's finite canvas bounds."""
        scene_id = self._active_resolved_scene_id()
        resolution = self.editorOperationResolver().resolve(
            EditorOperation.SELECT_PIXELS
        )
        return bool(
            scene_id is not None
            and resolution.allowed
            and self._anchor_floating_pixels_before_edit()
            and self.editorInteraction().select_all_pixels(scene_id)
        )

    def invertPixelSelection(self) -> bool:
        """Invert pixel selection inside the active scene's finite canvas bounds."""
        scene_id = self._active_resolved_scene_id()
        resolution = self.editorOperationResolver().resolve(
            EditorOperation.SELECT_PIXELS
        )
        return bool(
            scene_id is not None
            and resolution.allowed
            and self._anchor_floating_pixels_before_edit()
            and self.editorInteraction().invert_pixel_selection(scene_id)
        )

    def selectLayerCoverage(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        mode: PixelSelectionMode = PixelSelectionMode.REPLACE,
    ) -> bool:
        """Use a coverage-producing layer as composition pixel selection."""
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not isinstance(mode, PixelSelectionMode):
            raise TypeError("mode must be PixelSelectionMode")
        resolution = self.editorOperationResolver().resolve(
            EditorOperation.SELECT_PIXELS
        )
        if not resolution.allowed or not self._anchor_floating_pixels_before_edit():
            return False
        return self.editorInteraction().select_layer_coverage(
            self._resolve_public_scene_id(scene_id),
            layer_id,
            CoverageCombineMode(mode.value),
        )

    def deleteSelectedPixels(self) -> bool:
        """Clear selected coverage from the selected policy-enabled raster layer."""
        resolution = self.editorOperationResolver().resolve(
            EditorOperation.DELETE_PIXELS
        )
        return bool(
            resolution.allowed
            and resolution.layer_id is not None
            and self._anchor_floating_pixels_before_edit()
            and self.editorInteraction().delete_selected_pixels()
        )

    def floatingPixelEditState(self) -> QPaneFloatingPixelEditState | None:
        """Return detached state for the active unresolved floating-pixel edit."""
        movement = self._selected_pixel_movement
        if movement is None or not movement.active:
            return None
        scene_id = movement.scene_id
        source_layer_id = movement.source_layer_id
        if scene_id is None or source_layer_id is None:
            return None
        public_scene = self.currentScene()
        return QPaneFloatingPixelEditState(
            scene_id=(scene_id if public_scene is None else public_scene.scene_id),
            source_layer_id=source_layer_id,
            mode=(
                FloatingPixelMode.CUT if movement.cut_source else FloatingPixelMode.COPY
            ),
            offset=movement.offset,
            bounds=movement.scene_bounds,
        )

    def anchorFloatingPixels(
        self,
        scene_id: uuid.UUID | None = None,
        layer_id: uuid.UUID | None = None,
    ) -> bool:
        """Resolve floating pixels into their source or a compatible layer.

        Args:
            scene_id: Optional public destination scene identifier.
            layer_id: Optional destination layer identifier.

        Returns:
            True when an unresolved edit was resolved.

        Raises:
            TypeError: If supplied identifiers are not UUIDs.
            ValueError: If exactly one destination identifier is supplied.
        """
        if (scene_id is None) != (layer_id is None):
            raise ValueError("scene_id and layer_id must be supplied together")
        if scene_id is not None and not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID or None")
        if layer_id is not None and not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID or None")
        movement = self._editor_movement_interaction
        if movement is None:
            return False
        if scene_id is None:
            return movement.anchor_floating_pixels()
        return movement.anchor_floating_pixels_to(
            self._resolve_public_scene_id(scene_id),
            layer_id,
        )

    def promoteFloatingPixels(self, label: str | None = None) -> uuid.UUID | None:
        """Resolve floating pixels into a newly created compatible layer."""
        if label is not None and not isinstance(label, str):
            raise TypeError("label must be a string or None")
        movement = self._editor_movement_interaction
        return None if movement is None else movement.promote_floating_pixels(label)

    def cancelFloatingPixels(self) -> bool:
        """Discard an unresolved floating edit without changing source pixels."""
        movement = self._selected_pixel_movement
        return bool(movement is not None and movement.cancel())

    def sceneEditUndoAvailable(self) -> bool:
        """Return whether the active scene has an undoable composition edit."""
        movement = self._selected_pixel_movement
        if movement is not None and movement.active:
            return True
        scene_id = self._active_resolved_scene_id()
        return bool(
            scene_id is not None
            and self.compositionService().edit_controller.can_undo(scene_id)
        )

    def sceneEditRedoAvailable(self) -> bool:
        """Return whether the active scene has a redoable composition edit."""
        movement = self._selected_pixel_movement
        if movement is not None and movement.active:
            return False
        scene_id = self._active_resolved_scene_id()
        return bool(
            scene_id is not None
            and self.compositionService().edit_controller.can_redo(scene_id)
        )

    def undoSceneEdit(self) -> bool:
        """Undo the latest chronological editor change in the active scene."""
        movement = self._selected_pixel_movement
        if movement is not None and movement.active:
            if movement.offset.isNull():
                return movement.cancel()
            if not movement.anchor_to_source():
                return False
        scene_id = self._active_resolved_scene_id()
        if scene_id is None:
            return False
        result = self.compositionService().edit_controller.undo(scene_id)
        if result.changed:
            self._publish_scene_transform_change()
        return result.changed

    def redoSceneEdit(self) -> bool:
        """Redo the next chronological editor change in the active scene."""
        movement = self._selected_pixel_movement
        if movement is not None and movement.active:
            return False
        scene_id = self._active_resolved_scene_id()
        if scene_id is None:
            return False
        result = self.compositionService().edit_controller.redo(scene_id)
        if result.changed:
            self._publish_scene_transform_change()
        return result.changed

    def registerSceneOverlay(
        self,
        name: str,
        draw_fn: SceneOverlayDrawFn,
    ) -> None:
        """Register a scene overlay painted relative to layered scene composition layers.

        Raises:
            ValueError: If `name` is already present.
        """
        self.interaction.registerSceneOverlay(name, draw_fn)

    def unregisterSceneOverlay(self, name: str) -> None:
        """Remove a previously registered scene overlay."""
        self.interaction.unregisterSceneOverlay(name)

    def sceneOverlays(self) -> Mapping[str, SceneOverlayDrawFn]:
        """Return a read-only snapshot of registered scene overlays."""
        return self.interaction.scene_overlays_snapshot()

    def overlaysSuspended(self) -> bool:
        """Return True when interaction-managed overlays are currently suppressed."""
        return self.interaction.overlays_suspended

    def overlaysResumePending(self) -> bool:
        """Indicate overlays should resume once pending activation work finishes."""
        return self.interaction.overlays_resume_pending

    def resumeOverlays(self) -> None:
        """Allow overlay drawing to resume on the next paint."""
        self.interaction.resume_overlays()

    def resumeOverlaysAndUpdate(self) -> None:
        """Resume overlays and trigger a repaint."""
        self.interaction.resume_overlays_and_update()

    def maybeResumeOverlays(self) -> None:
        """Resume overlays when activation has completed for the active image."""
        self.interaction.maybe_resume_overlays()

    def registerCursorProvider(self, mode: str, provider: CursorProvider) -> None:
        """Attach a cursor provider via the supported facade helper.

        If the mode is active when this is called, the cursor updates immediately.
        """
        self.interaction.registerCursorProvider(mode, provider)

    def unregisterCursorProvider(self, mode: str) -> None:
        """Detach a previously registered cursor provider."""
        self.interaction.unregisterCursorProvider(mode)

    def registerTool(
        self,
        mode: str,
        factory: ToolFactory,
        *,
        on_connect: ToolSignalBinder | None = None,
        on_disconnect: ToolSignalBinder | None = None,
    ) -> None:
        """Register a custom control mode through the supported facade API.

        Args:
            mode: Unique identifier for the tool mode.
            factory: Callable that creates a tool instance when the mode activates.
            on_connect: Optional binder for wiring tool-specific signals.
            on_disconnect: Optional binder invoked during teardown to unwire signals.
        """
        self.hooks.registerTool(
            mode,
            factory,
            on_connect=on_connect,
            on_disconnect=on_disconnect,
        )

    def unregisterTool(self, mode: str) -> None:
        """Remove a previously registered tool mode via the supported facade."""
        self.hooks.unregisterTool(mode)

    def setImagesByID(
        self,
        image_map: ImageMap,
        current_id: uuid.UUID,
    ):
        """Replace the catalog contents and navigate to ``current_id`` via the facade."""
        self._cancel_floating_pixels_for_context_change()
        catalog = self.catalog()
        removed_image_ids = tuple(set(catalog.imageIDs()) - set(image_map))
        self._masks_controller.prepare_catalog_image_removal(removed_image_ids)
        catalog.setImagesByID(image_map, current_id)
        self._sync_compositions_with_catalog()
        if current_id in self.catalog().imageIDs():
            self._activate_default_composition_for_image(current_id)

    def clearImages(self):
        """Reset the catalog, linked views, and caches before showing the configured placeholder."""
        self._cancel_floating_pixels_for_context_change()
        catalog = self.catalog()
        self._masks_controller.prepare_catalog_image_removal(tuple(catalog.imageIDs()))
        catalog.clearImages()
        self._scene_selection.clear()
        if self.compositionService().clear():
            self._emit_composition_changed()
            self._emit_composition_selection_changed(None)
            self._emit_scene_changed()

    def removeImageByID(self, image_id: uuid.UUID):
        """Remove ``image_id`` when present; callers remain responsible for navigation."""
        self._cancel_floating_pixels_for_context_change()
        catalog = self.catalog()
        self._masks_controller.prepare_catalog_image_removal((image_id,))
        catalog.removeImageByID(image_id)
        self._sync_compositions_with_catalog()

    def removeImagesByID(self, image_ids: list[uuid.UUID]):
        """Remove the provided image IDs when present without selecting a fallback."""
        self._cancel_floating_pixels_for_context_change()
        catalog = self.catalog()
        self._masks_controller.prepare_catalog_image_removal(tuple(image_ids))
        catalog.removeImagesByID(image_ids)
        self._sync_compositions_with_catalog()

    def setCurrentImageID(self, image_id: uuid.UUID | None):
        """Navigate to ``image_id`` while overlays are suspended for navigation.

        If ``image_id`` is None, the current image is deselected and the qpane
        reverts to its configured fallback state (placeholder or blank).
        """
        self._cancel_floating_pixels_for_context_change()
        self.interaction.suspend_overlays_for_navigation()
        catalog = self.catalog()
        catalog.setCurrentImageID(image_id)
        if image_id is None:
            if self.compositionService().clear_selection():
                self._emit_composition_selection_changed(None)
                self._emit_scene_changed()
            self._emit_catalog_selection_changed(None)
            self._handle_comparison_changed()
        elif catalog.currentImageID() == image_id:
            self._activate_default_composition_for_image(image_id)

    def setAllImagesLinked(self, enabled: bool):
        """Toggle pan/zoom synchronization across all images."""
        image_ids = self.catalog().imageIDs()
        if enabled and len(image_ids) >= 2:
            members = tuple(image_ids)
            existing = self.linkedGroups()
            reuse_id = None
            for group in existing:
                if set(group.members) == set(members):
                    reuse_id = group.group_id
                    break
            group_id = reuse_id if reuse_id is not None else uuid.uuid4()
            self.setLinkedGroups((LinkedGroup(group_id=group_id, members=members),))
        else:
            self.setLinkedGroups(())

    def setLinkedGroups(self, groups: Iterable[LinkedGroup]) -> None:
        """Define linked pan/zoom groups and emit link change signals.

        Args:
            groups: LinkedGroup definitions to persist.

        Side effects:
            Emits ``linkGroupsChanged`` when the group definition changes.
        """
        self.linkManager().setGroups(tuple(groups))
        self._maybe_emit_link_groups_changed()

    def compose(
        self,
        *,
        images: Iterable[uuid.UUID],
        title: str | None = None,
    ) -> uuid.UUID:
        """Create and open a persistent composition from catalog image IDs.

        Args:
            images: One or two catalog image UUIDs in composition order.
            title: Optional host-facing title.

        Raises:
            KeyError: If any image ID is not in the catalog.
            ValueError: If the image list is empty, too long, or duplicated.

        Side effects:
            Opens the new composition, updates catalog selection to its base
            image, emits composition signals, and refreshes comparison state.
        """
        image_ids = tuple(images)
        missing = [
            image_id
            for image_id in image_ids
            if not self._image_catalog.containsImage(image_id)
        ]
        if missing:
            raise KeyError("compose image IDs must exist in the catalog")
        record = self.compositionService().compose(
            image_ids,
            title=title,
            path_lookup=self.imagePath,
        )
        self._open_composition_record(record)
        self._emit_composition_changed()
        return record.composition_id

    def openComposition(self, composition_id: uuid.UUID) -> None:
        """Open an existing composition by UUID.

        Args:
            composition_id: Composition UUID returned by composition APIs.

        Raises:
            KeyError: If ``composition_id`` is unknown.
            TypeError: If ``composition_id`` is not a UUID.

        Side effects:
            Updates the effective catalog selection and emits composition
            selection/comparison state.
        """
        record = self.compositionService().open_composition(composition_id)
        self._open_composition_record(record)

    def removeComposition(self, composition_id: uuid.UUID) -> None:
        """Remove a composition when its document policy permits removal.

        Raises:
            ValueError: If document policy prevents removal.
            KeyError: If ``composition_id`` is unknown.

        Side effects:
            Emits composition change signals and opens the next available
            composition when the removed one was active.
        """
        service = self.compositionService()
        previous_id = service.current_composition_id()
        service.remove_composition(composition_id)
        active = service.active_record()
        if previous_id == composition_id and active is not None:
            self._open_composition_record(active)
        elif active is None:
            self.setCurrentImageID(None)
        self._emit_composition_changed()

    def getCatalogSnapshot(self) -> CatalogSnapshot:
        """Return a structured catalog snapshot for host consumption.

        Returns:
            CatalogSnapshot: Ordered catalog entries, linked groups, and active IDs.
        """
        image_ids = tuple(self.imageIDs())
        all_images = self.allImages
        all_paths = self.allImagePaths
        catalog_entries: dict[uuid.UUID, CatalogEntry] = {}
        for image_id, image, path in zip(image_ids, all_images, all_paths):
            catalog_entries[image_id] = CatalogEntry(image=image, path=path)
        return CatalogSnapshot(
            catalog=catalog_entries,
            linked_groups=tuple(self.linkedGroups()),
            order=image_ids,
            current_image_id=self.currentImageID(),
            active_mask_id=self.activeMaskID(),
            mask_capable=self.maskFeatureAvailable(),
        )

    def createBlankMask(self, size: QSize) -> "uuid.UUID | None":
        """Create an empty mask layer in the active composition.

        Args:
            size: Dimensions of the new mask in local raster pixels.

        Returns:
            The new mask UUID, or None when mask tooling is unavailable.

        Side effects:
            Emits ``catalogChanged`` with ``maskCreated`` when a mask is created.
        """
        mask_id = self._masks_controller.create_blank_mask(size)
        if mask_id is not None:
            self._emit_catalog_mutation("maskCreated", affected_ids=(mask_id,))
        return mask_id

    def loadMaskFromFile(self, path: str) -> "uuid.UUID | None":
        """Load a mask layer from disk and return its ID when available.

        Side effects:
            Emits ``catalogChanged`` with ``maskImported`` when a mask is loaded.
        """
        mask_id = self._masks_controller.load_mask_from_file(path)
        if mask_id is not None:
            self._emit_catalog_mutation("maskImported", affected_ids=(mask_id,))
        return mask_id

    def removeMaskFromImage(self, image_id: uuid.UUID, mask_id: uuid.UUID) -> bool:
        """Remove `mask_id` from `image_id` through the active mask service.

        Side effects:
            Emits ``catalogChanged`` with ``maskDeleted`` when removal succeeds.
            Emits ``catalogSelectionChanged`` for the active image when removal succeeds.
        """
        self._cancel_floating_pixels_for_context_change()
        removed = self._masks_controller.remove_mask_from_image(image_id, mask_id)
        if removed:
            self._emit_catalog_mutation("maskDeleted", affected_ids=(mask_id,))
            self._emit_catalog_selection_changed(image_id)
        return removed

    def setActiveMaskID(self, mask_id):
        """Set the active mask for editing while letting the service manage ordering."""
        self._cancel_floating_pixels_for_context_change()
        changed = self._masks_controller.set_active_mask_id(mask_id)
        if changed:
            self._synchronize_active_mask_layer_selection()
            current_id = None
            try:
                current_id = self.catalog().currentImageID()
            except RuntimeError:
                current_id = None
            self._emit_catalog_selection_changed(current_id)
        return changed

    def setMaskProperties(
        self, mask_id, color: QColor | None = None, opacity: float | None = None
    ):
        """Update display properties for ``mask_id``.

        Args:
            mask_id: Identifier of the mask to update.
            color: New color when provided; leave unchanged when None.
            opacity: New opacity when provided; leave unchanged when None.
        """
        changed = self._masks_controller.set_mask_properties(
            mask_id, color=color, opacity=opacity
        )
        if changed:
            self._emit_catalog_mutation(
                "maskPropertiesChanged", affected_ids=(mask_id,)
            )
        return changed

    def prefetchMaskOverlays(
        self, image_id: uuid.UUID | None, *, reason: str = "navigation"
    ) -> bool:
        """Request asynchronous warming of mask renders for `image_id` when masking is available."""
        return self._masks_controller.prefetch_mask_overlays(image_id, reason=reason)

    def cycleMasksForward(self):
        """Cycle the mask layer stack forward, moving the bottom layer to the top."""
        self._cancel_floating_pixels_for_context_change()
        return self._masks_controller.cycle_masks_forward()

    def cycleMasksBackward(self):
        """Cycle the mask layer stack backward, moving the top layer to the bottom."""
        self._cancel_floating_pixels_for_context_change()
        return self._masks_controller.cycle_masks_backward()

    def undoMaskEdit(self) -> bool:
        """Undo the last mask edit through the mask workflow."""
        movement = self._selected_pixel_movement
        if movement is not None and movement.active:
            return self.undoSceneEdit()
        return self._masks_controller.undo_mask_edit()

    def redoMaskEdit(self) -> bool:
        """Redo the last reverted mask edit through the mask workflow."""
        movement = self._selected_pixel_movement
        if movement is not None and movement.active:
            return False
        return self._masks_controller.redo_mask_edit()

    def setControlMode(
        self,
        mode: str,
    ):
        """Delegate control-mode changes to the interaction layer."""
        if self.catalog().placeholderActive():
            mask_modes = {
                Tools.CONTROL_MODE_DRAW_BRUSH,
                Tools.CONTROL_MODE_SMART_SELECT,
            }
            if mode in mask_modes:
                logger.info(
                    "Ignoring mask control mode while placeholder is active: %s", mode
                )
                return
        self.interaction.set_control_mode(mode)

    def setComparisonImageID(self, image_id: uuid.UUID) -> None:
        """Use a catalog image as the comparison reveal source.

        Args:
            image_id: Catalog UUID to render as the comparison image.

        Raises:
            KeyError: If ``image_id`` is not in the catalog.
            TypeError: If ``image_id`` is not a UUID.

        Side effects:
            Marks the rendered scene dirty and emits ``comparisonChanged``.
        """
        self._comparison_service().set_catalog_image(image_id)

    def clearComparisonImage(self) -> None:
        """Disable comparison rendering and repaint the current scene."""
        self._comparison_service().clear()

    def setComparisonSplit(
        self,
        position: float,
        orientation: ComparisonOrientation | str | None = None,
    ) -> None:
        """Set the comparison reveal split.

        Args:
            position: Normalized split position from ``0.0`` to ``1.0``.
            orientation: Optional split orientation.

        Raises:
            ValueError: If ``position`` is not numeric or orientation is unknown.

        Side effects:
            Marks the rendered scene dirty and emits ``comparisonChanged``.
        """
        self._comparison_service().set_split(position, orientation)

    def comparisonState(self) -> ComparisonState:
        """Return the current comparison rendering state."""
        return self._comparison_service().state()

    def comparisonDividerInteractive(self) -> bool:
        """Return whether comparison-divider dragging is enabled."""
        return self.comparisonDividerInteraction().interactive()

    def setComparisonDividerInteractive(self, enabled: bool) -> None:
        """Enable or disable built-in comparison-divider dragging.

        Args:
            enabled: Whether the split boundary should accept mouse drags while
                comparison rendering is active.

        Raises:
            TypeError: If ``enabled`` is not a bool.

        Side effects:
            Clears any active divider drag, refreshes the cursor, and schedules a
            repaint.
        """
        self.comparisonDividerInteraction().set_interactive(enabled)
        self.refreshCursor()
        self.update()

    def comparisonDividerState(self) -> ComparisonDividerState:
        """Return host-facing comparison divider geometry and interaction state."""
        return self.comparisonDividerInteraction().state()

    # ========================================================================
    # Internal Implementation
    # ========================================================================

    def catalog(self) -> Catalog:
        """Expose the catalog facade managing catalog state and navigation hooks."""
        if self._catalog is None:
            raise AttributeError("Catalog accessed before initialization")
        return self._catalog

    def compositionService(self) -> CompositionService:
        """Expose the internal composition owner."""
        if self._composition_service is None:
            raise AttributeError("Composition service accessed before initialization")
        return self._composition_service

    def view(self) -> View:
        """Expose the view collaborator that owns viewport, tile, and swap services."""
        if self._view is None:
            raise AttributeError("View accessed before initialization")
        return self._view

    def presenter(self) -> RenderingPresenter:
        """Expose the RenderingPresenter managed by the rendering stack."""
        return self.view().presenter

    def sceneMutationCoordinator(self) -> SceneMutationCoordinator:
        """Expose internal scene mutation routing for feature workflows."""
        coordinator = self._scene_mutations
        if coordinator is None:
            raise AttributeError(
                "Scene mutation coordinator accessed before initialization"
            )
        return coordinator

    def pixelSelectionService(self) -> PixelSelectionService:
        """Expose the composition-scoped pixel-selection owner internally."""
        service = self._pixel_selection
        if service is None:
            raise AttributeError(
                "Pixel selection service accessed before initialization"
            )
        return service

    def editorInteraction(self) -> EditorInteractionCoordinator:
        """Expose source-neutral editor interaction coordination internally."""
        interaction = self._editor_interaction
        if interaction is None:
            raise AttributeError("Editor interaction accessed before initialization")
        return interaction

    def sceneLayerMovementInteraction(self) -> SceneLayerMovementInteraction:
        """Expose private panel-to-scene movement adaptation."""
        interaction = self._scene_movement_interaction
        if interaction is None:
            raise AttributeError("Scene layer movement accessed before initialization")
        return interaction

    def sceneLayerTransformInteraction(self) -> EditorTransformInteraction:
        """Expose private panel-space affine transform interaction."""
        interaction = self._scene_transform_interaction
        if interaction is None:
            raise AttributeError("Scene layer transform accessed before initialization")
        return interaction

    def editorMovementInteraction(self) -> EditorMovementInteraction:
        """Expose private selection-aware movement arbitration."""
        interaction = self._editor_movement_interaction
        if interaction is None:
            raise AttributeError("Editor movement accessed before initialization")
        return interaction

    def editorOperationResolver(self) -> EditorOperationResolver:
        """Expose private source-neutral operation resolution."""
        resolver = self._operation_resolver
        if resolver is None:
            raise AttributeError(
                "Editor operation resolver accessed before initialization"
            )
        return resolver

    def activeMaskLayerCoordinates(self) -> ActiveMaskLayerCoordinates:
        """Expose private active-mask layer coordinate mapping."""
        coordinates = self._active_mask_coordinates
        if coordinates is None:
            raise AttributeError(
                "Active mask coordinates accessed before initialization"
            )
        return coordinates

    def _active_resolved_scene_id(self) -> uuid.UUID | None:
        """Return the active internal scene identifier used for mutation routing."""
        scene = self.sceneMutationCoordinator().active_scene()
        return None if scene is None else scene.scene_id

    def _active_public_scene_id(self) -> uuid.UUID | None:
        """Return the active host-facing scene identifier."""
        scene = self.currentScene()
        return None if scene is None else scene.scene_id

    def _vector_editor_controller(self) -> VectorHostFacade:
        """Return the installed host-facing vector delegation owner."""
        if self._vector_editor is None:
            raise AttributeError("Vector editor accessed before initialization")
        return self._vector_editor

    def _vector_interaction_controller(self) -> VectorInteractionController:
        """Return the installed vector tool policy and gesture coordinator."""
        if self._vector_interaction is None:
            raise AttributeError("Vector interaction accessed before initialization")
        return self._vector_interaction

    def _vector_node_controller(self) -> VectorNodeEditController:
        """Return the installed vector node-edit session owner."""
        if self._vector_nodes is None:
            raise AttributeError("Vector node editing accessed before initialization")
        return self._vector_nodes

    def _vector_text_controller(self) -> VectorTextEditController:
        """Return the installed semantic text-edit session owner."""
        if self._vector_text is None:
            raise AttributeError("Vector text editing accessed before initialization")
        return self._vector_text

    @staticmethod
    def _validate_vector_ids(*identifiers: uuid.UUID) -> None:
        """Validate stable vector scene, layer, and object identities."""
        if any(not isinstance(identifier, uuid.UUID) for identifier in identifiers):
            raise TypeError("vector identifiers must be UUID values")

    def _resolve_public_scene_id(self, scene_id: uuid.UUID) -> uuid.UUID:
        """Map a public default-composition ID to its resolved scene ID."""
        active_scene = self.sceneMutationCoordinator().active_scene()
        public_scene = self.currentScene()
        if (
            active_scene is not None
            and active_scene.scene_id != scene_id
            and public_scene is not None
            and public_scene.scene_id == scene_id
        ):
            return active_scene.scene_id
        return scene_id

    def _placed_scope(
        self, scene_id: uuid.UUID, layer_id: uuid.UUID
    ) -> uuid.UUID | None:
        """Resolve an active public layer identity to its composition scope."""
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        public_scene = self.currentScene()
        scope_id = self.compositionService().current_composition_id()
        if public_scene is None or scope_id is None:
            return None
        if scene_id not in {public_scene.scene_id, public_scene.composition_id}:
            return None
        instance = self.compositionService().layers.layer(scope_id, layer_id)
        return (
            scope_id
            if instance is not None
            and isinstance(instance.source, PlacedAssetReference)
            else None
        )

    @staticmethod
    def _validate_placed_inputs(
        image: QImage | None,
        placement: QRectF | None,
        label: str | None,
        interaction: QPaneLayerInteractionPolicy | None,
    ) -> None:
        """Validate common public placed-layer creation inputs."""
        if image is not None:
            if not isinstance(image, QImage):
                raise TypeError("image must be a QImage")
            if image.isNull():
                raise ValueError("image must not be null")
        if placement is not None and not isinstance(placement, QRectF):
            raise TypeError("placement must be a QRectF or None")
        if label is not None and not isinstance(label, str):
            raise TypeError("label must be a string or None")
        if interaction is not None and not isinstance(
            interaction, QPaneLayerInteractionPolicy
        ):
            raise TypeError("interaction must be QPaneLayerInteractionPolicy or None")

    @staticmethod
    def _layer_placement(placement: QRectF | None) -> LayerPlacement | None:
        """Convert optional detached public geometry to an internal value."""
        if placement is None:
            return None
        return LayerPlacement(
            placement.x(),
            placement.y(),
            placement.width(),
            placement.height(),
        )

    def _publish_scene_transform_change(self) -> None:
        """Refresh rendering and publish scene transform/history state."""
        self.view().invalidate_content_cache()
        self._handle_internal_scene_content_changed()
        self._emit_scene_changed()

    def _refresh_scene_transform_preview(self) -> None:
        """Invalidate scene pixels and schedule painting for transient geometry."""
        self.view().mark_dirty()
        self.update()

    def _refresh_selected_pixel_move_preview(self) -> None:
        """Invalidate only old/new preview pixels and refresh translated ants."""
        movement = self._selected_pixel_movement
        scene_id = self._active_resolved_scene_id()
        selection_state = None
        if movement is not None:
            selection_state = movement.preview_state
        suppress_selection = bool(movement is not None and movement.transforming)
        if selection_state is None and scene_id is not None and not suppress_selection:
            selection_state = self.pixelSelectionService().state(scene_id)
        if suppress_selection:
            selection_state = None
        self._editor_overlays.set_selection(selection_state)
        floating_state = self.floatingPixelEditState()
        if floating_state != self._last_floating_pixel_state:
            self._last_floating_pixel_state = floating_state
            self.floatingPixelEditChanged.emit(floating_state)
            self.sceneEditHistoryChanged.emit(
                self.sceneEditUndoAvailable(),
                self.sceneEditRedoAvailable(),
            )
        self.update()

    def _anchor_floating_pixels_before_edit(self) -> bool:
        """Resolve transient content before an incompatible durable edit."""
        movement = self._selected_pixel_movement
        return bool(
            movement is None or not movement.active or movement.anchor_to_source()
        )

    def _cancel_floating_pixels_for_context_change(self) -> None:
        """Restore source pixels before abandoning their composition context."""
        movement = self._selected_pixel_movement
        if movement is not None:
            movement.cancel()

    def sceneProviderRegistry(self) -> SceneProviderRegistry:
        """Expose private scene-provider registration for feature workflows."""
        registry = self._scene_provider_registry
        if registry is None:
            raise AttributeError(
                "Scene provider registry accessed before initialization"
            )
        return registry

    def layerSourceCapabilities(self) -> LayerSourceCapabilities:
        """Expose private focused source capabilities for feature wiring."""
        capabilities = self._source_capabilities
        if capabilities is None:
            raise AttributeError(
                "Layer source capabilities accessed before initialization"
            )
        return capabilities

    def paintingCoordinator(self) -> PaintingCoordinator:
        """Expose the internal source-neutral painting coordinator."""
        coordinator = self._painting
        if coordinator is None:
            raise AttributeError("painting coordinator accessed before initialization")
        return coordinator

    def comparisonDividerInteraction(self) -> CompareDividerInteraction:
        """Expose the internal comparison divider interaction owner."""
        interaction = self._compare_interaction
        if interaction is None:
            raise AttributeError(
                "Comparison divider interaction accessed before initialization"
            )
        return interaction

    def linkManager(self) -> LinkManager:
        """Expose the link manager coordinating linked-view groups."""
        return self.view().link_manager

    def diagnostics(self) -> Diagnostics:
        """Expose the diagnostics coordinator for this QPane."""
        return self._diagnostics_manager

    def diagnosticsOverlayController(self) -> DiagnosticsOverlayController:
        """Return the diagnostics overlay controller owned by this QPane."""
        controller = self._diagnostics_overlay_controller
        if controller is None:
            controller = DiagnosticsOverlayController(self)
            self._diagnostics_overlay_controller = controller
        return controller

    def _comparison_service(self) -> CompareService:
        """Return the internal compare service."""
        service = self.compare_service
        if service is None:
            raise AttributeError("Compare service accessed before initialization")
        return service

    @staticmethod
    def _aspect_scene_rect(
        source_size: QSize,
        target_rect: QRectF,
        *,
        cover: bool,
    ) -> QRectF:
        """Return an aspect-preserving rectangle centered on ``target_rect``."""
        source_width = float(source_size.width())
        source_height = float(source_size.height())
        if source_width <= 0.0 or source_height <= 0.0:
            raise ValueError("source_size dimensions must be positive")
        target = QRectF(target_rect)
        target_width = float(target.width())
        target_height = float(target.height())
        if target_width < 0.0 or target_height < 0.0:
            raise ValueError("target_rect dimensions must be non-negative")
        center = target.center()
        if target_width == 0.0 or target_height == 0.0:
            return QRectF(center.x(), center.y(), 0.0, 0.0)
        source_aspect = source_width / source_height
        target_aspect = target_width / target_height
        use_target_width = (
            target_aspect > source_aspect if cover else target_aspect <= source_aspect
        )
        if use_target_width:
            width = target_width
            height = width / source_aspect
        else:
            height = target_height
            width = height * source_aspect
        return QRectF(
            center.x() - width / 2.0,
            center.y() - height / 2.0,
            width,
            height,
        )

    def _scene_hit_test(self, panel_pos: QPoint) -> SceneLayerHitTestResult | None:
        """Return private scene-layer hit-test metadata for ``panel_pos``."""
        return self.view().scene_hit_test(panel_pos)

    @property
    def executor(self) -> TaskExecutorProtocol:
        """Return the task executor shared across QPane subsystems."""
        return self._state.executor

    @property
    def cacheCoordinator(self) -> CacheCoordinator | None:
        """Return the cache coordinator when coordination is enabled."""
        return self._state.cache_coordinator

    @property
    def swapDelegate(self) -> SwapDelegate:
        """Expose the swap delegate orchestrating catalog navigation."""
        return self.view().swap_delegate

    @property
    def _masks_controller(self) -> Masks:
        """Return the masks workflow controller."""
        if self._masks is None:
            raise AttributeError("Masks accessed before initialization")
        return self._masks

    @property
    def _tools_manager(self) -> Tools:
        """Return the tools manager orchestrating input modes."""
        if self._tools is None:
            raise AttributeError("Tools accessed before initialization")
        return self._tools

    @property
    def hooks(self) -> QPaneHooks:
        """Expose internal hook helpers reserved for QPane feature installers.

        Hosts must use the QPane.register* facade methods instead of calling this property directly.
        """
        return self._hooks

    def _init_core_components(self) -> None:
        """Build and install the always-on viewer and editor collaboration graph."""
        self._state.cache_coordinator = self._state.build_cache_coordinator()
        self._state.cache_registry = CacheRegistry(self._state.cache_coordinator)
        components = EditorCompositionRoot().build(
            EditorRootInputs(
                qpane=self,
                state=self._state,
                settings=self.settings,
                executor=self.executor,
                cache_registry=self._state.cache_registry,
                diagnostics=self._diagnostics_manager,
                layer_selection=self._scene_selection,
                transform_preview=self._scene_transform_preview,
                selection_projections=self._selection_layer_projections,
                floating_promotions=self._floating_layer_promotions,
                editor_policy=self._editor_policy,
                callbacks=EditorRootCallbacks(
                    composition_history_changed=(
                        self._handle_composition_edit_history_changed
                    ),
                    composition_layers_changed=(
                        self._handle_composition_layers_changed
                    ),
                    pixel_selection_changed=self._handle_pixel_selection_changed,
                    transform_changed=self._publish_scene_transform_change,
                    transform_preview_changed=self._refresh_scene_transform_preview,
                    raster_structure_changed=self._handle_raster_structure_changed,
                    raster_bounds_completed=self._handle_raster_bounds_completion,
                    scene_content_changed=lambda _bounds: (
                        self._handle_internal_scene_content_changed()
                    ),
                    placed_asset_changed=self._handle_placed_asset_changed,
                    pixel_move_preview_changed=(
                        self._refresh_selected_pixel_move_preview
                    ),
                    comparison_changed=self._handle_comparison_changed,
                    active_mask_id=lambda: (
                        None if self._masks is None else self._masks.active_mask_id()
                    ),
                    placed_asset_completed=self._handle_placed_asset_completion,
                    current_edit_scope_id=self._active_resolved_scene_id,
                    paint_target_changed=self._handle_paint_target_changed,
                    default_paint_target_available=(
                        self._default_mask_paint_target_available
                    ),
                    vector_selection_changed=self._handle_vector_selection_changed,
                    vector_node_selection_changed=(
                        self._handle_vector_node_selection_changed
                    ),
                    vector_text_edit_changed=self._handle_vector_text_edit_changed,
                    vector_content_changed=self._publish_vector_content_change,
                    vector_options_changed=self._handle_vector_options_changed,
                    vector_conversion_completed=(
                        self._handle_vector_conversion_completion
                    ),
                ),
            )
        )
        self._scene_provider_registry = components.scene_providers
        self._source_capabilities = components.source_capabilities
        self._image_catalog = components.image_catalog
        self._composition_service = components.compositions
        self._editable_raster_assets = components.editable_raster_assets
        self._editable_raster_layers = components.editable_raster_layers
        self._placed_assets = components.placed_assets
        self._placed_asset_workflow = components.placed_asset_workflow
        self._placed_asset_rasterization = components.placed_asset_rasterization
        self.destroyed.connect(
            lambda _obj=None, workflow=components.placed_asset_workflow: (
                workflow.shutdown()
            )
        )
        self.destroyed.connect(
            lambda _obj=None, service=components.placed_asset_rasterization: (
                service.shutdown()
            )
        )
        self.destroyed.connect(
            lambda _obj=None, service=components.vector.conversions: (
                service.shutdown()
            )
        )
        self._pixel_selection = components.pixel_selection
        self._painting = components.painting
        self._vector_editor = VectorHostFacade(
            compositions=components.compositions,
            assets=components.vector.assets,
            layers=components.vector.layers,
            edits=components.vector.edits,
            selection=components.vector.selection,
            current_scene=components.view.current_scene_descriptor,
            current_public_scene_id=self._active_public_scene_id,
            changed=self._publish_vector_content_change,
            conversions=components.vector.conversions,
            masks=components.vector.masks,
            targets=components.vector.targets,
            layer_selection=self._scene_selection,
            nodes=components.vector.nodes,
            texts=components.vector.texts,
        )
        self._vector_interaction = components.vector.interaction
        self._vector_nodes = components.vector.nodes
        self._vector_text = components.vector.texts
        self._composition_layer_assembler = components.layer_assembler
        self._view = components.view
        self._scene_mutations = components.scene_mutations
        self._scene_movement = components.scene_movement
        self._scene_movement_interaction = components.scene_movement_interaction
        self._scene_transform_interaction = components.scene_transform_interaction
        self._raster_mutations = components.raster_mutations
        self._layer_pixel_owners = components.pixel_owners
        self._layer_pixel_mutations = components.pixel_mutations
        self._editor_interaction = components.editor_interaction
        self._raster_floating_layer_owner = components.raster_floating_owner
        self._selected_pixel_movement = components.selected_pixel_movement
        self._editor_movement_interaction = components.editor_movement_interaction
        self._operation_resolver = components.operation_resolver
        self._active_mask_coordinates = components.active_mask_coordinates
        self._catalog = components.catalog
        self._composition_scene_adapter = components.composition_scene_adapter
        self.compare_service = components.compare_service
        self._compare_interaction = components.compare_interaction
        self._tools = components.tools
        tool_signals = components.tools.signals
        tool_signals.stroke_applied.connect(components.painting.apply)
        tool_signals.stroke_completed.connect(components.painting.commit)
        tool_signals.stroke_cancelled.connect(components.painting.cancel)
        tool_signals.undo_state_push_requested.connect(components.painting.begin)
        tool_signals.brush_size_changed.connect(self.setBrushSize)
        self.cursor_builder = components.cursor_builder
        self.mask_service = None
        self.mask_controller = None
        self._sam_manager = None
        self._autosave_manager = None

    def _wire_facade_signals(self) -> None:
        """Connect facade-level signals for catalog, link, and diagnostics events."""
        catalog = self.catalog()
        catalog.setMutationListener(self._handle_catalog_mutation)
        self.currentImageChanged.connect(self._handle_current_image_changed_signal)
        controller = self.diagnosticsOverlayController()
        controller.setOverlayChangedCallback(self._handle_diagnostics_overlay_toggled)
        controller.setDetailChangedCallback(self._handle_diagnostics_detail_toggled)
        self._last_link_groups = self._normalized_link_groups()
        self._emit_catalog_selection_changed(self.catalog().currentImageID())

    def _schedule_initial_view_signals(self) -> None:
        """Ensure the first zoom/viewport signals emit once Qt shows the widget."""
        if self._initial_view_signals_scheduled:
            return
        self._initial_view_signals_scheduled = True
        QTimer.singleShot(0, self, self._emit_initial_view_signals)

    def _emit_initial_view_signals(self) -> None:
        """Emit initial zoom and viewport snapshots after the widget initializes."""
        self._initial_view_signals_scheduled = False
        self._emit_zoom_snapshot()
        self._emit_viewport_rect_if_changed(force=True)

    def featureFallbacks(self) -> FeatureFallbacks:
        """Expose the fallback tracker used to log optional feature availability."""
        return self._state.fallbacks

    def failedFeatures(self) -> Mapping[str, FeatureFailure]:
        """Return recorded feature installation failures keyed by feature name."""
        return self._state.failed_features

    def gatherDiagnostics(self) -> DiagnosticsSnapshot:
        """Collect a diagnostic snapshot for this QPane instance."""
        return self.diagnostics().gather()

    def createStatusOverlay(self, *, parent: QWidget | None = None):
        """Create a status overlay widget bound to this QPane."""
        return ui.create_status_overlay(self, parent=parent)

    def applyCacheSettings(self) -> None:
        """Propagate cache configuration to view-managed controllers."""
        self._state.apply_cache_settings()

    def _apply_diagnostics_overlay_preferences(self) -> None:
        """Synchronize overlay visibility and detail toggles with settings.

        Raises:
            ValueError: When configured diagnostics domains are not available.
        """
        controller = self.diagnosticsOverlayController()
        settings = self.settings
        enabled_domains = tuple(
            getattr(settings, "diagnostics_domains_enabled", ()) or ()
        )
        available_domains = set(controller.domains())
        unknown = tuple(
            domain for domain in enabled_domains if domain not in available_domains
        )
        if unknown:
            raise ValueError(
                f"Diagnostics domains not available for this qpane: {', '.join(unknown)}"
            )
        for domain in available_domains:
            controller.setDomainEnabled(domain, domain in enabled_domains)
        overlay_enabled = bool(getattr(settings, "diagnostics_overlay_enabled", False))
        controller.setOverlayEnabled(overlay_enabled)

    def _normalize_diagnostics_domain(self, domain: str | DiagnosticsDomain) -> str:
        """Return a canonical diagnostics domain or raise when unavailable."""
        controller = self.diagnosticsOverlayController()
        available = set(controller.domains())
        candidate = (
            domain.value if isinstance(domain, DiagnosticsDomain) else str(domain)
        )
        canonical = candidate.strip().lower()
        if canonical not in available:
            raise ValueError(
                f"Diagnostics domain '{candidate}' is not available for this qpane"
            )
        return canonical

    def attachAutosaveManager(self, manager: "AutosaveManager") -> None:
        """Install the autosave manager used by optional features.

        Replaces any existing manager; masking hooks detach it automatically when autosave is disabled.
        """
        self.hooks.attachAutosaveManager(manager)

    def detachAutosaveManager(self) -> None:
        """Remove the currently attached autosave manager, if any.

        Missing managers are ignored so callers can always invoke this during teardown.
        """
        self.hooks.detachAutosaveManager()

    def autosaveManager(self) -> "AutosaveManager | None":
        """Return the currently attached autosave manager, if any."""
        return self._autosave_manager

    def _set_autosave_manager(self, manager: "AutosaveManager | None") -> None:
        """Internal helper used by hooks to manage autosave state."""
        self._autosave_manager = manager

    def attachMaskService(self, service: "MaskService") -> None:
        """Attach the mask service facade and refresh autosave hooks.

        Side effects:
            Emits ``catalogChanged`` with ``maskServiceAttached``.
        """
        self._masks_controller.attachMaskService(service)
        service.bindCompositionEdits(self.compositionService().edit_controller)
        service.setStrokeConstraintProvider(
            self.editorInteraction().mask_stroke_constraint
        )
        factory = MaskLayerDescriptorFactory(
            assets=service.assets,
            renders=service.controller.renders,
            dynamic_revision=service.scene_provider_revision,
        )
        assembler = self._composition_layer_assembler
        if assembler is None:
            raise RuntimeError("composition layer assembler is unavailable")
        assembler.register_factory(factory)
        self._mask_descriptor_factory = factory
        capabilities = MaskSourceCapabilities(
            assets=service.assets,
            renders=service.controller.renders,
        )
        sources = self.layerSourceCapabilities()
        sources.metadata.register(MaskAssetReference, capabilities)
        sources.rasters.register(MaskAssetReference, capabilities)
        sources.raster_patches.register(MaskAssetReference, capabilities)
        sources.hit_tests.register(MaskAssetReference, capabilities)
        sources.coverage.register(MaskAssetReference, capabilities)
        sources.pixel_presentation.register(MaskAssetReference, capabilities)
        self._mask_source_capabilities = capabilities
        from .masks.raster_mutations import MaskRasterMutationOwner

        raster_owner = MaskRasterMutationOwner(
            assets=service.assets,
            edits=service.controller.edits,
            renders=service.controller.renders,
            executor=self.executor,
            mask_changed=service.controller.mask_updated.emit,
            undo_changed=service.controller.undo_stack_changed.emit,
            scene_changed=self._handle_raster_structure_changed,
            completed=self._handle_raster_bounds_completion,
        )
        if self._raster_mutations is not None:
            self._raster_mutations.register_owner(raster_owner)
        self._mask_raster_mutation_owner = raster_owner
        render_synchronizer = MaskPixelRenderSynchronizer(
            service.assets,
            service.controller.renders,
            service.updateMaskRegion,
        )
        pixel_owner = MaskLayerPixelMutationOwner(
            service.assets,
            changed=render_synchronizer.refresh,
            structure_changed=self._handle_raster_structure_changed,
        )
        if self._layer_pixel_owners is not None:
            self._layer_pixel_owners.register(pixel_owner)
        self._mask_pixel_edit_owner = pixel_owner
        mask_floating_owner = MaskFloatingLayerOwner(
            assets=service.assets,
            layers=self.compositionService().layers,
            current_composition_id=self.compositionService().current_composition_id,
            changed=lambda _mask_id: self._handle_raster_structure_changed(),
        )
        self._floating_layer_promotions.register(mask_floating_owner)
        self._mask_floating_layer_owner = mask_floating_owner
        resource_owner = MaskResourceLifecycleOwner(service.assets)
        self.compositionService().resource_lifetime.register_owner(resource_owner)
        self._mask_resource_lifecycle_owner = resource_owner
        paint_owner = MaskCoveragePaintTargetOwner(service)
        self.paintingCoordinator().registry.register(paint_owner)
        self.paintingCoordinator().registry.register_idle_feedback(
            paint_owner,
            paint_owner.idle_preview_color,
        )
        self._mask_paint_target_owner = paint_owner
        self._emit_catalog_mutation("maskServiceAttached", affected_ids=())

    def detachMaskService(self) -> None:
        """Detach the mask service and tear down autosave wiring.

        Side effects:
            Emits ``catalogChanged`` with ``maskServiceDetached``.
        """
        service = self.mask_service
        if service is not None:
            service.setStrokeConstraintProvider(None)
        raster_owner = self._mask_raster_mutation_owner
        if raster_owner is not None and self._raster_mutations is not None:
            self._raster_mutations.unregister_owner(raster_owner)
        self._mask_raster_mutation_owner = None
        pixel_owner = self._mask_pixel_edit_owner
        if pixel_owner is not None and self._layer_pixel_owners is not None:
            self._layer_pixel_owners.unregister(pixel_owner)
        self._mask_pixel_edit_owner = None
        floating_owner = self._mask_floating_layer_owner
        if floating_owner is not None:
            self._floating_layer_promotions.unregister(floating_owner)
        self._mask_floating_layer_owner = None
        resource_owner = self._mask_resource_lifecycle_owner
        if resource_owner is not None:
            self.compositionService().resource_lifetime.unregister_owner(resource_owner)
        self._mask_resource_lifecycle_owner = None
        paint_owner = self._mask_paint_target_owner
        if paint_owner is not None:
            self.paintingCoordinator().registry.unregister(paint_owner)
        self._mask_paint_target_owner = None
        factory = self._mask_descriptor_factory
        assembler = self._composition_layer_assembler
        if factory is not None and assembler is not None:
            assembler.unregister_factory(factory)
        self._mask_descriptor_factory = None
        capabilities = self._mask_source_capabilities
        if capabilities is not None:
            sources = self.layerSourceCapabilities()
            sources.metadata.unregister(MaskAssetReference, capabilities)
            sources.rasters.unregister(MaskAssetReference, capabilities)
            sources.raster_patches.unregister(MaskAssetReference, capabilities)
            sources.hit_tests.unregister(MaskAssetReference, capabilities)
            sources.coverage.unregister(MaskAssetReference, capabilities)
            sources.pixel_presentation.unregister(MaskAssetReference, capabilities)
            self._mask_source_capabilities = None
        self._masks_controller.detachMaskService()
        self._emit_catalog_mutation("maskServiceDetached", affected_ids=())

    def attachSamManager(self, sam_manager: "SamManager") -> None:
        """Attach a SamManager instance and wire its signals."""
        self._masks_controller.attachSamManager(sam_manager)

    def detachSamManager(self) -> None:
        """Detach the SAM manager and cancel outstanding predictor work."""
        self._masks_controller.detachSamManager()

    def samManager(self) -> "SamManager | None":
        """Return the active SAM manager when installed."""
        return self._sam_manager

    def _set_sam_manager(self, manager: "SamManager | None") -> None:
        """Internal helper for workflow/hooks to track SAM managers."""
        self._sam_manager = manager

    def addImage(self, image_id: uuid.UUID, image: QImage, path: Path | None):
        """Add or replace a single catalog entry without changing the selection."""
        catalog = self.catalog()
        catalog.addImage(image_id, image, path)

    def _display_current_catalog_image(self, *, fit_view: bool = True) -> None:
        """Render the catalog's current image if present; otherwise blank the qpane."""
        catalog = self.catalog()
        catalog.displayCurrentCatalogImage(fit_view=fit_view)

    @property
    def imageCount(self) -> int:
        """Return the total number of images managed by this QPane."""
        catalog = self.catalog()
        return catalog.imageCount()

    def linkedViewGroupID(self, image_id: uuid.UUID) -> uuid.UUID | None:
        """Return the linked-view group identifier that contains ``image_id`` when linked."""
        return self.catalog().linkedViewGroupID(image_id)

    def updateMaskFromFile(self, mask_id: "uuid.UUID", file_path: str) -> bool:
        """Replace a mask layer's pixels from ``file_path`` while preserving metadata.

        Args:
            mask_id: Identifier of the mask layer to update.
            file_path: Filesystem path to the replacement mask image.

        Returns:
            True when the layer was updated successfully.
        """
        return self._masks_controller.update_mask_from_file(mask_id, file_path)

    def invalidateActiveMaskCache(self):
        """Invalidate the colorized pixmap cache for the currently active mask.

        External tools that mutate mask images directly should call this to keep previews in sync.
        """
        return self._masks_controller.invalidate_active_mask_cache()

    def updateMaskRegion(
        self,
        dirty_image_rect: QRect,
        active_mask_layer: "MaskLayer",
        *,
        sub_mask_image: QImage | None = None,
        force_async_colorize: bool = False,
    ) -> bool:
        """Forward mask-region updates to refresh cached mask renders.

        Args:
            dirty_image_rect: Image-space rectangle that was modified.
            active_mask_layer: Layer owning the updated pixels.
            sub_mask_image: Optional pre-updated snippet to reuse instead of copying from the layer.
            force_async_colorize: Queue high-resolution colorization even when previews are decimated.

        Returns:
            True when the region update is dispatched successfully.
        """
        return self._masks_controller.update_mask_region(
            dirty_image_rect,
            active_mask_layer,
            sub_mask_image=sub_mask_image,
            force_async_colorize=force_async_colorize,
        )

    def generateAndApplyMask(self, bbox: np.ndarray, erase_mode: bool = False):
        """Generate a mask from ``bbox`` and apply it through the mask workflow."""
        return self._masks_controller.generate_and_apply_mask(
            bbox, erase_mode=erase_mode
        )

    def _sync_mask_activation_for_image(
        self, image_id: uuid.UUID | None
    ) -> MaskActivationSyncResult:
        """Synchronize mask activation for `image_id` and surface workflow status."""
        return self._masks_controller.sync_mask_activation_for_image(image_id)

    def isMaskActivationPending(self, image_id: uuid.UUID | None = None) -> bool:
        """Return True while deferred mask activation remains outstanding."""
        return self._masks_controller.is_activation_pending(image_id)

    def refreshMaskAutosavePolicy(self) -> None:
        """Re-evaluate mask autosave wiring after feature state changes."""
        self._masks_controller.refreshMaskAutosavePolicy()

    def resetActiveSamPredictor(self) -> None:
        """Clear any cached predictor so SAM requests start fresh."""
        self._masks_controller.resetActiveSamPredictor()

    def refreshCursor(self) -> None:
        """Refresh the QWidget cursor via the interaction delegate."""
        self.interaction.update_cursor()

    def updateBrushCursor(self, erase_indicator: bool = False) -> None:
        """Delegate brush cursor updates to the mask bridge via the interaction layer."""
        self.interaction.update_brush_cursor(erase_indicator=erase_indicator)

    def updateModifierKeyCursor(self) -> None:
        """Update modifier-sensitive cursors via the interaction delegate."""
        self.interaction.update_modifier_key_cursor()

    def setPanZoomLocked(self, locked: bool):
        """Delegate pan/zoom lock state to the viewport."""
        self.view().viewport.set_locked(bool(locked))

    def blank(self):
        """Blank the qpane without clearing caches."""
        self.interaction.blank()

    def getPan(self) -> QPointF:
        """Return the current pan offset."""
        return self.view().viewport.pan

    def setPan(self, pan: QPointF):
        """Delegate pan updates to the viewport."""
        self.view().viewport.setPan(pan)

    def getZoomMode(self) -> ViewportZoomMode:
        """Expose the active zoom mode reported by the viewport."""
        return self.view().viewport.get_zoom_mode()

    def markDirty(self, dirty_rect: QRect | QRectF | None = None):
        """Mark a region of the qpane as dirty by delegating to the renderer.

        Passing ``None`` marks the entire qpane dirty.
        """
        self.view().mark_dirty(dirty_rect)

    def _save_zoom_pan_for_current_image(self):
        """Persist the current viewport transform through the swap delegate."""
        self.view().swap_delegate.save_zoom_pan_for_current_image()

    def _restore_zoom_pan_for_new_image(self, image_id):
        """Restore the saved viewport transform for ``image_id`` when present."""
        self.view().swap_delegate.restore_zoom_pan_for_new_image(image_id)

    def _apply_zoom_interpolated(
        self,
        requested_zoom: float,
        anchor: QPoint | QPointF | None = None,
    ) -> None:
        """Apply a clamped zoom request using the viewport interpolation path."""
        new_zoom = self._normalize_zoom_request(requested_zoom)
        if new_zoom is None:
            return
        self.view().viewport.applyZoomInterpolated(new_zoom, anchor=anchor)

    def _apply_zoom_interpolated_with_mode(
        self,
        requested_zoom: float,
        anchor: QPoint | QPointF | None,
        target_mode: ViewportZoomMode,
    ) -> None:
        """Apply an interpolated zoom request while setting the target mode."""
        if target_mode == ViewportZoomMode.FIT:
            if not self._can_apply_zoom():
                return
            new_zoom = requested_zoom
            if new_zoom <= 0:
                return
        else:
            reinterpret_one = target_mode != ViewportZoomMode.FIT
            new_zoom = self._normalize_zoom_request(
                requested_zoom, reinterpret_one_as_native=reinterpret_one
            )
            if new_zoom is None:
                return
        target_pan = None
        fit_zoom = None
        if target_mode == ViewportZoomMode.FIT:
            target_pan = QPointF(0, 0)
            fit_zoom = new_zoom
        elif target_mode == ViewportZoomMode.ONE_TO_ONE:
            target_pan = None if anchor is not None else QPointF(0, 0)
        self.view().viewport.applyZoomInterpolatedWithMode(
            new_zoom,
            anchor=anchor,
            target_mode=target_mode,
            target_pan=target_pan,
            fit_zoom=fit_zoom,
        )

    def _apply_zoom_fit_interpolated(self) -> None:
        """Fit the viewport using an interpolated transition."""
        if not self._can_apply_zoom():
            return
        self.view().viewport.setZoomFitInterpolated()

    def _apply_zoom_one_to_one_interpolated(
        self, anchor: QPoint | QPointF | None = None
    ) -> None:
        """Snap to 1:1 zoom using an interpolated transition."""
        if not self._can_apply_zoom():
            return
        self.view().viewport.setZoom1To1Interpolated(anchor=anchor)

    def saveCurrentViewState(self) -> None:
        """Persist the current pan/zoom state for the active image."""
        self._save_zoom_pan_for_current_image()

    def restoreViewStateForImage(self, image_id: uuid.UUID) -> None:
        """Reapply a saved pan/zoom state for ``image_id`` when available."""
        self._restore_zoom_pan_for_new_image(image_id)

    def nativeZoom(self) -> float:
        """Return the zoom level where one image pixel equals one device pixel."""
        return self.view().viewport.nativeZoom()

    def isDragOutAllowed(self) -> bool:
        """Return True when drag-out is enabled and the image fits the viewport."""
        catalog = self.catalog()
        if catalog.placeholderActive():
            policy = catalog.placeholderPolicy()
            if policy is None or not getattr(policy, "drag_out_enabled", False):
                return False
            if not self.view().has_renderable_content():
                return False
        if not getattr(self.settings, "drag_out_enabled", True):
            return False
        content_snapshot = self.view().current_content_snapshot()
        if content_snapshot is None:
            return False
        return ui.is_drag_out_allowed(
            image_size=content_snapshot.base_image_size,
            zoom=self.view().viewport.zoom,
            zoom_mode=self.view().viewport.get_zoom_mode(),
            viewport_size=self.physicalViewportRect().size(),
        )

    def replaceRenderer(self, renderer: "Renderer") -> None:
        """Swap the active renderer while keeping presenter/view state aligned."""
        self.view().replace_renderer(renderer)

    def onViewChanged(self):
        """Slot connected to the viewport's viewChanged signal."""
        reused = self.view().handle_viewport_changed()
        if reused:
            cursor_refresh_needed = False
        else:
            self.markDirty()
            self.update()
            cursor_refresh_needed = True
        if cursor_refresh_needed:
            self.refreshCursor()
        self._emit_zoom_snapshot()
        self._emit_viewport_rect_if_changed()

    def _allocate_buffers(self):
        """Calculate buffer properties and tell the renderer to allocate them."""
        self.view().allocate_buffers()

    def physicalViewportRect(self) -> QRectF:
        """Return the current viewport rectangle in physical (device) pixels.

        Useful for tile visibility and rendering alignment.
        """
        return self.view().physical_viewport_rect()

    def panelToImagePoint(self, panel_pos: QPoint) -> QPoint | None:
        """Delegates coordinate conversion to the viewport."""
        return self.view().panel_to_image_point(panel_pos)

    def imageToPanelPoint(self, image_point: QPoint) -> QPointF | None:
        """Delegates coordinate conversion to the viewport."""
        return self.view().image_to_panel_point(image_point)

    def _screen_tracking_enabled(self) -> bool:
        """Return True when zoom normalization across screens is enabled."""
        return bool(getattr(self.settings, "normalize_zoom_on_screen_change", False))

    def _refresh_rate_tracking_enabled(self) -> bool:
        """Return True when smooth zoom should target the display refresh rate."""
        return bool(getattr(self.settings, "smooth_zoom_use_display_fps", True))

    def _screen_tracking_required(self) -> bool:
        """Return True when the window should listen for screen change events."""
        return self._screen_tracking_enabled() or self._refresh_rate_tracking_enabled()

    def _normalize_one_to_one_enabled(self) -> bool:
        """Return True when 1:1 zoom normalization is allowed."""
        return bool(getattr(self.settings, "normalize_zoom_for_one_to_one", False))

    def _viewport_in_one_to_one(self, viewport) -> bool:
        """Return True when ``viewport`` currently represents a 1:1 zoom."""
        zoom_mode = viewport.get_zoom_mode()
        if zoom_mode == ViewportZoomMode.ONE_TO_ONE:
            return True
        native_zoom = float(viewport.nativeZoom())
        if native_zoom <= 0:
            return False
        return isclose(viewport.zoom, native_zoom, rel_tol=1e-6, abs_tol=1e-6)

    def _refresh_screen_tracking(self) -> None:
        """Attach or detach screen-change listeners based on the current setting."""
        if not self._screen_tracking_required():
            self._disconnect_screen_signals()
            return
        self._connect_screen_signals()
        if self._tracked_screen is not None:
            self._set_tracked_screen(self._tracked_screen, force=True)

    def _screen_device_pixel_ratio(self, screen: QScreen | None) -> float:
        """Return the DPR for ``screen`` or this qpane when unavailable."""
        if screen is not None:
            ratio = float(screen.devicePixelRatio())
        else:
            ratio = float(self.devicePixelRatioF())
        return ratio if ratio > 0 else 1.0

    def _safe_disconnect(self, signal: object, handler: object) -> None:
        """Best-effort disconnect for Qt signals during teardown."""
        try:
            signal.disconnect(handler)
        except (TypeError, RuntimeError, SystemError):
            pass

    def _rebase_zoom_for_screen_change(self, old_dpr: float, new_dpr: float) -> None:
        """Scale zoom/pan so viewport coverage stays stable across DPR changes.

        Args:
            old_dpr: Device pixel ratio before the change.
            new_dpr: Device pixel ratio reported by the new screen.
        """
        if not self._screen_tracking_enabled():
            return
        if old_dpr <= 0 or new_dpr <= 0:
            return
        if isclose(old_dpr, new_dpr, rel_tol=1e-6, abs_tol=1e-6):
            return
        view = self.view()
        viewport = view.viewport
        if not self._normalize_one_to_one_enabled() and self._viewport_in_one_to_one(
            viewport
        ):
            self._last_screen_dpr = new_dpr
            return
        scale = new_dpr / old_dpr
        new_zoom = viewport.zoom * scale
        pan = viewport.pan
        scaled_pan = QPointF(pan.x() * scale, pan.y() * scale)
        viewport.setZoomAndPan(new_zoom, scaled_pan)
        view.presenter.ensure_view_alignment(force=True)
        self._last_screen_dpr = new_dpr

    def _connect_screen_signals(self) -> None:
        """Ensure the window and active screen notify us about DPR changes."""
        window = self._resolve_window_handle()
        if window is None:
            return
        if self._tracked_window is not window:
            self._disconnect_window_signals()
            window.screenChanged.connect(self._handle_screen_changed)
            window.destroyed.connect(self._handle_tracked_window_destroyed)
            self._tracked_window = window
        self._set_tracked_screen(window.screen())

    def _resolve_window_handle(self) -> QWindow | None:
        """Return the top-level window handle hosting this widget."""
        handle = self.windowHandle()
        if handle is not None:
            return handle
        window = self.window()
        if window is None:
            return None
        return window.windowHandle()

    def _disconnect_screen_signals(self) -> None:
        """Detach all screen tracking hooks."""
        self._disconnect_window_signals()
        self._set_tracked_screen(None)

    def _disconnect_window_signals(self) -> None:
        """Safely disconnect tracked window change hooks and clear the reference."""
        window = self._tracked_window
        if window is None:
            return
        self._safe_disconnect(window.screenChanged, self._handle_screen_changed)
        self._safe_disconnect(window.destroyed, self._handle_tracked_window_destroyed)
        self._tracked_window = None

    def _set_tracked_screen(
        self, screen: QScreen | None, *, force: bool = False
    ) -> None:
        """Swap the screen DPI listener to ``screen`` when provided."""
        if not force and self._tracked_screen is screen:
            return
        if self._tracked_screen is not None:
            if "dpi" in self._tracked_screen_connections:
                self._safe_disconnect(
                    self._tracked_screen.logicalDotsPerInchChanged,
                    self._handle_screen_dpi_changed,
                )
            if "refresh" in self._tracked_screen_connections:
                self._safe_disconnect(
                    self._tracked_screen.refreshRateChanged,
                    self._handle_screen_refresh_rate_changed,
                )
        self._tracked_screen = None
        self._tracked_screen_connections.clear()
        if screen is None:
            return
        if self._screen_tracking_enabled():
            screen.logicalDotsPerInchChanged.connect(self._handle_screen_dpi_changed)
            self._tracked_screen_connections.add("dpi")
        if self._refresh_rate_tracking_enabled():
            screen.refreshRateChanged.connect(self._handle_screen_refresh_rate_changed)
            self._tracked_screen_connections.add("refresh")
        self._tracked_screen = screen
        self._last_screen_dpr = self._screen_device_pixel_ratio(screen)
        self.view().viewport.update_detected_refresh_rate(screen.refreshRate())

    def _handle_tracked_window_destroyed(self, destroyed: object | None = None) -> None:
        """Clear tracked window references when the host window is destroyed."""
        if destroyed is not None and destroyed is not self._tracked_window:
            return
        self._tracked_window = None
        self._set_tracked_screen(None)

    def _handle_screen_changed(self, screen: QScreen | None) -> None:
        """Normalize zoom when the widget moves to a different screen."""
        if self._screen_tracking_enabled():
            old_dpr = self._last_screen_dpr
            new_dpr = self._screen_device_pixel_ratio(screen)
            self._rebase_zoom_for_screen_change(old_dpr, new_dpr)
        self._set_tracked_screen(screen)
        self._emit_viewport_rect_if_changed(force=True)

    def _handle_screen_dpi_changed(self, *_args: object) -> None:
        """Normalize zoom when the current screen updates its DPI."""
        screen = self._tracked_screen
        if not self._screen_tracking_enabled():
            return
        screen = self._tracked_screen
        if screen is None:
            return
        old_dpr = self._last_screen_dpr
        new_dpr = self._screen_device_pixel_ratio(screen)
        self._rebase_zoom_for_screen_change(old_dpr, new_dpr)
        self._last_screen_dpr = new_dpr
        self._emit_viewport_rect_if_changed(force=True)

    def _handle_screen_refresh_rate_changed(self, *_args: object) -> None:
        """Record the latest refresh rate when the screen reports a change."""
        screen = self._tracked_screen
        if screen is None:
            return
        self.view().viewport.update_detected_refresh_rate(screen.refreshRate())

    def _emit_zoom_snapshot(self) -> None:
        """Emit the current zoom factor without reaching into demo code."""
        try:
            zoom = float(self.view().viewport.zoom)
        except RuntimeError:  # pragma: no cover - deleted Qt object during shutdown
            return
        self.zoomChanged.emit(zoom)

    def _normalize_zoom_request(
        self, requested_zoom: float, *, reinterpret_one_as_native: bool = True
    ) -> float | None:
        """Validate and clamp a zoom request for viewport application."""
        viewport = self.view().viewport
        if not self._can_apply_zoom():
            return None
        # Reinterpret '1.0' as nativeZoom() for DPI-accuracy.
        if reinterpret_one_as_native and abs(requested_zoom - 1.0) < 1e-6:
            requested_zoom = self.nativeZoom()
        return viewport.clamp_zoom(requested_zoom)

    def _can_apply_zoom(self) -> bool:
        """Return True when zoom updates are allowed for the current view."""
        viewport = self.view().viewport
        if not self.view().has_renderable_content():
            logger.warning("applyZoom ignored because no image is loaded")
            return False
        if viewport.is_locked():
            logger.warning("applyZoom ignored because the viewport is locked")
            return False
        return True

    def _emit_viewport_rect_if_changed(self, *, force: bool = False) -> None:
        """Emit the physical viewport rectangle when it differs from the last snapshot."""
        try:
            rect = QRectF(self.physicalViewportRect())
        except RuntimeError:  # pragma: no cover - deleted Qt object during teardown
            return
        if not force and self._last_viewport_rect == rect:
            return
        self._last_viewport_rect = rect
        self.viewportRectChanged.emit(rect)

    def _handle_catalog_mutation(self, event: CatalogMutationEvent) -> None:
        """Relay catalog mutations through the QPane signal surface."""
        self.view().invalidate_content_cache()
        removed_ids = self._removed_catalog_ids(event)
        compositions_changed = self._sync_compositions_with_catalog()
        compare = self.compare_service
        if compare is not None:
            if removed_ids:
                compare.remove_catalog_images(removed_ids)
            compare.reconcile_catalog()
        affected_ids = set(event.affected_ids)
        comparison_source_id = (
            compare.state().source_id if compare is not None else None
        )
        if (
            self.catalog().currentImageID() in affected_ids
            or comparison_source_id in affected_ids
        ):
            self._sync_viewport_content_geometry()
            self.view().mark_dirty(None)
            self.update()
        self.catalogChanged.emit(event)
        self._maybe_emit_link_groups_changed()
        if compositions_changed:
            self._emit_composition_changed()

    @staticmethod
    def _removed_catalog_ids(event: CatalogMutationEvent) -> set[uuid.UUID]:
        """Return affected IDs only for catalog mutations that remove entries."""
        if event.reason in {"removeImageByID", "removeImagesByID", "clearImages"}:
            return set(event.affected_ids)
        return set()

    def _handle_comparison_changed(
        self,
        change: ComparisonChange | None = None,
    ) -> None:
        """Refresh rendering and signals after comparison state changes."""
        try:
            self.view().invalidate_content_cache()
            if change is None or change.kind in {
                ComparisonChangeKind.SOURCE,
                ComparisonChangeKind.ENABLED,
            }:
                self._sync_viewport_content_geometry()
            if change is not None and change.kind == ComparisonChangeKind.SPLIT:
                dirty_rect = self._comparison_split_dirty_rect(change)
            else:
                dirty_rect = None
            self.view().mark_dirty(dirty_rect)
        except RuntimeError:  # pragma: no cover - deleted Qt object during teardown
            return
        state = self._comparison_service().state()
        if not state.enabled:
            self.comparisonDividerInteraction().cancel_drag()
        self.comparisonChanged.emit(state)
        self.refreshCursor()
        self.update()

    def _comparison_split_dirty_rect(self, change: ComparisonChange) -> QRect | None:
        """Return the bounded dirty rect for a pure comparison split change."""
        previous = change.previous
        current = change.current
        if (
            not previous.enabled
            or not current.enabled
            or previous.source_id != current.source_id
            or previous.orientation != current.orientation
        ):
            return None
        plan = self.view().calculateRenderPlan(
            is_blank=getattr(self, "_is_blank", False)
        )
        if plan is None:
            return None
        compare_item = next(
            (
                item
                for item in plan.render_items
                if isinstance(item, RasterLayerRenderItem)
                and item.descriptor.hit_test.role == "comparison-image"
            ),
            None,
        )
        if compare_item is None:
            return None
        previous_line = self._comparison_split_line(
            compare_item,
            plan.scene_bounds,
            previous.split_position,
            current.orientation,
        )
        current_line = self._comparison_split_line(
            compare_item,
            plan.scene_bounds,
            current.split_position,
            current.orientation,
        )
        if previous_line is None or current_line is None:
            return None
        bounds = QRectF(previous_line.p1(), previous_line.p2()).normalized()
        bounds = bounds.united(
            QRectF(current_line.p1(), current_line.p2()).normalized()
        )
        hit_width = self.comparisonDividerInteraction().state().hit_width
        return bounds.adjusted(
            -hit_width,
            -hit_width,
            hit_width,
            hit_width,
        ).toAlignedRect()

    @staticmethod
    def _comparison_split_line(
        item: RasterLayerRenderItem,
        scene_bounds,
        split_position: float,
        orientation: ComparisonOrientation,
    ) -> QLineF | None:
        """Project a normalized comparison split into widget coordinates."""
        placement = item.placement
        source_width = item.source_image.width()
        source_height = item.source_image.height()
        if (
            source_width <= 0
            or source_height <= 0
            or placement.width <= 0.0
            or placement.height <= 0.0
        ):
            return None
        if orientation == ComparisonOrientation.HORIZONTAL:
            scene_y = scene_bounds.y + scene_bounds.height * split_position
            source_y = (scene_y - placement.y) * source_height / placement.height
            source_line = QLineF(
                QPointF(0.0, source_y),
                QPointF(float(source_width), source_y),
            )
        else:
            scene_x = scene_bounds.x + scene_bounds.width * split_position
            source_x = (scene_x - placement.x) * source_width / placement.width
            source_line = QLineF(
                QPointF(source_x, 0.0),
                QPointF(source_x, float(source_height)),
            )
        return QLineF(
            item.transform.map(source_line.p1()),
            item.transform.map(source_line.p2()),
        )

    def _sync_compositions_with_catalog(self) -> bool:
        """Ensure composition records match the current catalog inventory."""
        service = self.compositionService()
        previous_id = service.current_composition_id()
        changed = service.sync_catalog(
            self.catalog().imageIDs(),
            path_lookup=self.imagePath,
            size_lookup=lambda image_id: self._image_catalog.getImage(image_id).size(),
        )
        active = service.active_record()
        current_id = self.catalog().currentImageID()
        if active is None and current_id is not None:
            try:
                active = service.open_default_for_image(current_id)
            except KeyError:
                return changed
            self._open_composition_record(active)
            return True
        current_composition_id = service.current_composition_id()
        if current_composition_id != previous_id:
            if active is not None:
                self._open_composition_record(active)
            else:
                self._emit_composition_selection_changed(current_composition_id)
                self._emit_scene_changed()
        return changed

    def _activate_default_composition_for_image(self, image_id: uuid.UUID) -> None:
        """Open the generated default composition for a catalog image."""
        service = self.compositionService()
        previous_id = service.current_composition_id()
        record = service.open_default_for_image(image_id)
        if previous_id != record.composition_id:
            self._emit_composition_selection_changed(record.composition_id)
            self._handle_comparison_changed()
            self._emit_scene_changed()

    def _open_composition_record(
        self,
        record: CompositionRecord,
        *,
        fit_view: bool = True,
    ) -> None:
        """Open one composition document and synchronize legacy navigation state."""
        self._cancel_floating_pixels_for_context_change()
        image_id = record.navigation_image_id
        if image_id is not None and self.catalog().currentImageID() != image_id:
            self.interaction.suspend_overlays_for_navigation()
            self.catalog().setCurrentImageID(image_id)
        self._is_blank = False
        self.view().invalidate_content_cache()
        self._emit_composition_selection_changed(record.composition_id)
        self._handle_comparison_changed()
        if record.policy.removable:
            self._sync_view_to_scene_bounds(fit_view=fit_view)
        self._emit_scene_changed()

    def _refresh_active_scene_content(self, *, fit_view: bool) -> None:
        """Refresh rendering after the active scene payload changes in place."""
        self.view().invalidate_content_cache()
        self._sync_view_to_scene_bounds(fit_view=fit_view)
        self._emit_scene_changed()

    def _default_mask_paint_target_available(self) -> bool:
        """Return whether legacy catalog painting can provision its default mask."""
        return self._masks is not None and self.catalog().currentImageID() is not None

    def _emit_composition_changed(self) -> None:
        """Emit the latest composition snapshot."""
        self.compositionChanged.emit(self.getCompositionSnapshot())

    def _emit_composition_selection_changed(
        self, composition_id: uuid.UUID | None
    ) -> None:
        """Emit composition selection changes for host browsers."""
        self.compositionSelectionChanged.emit(composition_id)

    def _emit_scene_changed(self) -> None:
        """Emit the current normalized scene snapshot."""
        self._scene_selection.validate(self.sceneMutationCoordinator().active_scene())
        if self._vector_editor is not None:
            self._vector_editor.synchronize_selection()
        scene_id = self._active_resolved_scene_id()
        state = (
            None
            if scene_id is None
            else self.editorInteraction().pixel_selection_state(scene_id)
        )
        self._editor_overlays.set_selection(state)
        self.sceneChanged.emit(self._current_scene_snapshot())
        if self._scene_mutations is not None:
            self.sceneEditHistoryChanged.emit(
                self.sceneEditUndoAvailable(),
                self.sceneEditRedoAvailable(),
            )

    def _handle_raster_structure_changed(self) -> None:
        """Refresh scene geometry and public state after a raster source change."""
        self.view().invalidate_content_cache()
        self._handle_internal_scene_content_changed()
        self._emit_scene_changed()

    def _handle_placed_asset_changed(self, _scope_id: uuid.UUID) -> None:
        """Refresh source products and public state after a placed-asset change."""
        self.view().invalidate_content_cache()
        self._handle_internal_scene_content_changed()
        self._emit_scene_changed()

    def _handle_placed_asset_completion(
        self, completion: PlacedAssetCompletion
    ) -> None:
        """Publish one typed internal placed completion through the facade signal."""
        public_scene = self.currentScene()
        public_scene_id = (
            completion.scope_id
            if public_scene is None
            or completion.scope_id != public_scene.composition_id
            else public_scene.scene_id
        )
        self.placedAssetRequestCompleted.emit(
            completion.request_id,
            public_scene_id,
            completion.layer_id,
            completion.succeeded,
            completion.message,
        )

    def _handle_vector_conversion_completion(
        self,
        completion: VectorConversionCompletion,
    ) -> None:
        """Publish one terminal vector conversion through the public signal."""
        self.vectorRequestCompleted.emit(
            completion.request_id,
            completion.scene_id,
            completion.layer_id,
            VectorConversionKind(completion.kind).value,
            completion.succeeded,
            completion.message,
        )

    def _handle_raster_bounds_completion(
        self,
        completion: RasterBoundsCompletion,
    ) -> None:
        """Map one internal completion to the public active-scene identifier."""
        public_scene_id = self._raster_request_public_scenes.pop(
            completion.request_id,
            completion.scene_id,
        )
        self.rasterBoundsRequestCompleted.emit(
            completion.request_id,
            public_scene_id,
            completion.layer_id,
            completion.succeeded,
            completion.message,
        )

    def _current_scene_snapshot(self) -> QPaneScene | None:
        """Return a public scene snapshot for the active composition."""
        service = self.compositionService()
        record = service.active_record()
        if record is None:
            return None
        resolved = self.view().current_scene_descriptor()
        if resolved is None:
            return None
        return QPaneScene(
            composition_id=record.composition_id,
            scene_id=record.composition_id,
            title=record.title,
            bounds=QRectF(
                resolved.bounds.x,
                resolved.bounds.y,
                resolved.bounds.width,
                resolved.bounds.height,
            ),
            layers=tuple(
                self._public_resolved_layer(
                    layer,
                    service.layers.layer(record.composition_id, layer.layer_id),
                )
                for layer in resolved.layers
            ),
        )

    @staticmethod
    def _public_resolved_layer(
        layer: LayerDescriptor,
        instance: CompositionLayerInstance | None = None,
    ) -> QPaneSceneLayer:
        """Convert one resolved source descriptor into a public layer snapshot."""
        source = layer.source
        if isinstance(source, CatalogImageReference):
            image_id = source.image_id
        else:
            image_id = None
        durable_transform = layer.transform if instance is None else instance.transform
        placement = (
            layer.placement
            if instance is None or layer.raster_bounds is None
            else durable_transform.map_bounds(layer.raster_bounds)
        )
        return QPaneSceneLayer(
            layer_id=layer.layer_id,
            image_id=image_id,
            placement=QRectF(
                placement.x,
                placement.y,
                placement.width,
                placement.height,
            ),
            visible=layer.visible,
            opacity=layer.opacity,
            clip=(
                None
                if instance is None or instance.clip is None
                else QPaneSceneClip(
                    coordinate_space=instance.clip.coordinate_space.value,
                    rect=QRectF(
                        instance.clip.x,
                        instance.clip.y,
                        instance.clip.width,
                        instance.clip.height,
                    ),
                )
            ),
            hit_test=layer.hit_test.enabled,
            role=layer.hit_test.role,
            metadata={} if instance is None else instance.metadata,
            interaction=public_layer_policy(layer.interaction),
            source_kind=source.kind,
            source_id=source.resource_id,
            label=layer.label,
            transform=(
                QTransform()
                if durable_transform is None
                else durable_transform.to_qtransform()
            ),
        )

    def _handle_internal_scene_content_changed(
        self, dirty_rect: QRect | QRectF | None = None
    ) -> None:
        """Refresh rendering after private scene content changes."""
        if self._scene_movement is not None and self._scene_mutations is not None:
            self._scene_movement.synchronize_scene(self._scene_mutations.active_scene())
        try:
            self.view().mark_dirty(dirty_rect)
        except RuntimeError:  # pragma: no cover - deleted Qt object during teardown
            return
        self.update()

    def _handle_pixel_selection_changed(self, state: PixelSelectionState) -> None:
        """Refresh active selection presentation and edit availability."""
        if state.scene_id != self._active_resolved_scene_id():
            return
        self._editor_overlays.set_selection(state)
        self.pixelSelectionChanged.emit(self._public_pixel_selection_state(state))

    def _handle_composition_edit_history_changed(
        self,
        scope_id: uuid.UUID,
    ) -> None:
        """Publish undo and redo availability for the active edit scope."""
        if scope_id != self._active_resolved_scene_id():
            return
        self.sceneEditHistoryChanged.emit(
            self.sceneEditUndoAvailable(),
            self.sceneEditRedoAvailable(),
        )

    def _handle_composition_layers_changed(
        self,
        _composition_id: uuid.UUID,
    ) -> None:
        """Publish the detached browser snapshot after a stored stack mutation."""
        self._emit_composition_changed()

    def _handle_selected_layer_changed(
        self,
        selection: SceneLayerSelection | None,
    ) -> None:
        """Publish selected-layer identity and refresh direct-edit feedback."""
        painting = self.paintingCoordinator()
        active_target = painting.identity
        if selection is None:
            if (
                active_target is not None
                and active_target.kind is PaintTargetKind.LAYER
            ):
                painting.clear()
        elif not (
            active_target is not None
            and active_target.kind is PaintTargetKind.LAYER
            and active_target.scene_id == selection.scene_id
            and active_target.layer_id == selection.layer_id
        ):
            selected = painting.select_layer(selection.scene_id, selection.layer_id)
            if (
                not selected
                and active_target is not None
                and active_target.kind is PaintTargetKind.LAYER
            ):
                painting.clear()
        self.selectedLayerChanged.emit(self.selectedLayer())
        self.update()

    def _handle_paint_target_changed(
        self,
        _target: PaintTargetIdentity | None,
    ) -> None:
        """Refresh brush feedback after the source-local paint target changes."""
        self.refreshCursor()
        self.paintTargetChanged.emit(self.paintTargetState())
        self.update()

    def _handle_vector_selection_changed(self) -> None:
        """Publish vector-object selection without disturbing raster selection."""
        state = (
            None
            if self._vector_editor is None
            else self._vector_editor.selection_state()
        )
        self.vectorSelectionChanged.emit(state)
        self.update()

    def _handle_vector_node_selection_changed(self) -> None:
        """Publish vector control-point selection without changing object selection."""
        state = (
            None
            if self._vector_editor is None
            else self._vector_editor.node_selection_state()
        )
        self.vectorNodeSelectionChanged.emit(state)
        self.update()

    def _handle_vector_text_edit_changed(self) -> None:
        """Publish the detached active semantic text session."""
        state = (
            None
            if self._vector_editor is None
            else self._vector_editor.text_edit_state()
        )
        self.vectorTextEditChanged.emit(state)
        self.update()

    def _handle_vector_options_changed(self) -> None:
        """Publish the contextual vector creation options."""
        interaction = self._vector_interaction
        if interaction is None:
            return
        self.vectorToolOptionsChanged.emit(interaction.shape, interaction.style)
        self.refreshCursor()

    def _publish_vector_content_change(self) -> None:
        """Refresh public scene presentation after vector document mutation."""
        self._handle_internal_scene_content_changed()
        self._emit_scene_changed()

    def _synchronize_active_mask_layer_selection(self) -> None:
        """Make the actively edited mask the generic selected scene layer."""
        active_mask_id = self.activeMaskID()
        scene = self.view().current_scene_descriptor()
        current = self._scene_selection.current
        if scene is None:
            return
        active_layer = next(
            (
                layer
                for layer in scene.layers
                if isinstance(layer.source, MaskAssetReference)
                and layer.source.mask_id == active_mask_id
            ),
            None,
        )
        if active_layer is not None:
            self.paintingCoordinator().select_layer(
                scene.scene_id,
                active_layer.layer_id,
                require_policy=False,
            )
            if active_layer.interaction.selectable:
                self._scene_selection.select(scene.scene_id, active_layer.layer_id)
            return
        if active_mask_id is not None or current is None:
            return
        selected_layer = next(
            (layer for layer in scene.layers if layer.layer_id == current.layer_id),
            None,
        )
        if selected_layer is not None and isinstance(
            selected_layer.source,
            MaskAssetReference,
        ):
            self._scene_selection.clear()

    def _public_pixel_selection_state(
        self,
        state: PixelSelectionState,
    ) -> QPanePixelSelectionState:
        """Convert internal selection coverage to a detached public snapshot."""
        coverage = state.coverage
        current_scene = self.currentScene()
        public_scene_id = (
            state.scene_id if current_scene is None else current_scene.scene_id
        )
        return QPanePixelSelectionState(
            scene_id=public_scene_id,
            revision=state.revision,
            bounds=None if coverage is None else coverage.bounds.to_qrect(),
            coverage=(
                None
                if coverage is None
                else numpy_to_qimage_grayscale8(coverage.pixels)
            ),
        )

    def _sync_view_to_scene_bounds(self, *, fit_view: bool) -> None:
        """Refresh viewport geometry after private scene layout changes."""
        view = self.view()
        snapshot = view.current_content_snapshot()
        if snapshot is None:
            return
        view.viewport.setContentSize(snapshot.base_image_size)
        if fit_view:
            view.viewport.setZoomFit()
        self.setMinimumSize(self.minimumSizeHint())
        view.allocate_buffers()
        view.mark_dirty()
        view.ensure_view_alignment(force=True)
        self.update()

    def _sync_viewport_content_geometry(self) -> None:
        """Refresh viewport content size after renderable scene geometry changes."""
        view = self.view()
        snapshot = view.current_content_snapshot()
        if snapshot is None:
            return
        viewport = view.viewport
        viewport.setContentSize(snapshot.base_image_size)
        if viewport.get_zoom_mode() == ViewportZoomMode.FIT:
            viewport.setZoomFit()
        else:
            viewport.setPan(viewport.pan)
        self.setMinimumSize(self.minimumSizeHint())

    def _emit_catalog_mutation(
        self, reason: str, *, affected_ids: Iterable[uuid.UUID] | None = None
    ) -> None:
        """Emit a catalog mutation event through the QPane surface."""
        current_id: uuid.UUID | None
        try:
            current_id = self.catalog().currentImageID()
        except RuntimeError:
            current_id = None
        event = CatalogMutationEvent(
            reason=reason,
            affected_ids=tuple(affected_ids or ()),
            current_id=current_id,
        )
        self._handle_catalog_mutation(event)

    def _normalized_link_groups(
        self,
    ) -> tuple[tuple[uuid.UUID, tuple[uuid.UUID, ...]], ...]:
        """Return normalized link-group definitions for change detection."""
        normalized: list[tuple[uuid.UUID, tuple[uuid.UUID, ...]]] = []
        for group in self.linkedGroups():
            normalized.append((group.group_id, tuple(sorted(group.members))))
        normalized.sort(key=lambda item: item[0].hex)
        return tuple(normalized)

    def _maybe_emit_link_groups_changed(self) -> None:
        """Emit link-group changes when the current definition differs."""
        groups = self._normalized_link_groups()
        if groups == self._last_link_groups:
            return
        self._last_link_groups = groups
        self.linkGroupsChanged.emit()

    def _emit_catalog_selection_changed(self, image_id: uuid.UUID | None) -> None:
        """Emit catalog selection changes for the active image."""
        self.catalogSelectionChanged.emit(image_id)

    def _handle_current_image_changed_signal(self, image_id: uuid.UUID) -> None:
        """Emit selection updates when the active image changes."""
        self._emit_catalog_selection_changed(image_id)

    def _handle_diagnostics_overlay_toggled(self, enabled: bool) -> None:
        """Emit overlay toggle changes while avoiding duplicate signals."""
        self.diagnosticsOverlayToggled.emit(enabled)

    def _handle_diagnostics_detail_toggled(self, domain: str, enabled: bool) -> None:
        """Emit diagnostics domain detail toggle changes."""
        self.diagnosticsDomainToggled.emit(domain, enabled)

    def resizeEvent(self, event):
        """Handle qpane resizing by realigning the view and refreshing the cursor."""
        self.view().ensure_view_alignment(force=True)
        self.update()
        self.refreshCursor()
        self._emit_viewport_rect_if_changed(force=True)

    def minimumSizeHint(self) -> QSize:
        """Prevent resizing below the configured minimum view size."""
        return self.view().minimum_size_hint()

    def paintEvent(self, event):
        """Delegate painting to the presenter and overlays after ensuring alignment."""
        self.view().ensure_view_alignment()
        presenter = self.view().presenter
        presenter.paint(
            is_blank=self._is_blank,
            content_overlays=self.interaction.content_overlays,
            scene_overlays=self.interaction.scene_overlays,
            overlays_suspended=self.interaction.overlays_suspended,
            draw_tool_overlay=self._draw_interaction_overlays,
        )
        self.interaction.maybe_resume_overlays()

    def _draw_interaction_overlays(self, painter: QPainter) -> None:
        """Draw the active tool overlay."""
        movement = self._editor_movement_interaction
        self._editor_overlays.draw(
            painter,
            self.view().scene_to_panel_transform(),
            self.view().current_scene_descriptor(),
            None if movement is None else movement.hovered,
        )
        self._tools_manager.draw_overlay(painter)

    def wheelEvent(self, event: QWheelEvent):
        """Route wheel events to the interaction layer for gesture handling."""
        self.interaction.handle_wheel_event(event)

    def mousePressEvent(self, event):
        """Forward mouse press events to the interaction delegate."""
        self.interaction.handle_mouse_press(event)

    def mouseMoveEvent(self, event):
        """Forward mouse move events to the interaction delegate."""
        self.interaction.handle_mouse_move(event)

    def mouseReleaseEvent(self, event):
        """Forward mouse release events to the interaction delegate."""
        self.interaction.handle_mouse_release(event)

    def mouseDoubleClickEvent(self, event):
        """Forward mouse double-click events to the interaction delegate."""
        self.interaction.handle_mouse_double_click(event)

    def enterEvent(self, event):
        """Forward enter events before invoking QWidget handling."""
        self.interaction.handle_enter_event(event)
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Forward leave events before invoking QWidget handling."""
        self.interaction.handle_leave_event(event)
        super().leaveEvent(event)

    def event(self, event):
        """Route direct input and refresh screen tracking on window changes."""
        if not hasattr(self, "_state"):
            return super().event(event)
        event_type = event.type()
        if event_type in (
            QEvent.Type.TouchBegin,
            QEvent.Type.TouchUpdate,
            QEvent.Type.TouchEnd,
            QEvent.Type.TouchCancel,
        ):
            if self.interaction.handle_touch_event(cast(QTouchEvent, event)):
                event.accept()
                return True
            event.ignore()
        if event_type in (
            QEvent.Type.WinIdChange,
            QEvent.Type.ParentChange,
            QEvent.Type.ShowToParent,
        ):
            self._refresh_screen_tracking()
        return super().event(event)

    def tabletEvent(self, event: QTabletEvent) -> None:
        """Route active-pen input through the interaction controller."""
        if self.interaction.handle_tablet_event(event):
            event.accept()
            return
        event.ignore()

    def showEvent(self, event):
        """Handle initial show-time setup that depends on widget geometry."""
        super().showEvent(event)
        self.interaction.handle_show_event()
        self._refresh_screen_tracking()
        self._emit_viewport_rect_if_changed(force=True)

    def keyPressEvent(self, event):
        """Let the interaction layer handle key presses first, falling back to QWidget."""
        if self.interaction.handle_key_press(event):
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        """Let the interaction layer handle key releases first, falling back to QWidget."""
        if self.interaction.handle_key_release(event):
            return
        super().keyReleaseEvent(event)
