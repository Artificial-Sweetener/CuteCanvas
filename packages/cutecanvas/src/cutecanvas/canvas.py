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

"""CuteCanvas widget facade coordinating document rendering and editor APIs."""

import logging
import uuid
from collections.abc import Iterable
from typing import cast

from PySide6.QtCore import (
    QEvent,
    QPoint,
    QRectF,
    QSize,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QHideEvent,
    QPainter,
    QScreen,
    QShowEvent,
    QTabletEvent,
    QTouchEvent,
    QWheelEvent,
    QWindow,
)
from PySide6.QtWidgets import QWidget
from qpane.sdk.execution import DefaultExecutionPolicy, ExecutionRuntime
from qpane.sdk.rendering import (
    View,
)
from qpane.sdk.scene import LayerSourceCapabilities, SceneProviderRegistry
from qpane.sdk.ui import (
    DiagnosticsOverlayController,
    OutboundDragController,
    OutboundMimeProvider,
)

from .composition import (
    CompositionService,
)
from .composition.scene_adapter import CompositionSceneAdapter
from .core import (
    CuteCanvasHooks,
    CuteCanvasState,
)
from .core.config import Config
from .coverage import CoverageShapeConfiguration
from .editor import (
    EditorInteractionCoordinator,
    EditorMovementInteraction,
    EditorOperationResolver,
    EditorPolicyController,
    FloatingLayerPromotionRegistry,
    InteractivePaintDestinationCoordinator,
    LayerSelectionProjectionCache,
    SelectedPixelMovementController,
)
from .editor.transform_interaction import EditorTransformInteraction
from .fill import PaintBucketCoordinator, SelectionFillCoordinator
from .masks.coordinates import ActiveMaskLayerCoordinates
from .masks.descriptor_factory import MaskLayerDescriptorFactory
from .masks.floating_layers import MaskFloatingLayerOwner
from .masks.paint_target import MaskCoveragePaintTargetOwner
from .masks.pixel_edits import (
    MaskLayerPixelMutationOwner,
)
from .masks.source_resolver import MaskSourceCapabilities
from .masks.workflow import Masks
from .painting import (
    PaintingCoordinator,
)
from .painting.clone_operation import CloneStampOperation
from .persistence import CompositionPersistenceService
from .placed.rasterization import PlacedAssetRasterizationService
from .placed.store import PlacedAssetStore
from .placed.workflow import PlacedAssetWorkflow
from .raster.assets import EditableRasterAssetStore
from .raster.floating_layers import EditableRasterFloatingLayerOwner
from .raster.layers import (
    EditableRasterLayerController,
)
from .resources.active_raster import ActiveRasterResolver
from .resources.composition_rasterization import (
    CompositionResourceRasterizationService,
)
from .resources.image_documents import ImageDocumentWorkflow
from .resources.layer_operations import LayerResourceOperations
from .resources.rasterization import LayerResourceRasterizationRouter
from .runtime.document_runtime import CanvasDocumentRuntime
from .runtime.execution_binding import CanvasExecutionBinding
from .scene.layer_assembly import CompositionLayerSceneAssembler
from .scene.layer_geometry import LayerGeometryResolver
from .scene.layer_selection import SceneLayerSelectionController
from .scene.movement_interaction import SceneLayerMovementInteraction
from .scene.mutations import SceneMutationCoordinator
from .scene.pixel_edits import LayerPixelMutationCoordinator
from .scene.pixel_owners import LayerPixelOwnerRegistry
from .scene.raster_mutations import (
    RasterLayerMutationCoordinator,
)
from .scene.source_capabilities import EditorSourceCapabilities
from .scene.transform_preview import SceneLayerTransformPreview
from .scene.transform_session import SceneLayerTransformController
from .selection import PixelSelectionService
from .snapping import SnapConfiguration
from .tools import Tools
from .tools.delegate import ToolInteractionDelegate
from .types import (
    FloatingPixelSnapshot,
)
from .ui.editor_overlays import EditorOverlayPresenter
from .vector.facade import VectorHostFacade
from .vector.interaction import VectorInteractionController
from .vector.node_edit import VectorNodeEditController
from .vector.node_tool import VECTOR_NODE_MODE
from .vector.text_edit import VectorTextEditController
from .vector.text_tool import VECTOR_TEXT_MODE
from .vector.tools import VECTOR_PATH_MODE, VECTOR_SHAPE_MODE

logger = logging.getLogger(__name__)

__all__ = ["CuteCanvas"]


from .document import CanvasDocument, CanvasViewSession
from .document.inspection import SessionInspectionBinding
from .facade.composition_api import CompositionApiMixin
from .facade.configuration_api import ConfigurationApiMixin
from .facade.context_api import ContentContextApiMixin
from .facade.coverage_api import CoverageApiMixin
from .facade.diagnostics_api import DiagnosticsApiMixin
from .facade.drag_api import CanvasDragSubjectResolver, OutboundDragApiMixin
from .facade.editor import EditorFacade
from .facade.editor_policy_api import EditorPolicyApiMixin
from .facade.effect_api import EffectApiMixin
from .facade.interaction_api import InteractionApiMixin
from .facade.layer_api import LayerApiMixin
from .facade.mask_api import MaskApiMixin
from .facade.placed_api import PlacedAssetApiMixin
from .facade.projection_api import ProjectionApiMixin
from .facade.raster_api import RasterApiMixin
from .facade.resource_api import ResourceApiMixin
from .facade.snapping_api import SnappingApiMixin
from .facade.vector_api import VectorApiMixin
from .facade.view_api import ViewApiMixin
from .runtime.accessors import CanvasAccessorsMixin
from .runtime.document_events import DocumentEventsMixin
from .runtime.lifecycle import CanvasLifecycleMixin
from .runtime.view_state import CanvasViewStateMixin


class CuteCanvas(
    QWidget,
    ViewApiMixin,
    ConfigurationApiMixin,
    DiagnosticsApiMixin,
    OutboundDragApiMixin,
    ContentContextApiMixin,
    EditorPolicyApiMixin,
    CompositionApiMixin,
    MaskApiMixin,
    LayerApiMixin,
    ResourceApiMixin,
    PlacedAssetApiMixin,
    ProjectionApiMixin,
    VectorApiMixin,
    RasterApiMixin,
    CoverageApiMixin,
    EffectApiMixin,
    SnappingApiMixin,
    InteractionApiMixin,
    CanvasAccessorsMixin,
    CanvasLifecycleMixin,
    CanvasViewStateMixin,
    DocumentEventsMixin,
):
    """QWidget facade that routes document rendering and editor orchestration."""

    # ========================================================================
    # Public API
    # ========================================================================
    CONTROL_MODE_PANZOOM = Tools.CONTROL_MODE_PANZOOM
    CONTROL_MODE_CURSOR = Tools.CONTROL_MODE_CURSOR
    CONTROL_MODE_MOVE = Tools.CONTROL_MODE_MOVE
    CONTROL_MODE_TRANSFORM = Tools.CONTROL_MODE_TRANSFORM
    CONTROL_MODE_DRAW_BRUSH = Tools.CONTROL_MODE_DRAW_BRUSH
    CONTROL_MODE_CLONE_STAMP = Tools.CONTROL_MODE_CLONE_STAMP
    CONTROL_MODE_PAINT_BUCKET = Tools.CONTROL_MODE_PAINT_BUCKET
    CONTROL_MODE_SMART_SELECT = Tools.CONTROL_MODE_SMART_SELECT
    CONTROL_MODE_SELECT_RECTANGLE = Tools.CONTROL_MODE_SELECT_RECTANGLE
    CONTROL_MODE_SELECT_ELLIPSE = Tools.CONTROL_MODE_SELECT_ELLIPSE
    CONTROL_MODE_SELECT_LASSO = Tools.CONTROL_MODE_SELECT_LASSO
    CONTROL_MODE_MASK_RECTANGLE = Tools.CONTROL_MODE_MASK_RECTANGLE
    CONTROL_MODE_MASK_ELLIPSE = Tools.CONTROL_MODE_MASK_ELLIPSE
    CONTROL_MODE_MASK_LASSO = Tools.CONTROL_MODE_MASK_LASSO
    CONTROL_MODE_VECTOR_SHAPE = VECTOR_SHAPE_MODE
    CONTROL_MODE_VECTOR_PATH = VECTOR_PATH_MODE
    CONTROL_MODE_VECTOR_NODE = VECTOR_NODE_MODE
    CONTROL_MODE_VECTOR_TEXT = VECTOR_TEXT_MODE
    zoomChanged: Signal = Signal(float)
    """Emit the viewport zoom factor when view state changes."""
    viewportRectChanged: Signal = Signal(QRectF)
    """Emit the physical viewport rectangle whenever its size changes."""
    maskSaved: Signal = Signal(str, str)
    """Emit ``mask_id`` and file path after a mask autosave completes."""
    maskUndoStackChanged: Signal = Signal(uuid.UUID)
    """Emit the mask UUID when its undo stack mutates."""
    diagnosticsOverlayToggled: Signal = Signal(bool)
    """Emit overlay visibility state when the diagnostics HUD toggles."""
    diagnosticsDomainToggled: Signal = Signal(str, bool)
    """Emit diagnostics domain ID and enabled state after detail toggles."""
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
    cloneStampChanged: Signal = Signal(object)
    """Emit the immutable Clone Stamp state after its configuration changes."""
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
    layerRasterizationCompleted: Signal = Signal(
        uuid.UUID,
        object,
        object,
        bool,
        str,
    )
    """Emit request, scene, layer, success, and message after rasterization."""
    projectionCompleted: Signal = Signal(object)
    """Emit one terminal :class:`CanvasProjectionResult`."""
    outboundDragFailed: Signal = Signal(object, str)
    """Emit the gesture subject and provider message after MIME materialization fails."""
    contentContextRequested: Signal = Signal(object, QPoint)
    """Emit the stable content subject and global position for a context gesture."""
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
        document: CanvasDocument | None = None,
        session: CanvasViewSession | None = None,
        document_runtime: CanvasDocumentRuntime | None = None,
        execution_runtime: ExecutionRuntime | None = None,
        execution_policy: DefaultExecutionPolicy | None = None,
        config_strict: bool = False,
        **kwargs,
    ):
        """Build the CuteCanvas widget and wire core collaborators.

        Args:
            config: Initial configuration snapshot to apply.
            features: Optional feature names to install (mask, sam, etc.).
            document: Headless content aggregate to mount.
            session: Detachable activation and presentation state to mount.
            document_runtime: Shared ephemeral owner for document-wide work.
            execution_runtime: Host-owned runtime shared by editor operations.
            execution_policy: Policy used only for a standalone runtime.
            config_strict: When ``True``, reject overrides targeting inactive
                feature namespaces instead of logging warnings.
            **kwargs: Configuration overrides forwarded to ``QPaneState``.
        """
        super().__init__()
        if document_runtime is not None and (
            execution_runtime is not None or execution_policy is not None
        ):
            raise ValueError(
                "document_runtime cannot be combined with execution runtime options"
            )
        if document_runtime is not None:
            if document is not None and document_runtime.document is not document:
                raise ValueError("document_runtime belongs to a different document")
            resolved_document = document_runtime.document
            resolved_document_runtime = document_runtime
            owns_document_runtime = False
        else:
            resolved_document = document or CanvasDocument()
            resolved_document_runtime = CanvasDocumentRuntime(
                resolved_document,
                execution_runtime=execution_runtime,
                execution_policy=execution_policy,
            )
            owns_document_runtime = True
        self._execution_binding = CanvasExecutionBinding(
            self,
            document_runtime=resolved_document_runtime,
            close_document_runtime=owns_document_runtime,
        )
        self._session = session or CanvasViewSession()
        self._state = CuteCanvasState(
            qpane=self,
            initial_config=config,
            config_overrides=kwargs,
            features=features,
            execution_runtime=self._execution_binding.runtime,
            execution_scope=self._execution_binding.scope,
            config_strict=config_strict,
        )
        self._owns_document = document is None and document_runtime is None
        self._document = resolved_document
        self._diagnostics_manager = self._state.diagnostics
        self.interaction = ToolInteractionDelegate(self)
        self._hooks = CuteCanvasHooks(self)
        self._view: View | None = None
        self._composition_service: CompositionService | None = None
        self._editable_raster_assets: EditableRasterAssetStore | None = None
        self._editable_raster_layers: EditableRasterLayerController | None = None
        self._placed_assets: PlacedAssetStore | None = None
        self._image_documents: ImageDocumentWorkflow | None = None
        self._active_raster: ActiveRasterResolver | None = None
        self._layer_resource_operations: LayerResourceOperations | None = None
        self._project_resource_descriptors = None
        self._project_resource_capabilities = None
        self._project_resource_lifecycle = None
        self._mask_resource_fork_owner = None
        self._placed_asset_workflow: PlacedAssetWorkflow | None = None
        self._placed_asset_rasterization: PlacedAssetRasterizationService | None = None
        self._composition_rasterization: (
            CompositionResourceRasterizationService | None
        ) = None
        self._resource_rasterization: LayerResourceRasterizationRouter | None = None
        self._pixel_selection: PixelSelectionService | None = None
        self._layer_geometry: LayerGeometryResolver | None = None
        self._painting: PaintingCoordinator | None = None
        self._clone_stamp: CloneStampOperation | None = None
        self._paint_bucket: PaintBucketCoordinator | None = None
        self._selection_fill: SelectionFillCoordinator | None = None
        self._snap_configuration: SnapConfiguration | None = None
        self._coverage_shape_configuration: CoverageShapeConfiguration | None = None
        self._vector_editor: VectorHostFacade | None = None
        self._vector_interaction: VectorInteractionController | None = None
        self._vector_nodes: VectorNodeEditController | None = None
        self._vector_text: VectorTextEditController | None = None
        self._persistence_service: CompositionPersistenceService | None = None
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
        self._selected_pixel_movement: SelectedPixelMovementController | None = None
        self._editor_movement_interaction: EditorMovementInteraction | None = None
        self._operation_resolver: EditorOperationResolver | None = None
        self._paint_destination: InteractivePaintDestinationCoordinator | None = None
        self._last_floating_pixel_state: FloatingPixelSnapshot | None = None
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
        self._editor_source_capabilities: EditorSourceCapabilities | None = None
        self._composition_layer_assembler: CompositionLayerSceneAssembler | None = None
        self._scene_rasterizer = None
        self._projection_service = None
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
        self._last_viewport_rect: QRectF | None = None
        self._inspection_binding: SessionInspectionBinding | None = None
        self._outbound_mime_provider: OutboundMimeProvider | None = None
        self._drag_subject_resolver: CanvasDragSubjectResolver | None = None
        self._outbound_drag_subject = None
        self._outbound_drag = OutboundDragController(self)
        self._outbound_drag.failed.connect(self._handle_outbound_drag_failed)
        self._initial_view_signals_scheduled = False
        self._init_core_components()
        self._masks = Masks(
            qpane=self,
            cache_registry=self._state.cache_registry,
        )
        self._masks.register_diagnostics(self._diagnostics_manager)
        self._state.install_features()
        self.applyCacheSettings()
        self.interaction.initialize_widget_properties()
        self.interaction.connect_signals()
        self._apply_diagnostics_overlay_preferences()
        self._wire_facade_signals()
        self._inspection_binding = SessionInspectionBinding(
            session=self.viewSession(),
            viewport=self.view().viewport,
            target_bounds=self._inspection_target_bounds,
            viewport_size=lambda: self.physicalViewportRect().size(),
        )
        persistence = self._persistence_service
        if persistence is None:  # pragma: no cover - construction invariant
            raise RuntimeError("CuteCanvas persistence service was not installed")
        self._editor_facade = EditorFacade.create(self, persistence)
        self.destroyed.connect(self._state.on_destroyed)
        self.destroyed.connect(lambda _obj=None: self._execution_binding.close())
        self.destroyed.connect(lambda _obj=None: self._outbound_drag.close())
        self.destroyed.connect(
            lambda _obj=None: (
                None
                if self._projection_service is None
                else self._projection_service.shutdown()
            )
        )
        self.destroyed.connect(
            lambda _obj=None: (
                None
                if self._inspection_binding is None
                else self._inspection_binding.close()
            )
        )
        self._schedule_initial_view_signals()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Route Qt context-menu delivery through the focused host-content facade."""
        ContentContextApiMixin.contextMenuEvent(self, event)

    @property
    def editor(self) -> EditorFacade:
        """Return focused document, tool, selection, and history APIs."""
        return self._editor_facade

    # ========================================================================
    # Internal Implementation
    # ========================================================================

    def resizeEvent(self, event):
        """Handle qpane resizing by realigning the view and refreshing the cursor."""
        del event
        self._handle_canvas_resize()

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
            () if movement is None else movement.snap_guides,
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

    def showEvent(self, event: QShowEvent) -> None:
        """Handle initial show-time setup that depends on widget geometry."""
        super().showEvent(event)
        self.interaction.handle_show_event()
        self._refresh_screen_tracking()
        self._emit_viewport_rect_if_changed(force=True)

    def hideEvent(self, event: QHideEvent) -> None:
        """Release application-wide input observation while hidden."""
        self.interaction.handle_hide_event()
        super().hideEvent(event)

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
