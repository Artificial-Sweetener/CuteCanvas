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
"""CanvasAccessors behavior for the CuteCanvas facade."""

from __future__ import annotations

import logging
import uuid

from PySide6.QtCore import (
    QPoint,
    QRectF,
    QSize,
)
from PySide6.QtGui import (
    QImage,
)
from qpane.sdk.cache import CacheCoordinator
from qpane.sdk.diagnostics import Diagnostics
from qpane.sdk.rendering import RenderingPresenter, SceneCoordinateSystem, View
from qpane.sdk.scene import (
    LayerPlacement,
    LayerSourceCapabilities,
    SceneLayerHitTestResult,
    SceneProviderRegistry,
)
from qpane.sdk.ui import DiagnosticsOverlayController

from cutecanvas.composition import CompositionService
from cutecanvas.core import (
    CuteCanvasHooks,
)
from cutecanvas.coverage import CoverageShapeConfiguration
from cutecanvas.document import CanvasDocument, CanvasViewSession
from cutecanvas.editor import (
    EditorInteractionCoordinator,
    EditorMovementInteraction,
    EditorOperationResolver,
    InteractivePaintDestinationCoordinator,
)
from cutecanvas.editor.layer_edge_modification import LayerEdgeModificationCoordinator
from cutecanvas.editor.transform_interaction import EditorTransformInteraction
from cutecanvas.fill import PaintBucketCoordinator, SelectionFillCoordinator
from cutecanvas.masks.canvas_aperture import ActiveMaskCanvasAperture
from cutecanvas.masks.coordinates import ActiveMaskLayerCoordinates
from cutecanvas.masks.workflow import Masks
from cutecanvas.painting import PaintingCoordinator
from cutecanvas.painting.clone_operation import CloneStampOperation
from cutecanvas.raster.layers import EditableRasterLayerController
from cutecanvas.resources import ProjectResourceReference
from cutecanvas.resources.active_raster import ActiveRasterResolver
from cutecanvas.resources.active_raster_coordinates import (
    ActiveRasterCoordinateResolver,
)
from cutecanvas.runtime.document_runtime import CanvasDocumentRuntime
from cutecanvas.scene.geometry import aspect_scene_rect
from cutecanvas.scene.layer_geometry import LayerGeometryResolver
from cutecanvas.scene.movement_interaction import SceneLayerMovementInteraction
from cutecanvas.scene.mutations import SceneMutationCoordinator
from cutecanvas.scene.source_capabilities import EditorSourceCapabilities
from cutecanvas.selection import (
    PixelSelectionModificationCoordinator,
    PixelSelectionService,
)
from cutecanvas.snapping import SnapConfiguration
from cutecanvas.snapping.system import SnappingSubsystem
from cutecanvas.tools import Tools
from cutecanvas.types import (
    LayerPolicy,
)
from cutecanvas.vector.facade import VectorHostFacade
from cutecanvas.vector.interaction import VectorInteractionController
from cutecanvas.vector.node_edit import VectorNodeEditController
from cutecanvas.vector.text_edit import VectorTextEditController

logger = logging.getLogger(__name__)


class CanvasAccessorsMixin:
    """Group canvasaccessors facade behavior."""

    def activeRasterResolver(self) -> ActiveRasterResolver:
        """Return the active document raster-input resolver."""
        resolver = self._active_raster
        if resolver is None:
            raise RuntimeError("active raster resolver is not initialized")
        return resolver

    def active_raster_coordinates(self) -> ActiveRasterCoordinateResolver:
        """Return the active raster-instance coordinate resolver."""
        resolver = self._active_raster_coordinates
        if resolver is None:
            raise RuntimeError("active raster coordinates are not initialized")
        return resolver

    def _cache_metric_source(self, consumer_id: str) -> object | None:
        """Resolve cache metrics without teaching QPane about editor domains."""
        if consumer_id == "tiles":
            return self.view().presenter.tile_manager
        if consumer_id == "pyramids":
            return self.view().pyramid_manager
        if consumer_id == "mask_overlays":
            controller = self.mask_controller
            return None if controller is None else controller.renders
        if consumer_id == "models":
            return self.samManager()
        return None

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

    def coordinateSystem(self) -> SceneCoordinateSystem:
        """Return the coordinate system for the active editor rendering stack."""
        return self.view().coordinates

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

    def pixelSelectionModificationCoordinator(
        self,
    ) -> PixelSelectionModificationCoordinator:
        """Expose the asynchronous pixel-selection modification owner internally."""
        coordinator = self._pixel_selection_modifications
        if coordinator is None:
            raise AttributeError(
                "Pixel selection modification accessed before initialization"
            )
        return coordinator

    def layerEdgeModificationCoordinator(self) -> LayerEdgeModificationCoordinator:
        """Expose the generic whole-layer edge session owner internally."""
        coordinator = self._layer_edge_modifications
        if coordinator is None:
            raise AttributeError(
                "Layer edge modification accessed before initialization"
            )
        return coordinator

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

    def interactivePaintDestination(self) -> InteractivePaintDestinationCoordinator:
        """Expose private selected-layer paint preparation."""
        destination = self._paint_destination
        if destination is None:
            raise AttributeError(
                "Interactive paint destination accessed before initialization"
            )
        return destination

    def editableRasterLayers(self) -> EditableRasterLayerController:
        """Expose private editable-raster instance lifecycle."""
        layers = self._editable_raster_layers
        if layers is None:
            raise AttributeError(
                "Editable raster layers accessed before initialization"
            )
        return layers

    def activeMaskLayerCoordinates(self) -> ActiveMaskLayerCoordinates:
        """Expose private active-mask layer coordinate mapping."""
        coordinates = self._active_mask_coordinates
        if coordinates is None:
            raise AttributeError(
                "Active mask coordinates accessed before initialization"
            )
        return coordinates

    def activeMaskCanvasAperture(self) -> ActiveMaskCanvasAperture:
        """Expose private active-mask canvas-aperture projection."""
        aperture = self._active_mask_aperture
        if aperture is None:
            raise AttributeError("Active mask aperture accessed before initialization")
        return aperture

    def _active_resolved_scene_id(self) -> uuid.UUID | None:
        """Return the active internal scene identifier used for mutation routing."""
        composition_id = self.viewSession().active_composition_id
        if composition_id is not None:
            return composition_id
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
        if (
            active_scene is not None
            and active_scene.scene_id != scene_id
            and self.viewSession().active_composition_id == scene_id
        ):
            return active_scene.scene_id
        return scene_id

    def _placed_scope(
        self, scene_id: uuid.UUID, layer_id: uuid.UUID
    ) -> uuid.UUID | None:
        """Resolve an active public layer identity to its composition scope."""
        scope_id = self._layer_scope(scene_id, layer_id)
        if scope_id is None:
            return None
        instance = self.compositionService().layers.layer(scope_id, layer_id)
        assets = self._placed_assets
        return (
            scope_id
            if instance is not None
            and isinstance(instance.source, ProjectResourceReference)
            and assets is not None
            and assets.get(instance.source.resource_id) is not None
            else None
        )

    def _layer_scope(
        self, scene_id: uuid.UUID, layer_id: uuid.UUID
    ) -> uuid.UUID | None:
        """Resolve one active public layer identity to its composition scope."""
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        public_scene = self.currentScene()
        scope_id = self.viewSession().active_composition_id
        if public_scene is None or scope_id is None:
            return None
        if scene_id not in {public_scene.scene_id, public_scene.composition_id}:
            return None
        instance = self.compositionService().layers.layer(scope_id, layer_id)
        return scope_id if instance is not None else None

    @staticmethod
    def _validate_placed_inputs(
        image: QImage | None,
        placement: QRectF | None,
        label: str | None,
        interaction: LayerPolicy | None,
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
        if interaction is not None and not isinstance(interaction, LayerPolicy):
            raise TypeError("interaction must be LayerPolicy or None")

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

    def _publish_scene_layer_change(self) -> None:
        """Refresh rendering and publish committed layer/history state."""
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

    def editorSourceCapabilities(self) -> EditorSourceCapabilities:
        """Expose editor-only source capabilities for feature wiring."""
        capabilities = self._editor_source_capabilities
        if capabilities is None:
            raise AttributeError(
                "Editor source capabilities accessed before initialization"
            )
        return capabilities

    def paintingCoordinator(self) -> PaintingCoordinator:
        """Expose the internal source-neutral painting coordinator."""
        coordinator = self._painting
        if coordinator is None:
            raise AttributeError("painting coordinator accessed before initialization")
        return coordinator

    def cloneStampOperation(self) -> CloneStampOperation:
        """Expose the internal Clone Stamp state and stroke operation."""
        operation = self._clone_stamp
        if operation is None:
            raise AttributeError("Clone Stamp accessed before initialization")
        return operation

    def layerGeometryResolver(self) -> LayerGeometryResolver:
        """Expose the authoritative manipulation-geometry resolver."""
        resolver = self._layer_geometry
        if resolver is None:
            raise AttributeError("layer geometry accessed before initialization")
        return resolver

    def paintBucketCoordinator(self) -> PaintBucketCoordinator:
        """Expose the internal asynchronous Paint Bucket coordinator."""
        coordinator = self._paint_bucket
        if coordinator is None:
            raise AttributeError("Paint Bucket accessed before initialization")
        return coordinator

    def selectionFillCoordinator(self) -> SelectionFillCoordinator:
        """Expose the internal Fill Selection coordinator."""
        coordinator = self._selection_fill
        if coordinator is None:
            raise AttributeError("Fill Selection accessed before initialization")
        return coordinator

    def snapConfiguration(self) -> SnapConfiguration:
        """Expose the authoritative editor snapping configuration."""
        snapping = self._snapping
        if snapping is None:
            raise AttributeError("snapping accessed before initialization")
        return snapping.configuration

    def snappingSubsystem(self) -> SnappingSubsystem:
        """Expose the focused snapping collaboration boundary internally."""
        snapping = self._snapping
        if snapping is None:
            raise AttributeError("snapping accessed before initialization")
        return snapping

    def coverageShapeConfiguration(self) -> CoverageShapeConfiguration:
        """Expose the authoritative retained coverage shape configuration."""
        configuration = self._coverage_shape_configuration
        if configuration is None:
            raise AttributeError(
                "coverage shape options accessed before initialization"
            )
        return configuration

    def diagnostics(self) -> Diagnostics:
        """Expose the diagnostics coordinator for this CuteCanvas."""
        return self._diagnostics_manager

    def diagnosticsOverlayController(self) -> DiagnosticsOverlayController:
        """Return the diagnostics overlay controller owned by this CuteCanvas."""
        controller = self._diagnostics_overlay_controller
        if controller is None:
            controller = DiagnosticsOverlayController(self)
            self._diagnostics_overlay_controller = controller
        return controller

    @staticmethod
    def _aspect_scene_rect(
        source_size: QSize,
        target_rect: QRectF,
        *,
        cover: bool,
    ) -> QRectF:
        """Return an aspect-preserving rectangle centered on ``target_rect``."""
        return aspect_scene_rect(source_size, target_rect, cover=cover)

    def _scene_hit_test(self, panel_pos: QPoint) -> SceneLayerHitTestResult | None:
        """Return private scene-layer hit-test metadata for ``panel_pos``."""
        return self.view().scene_hit_test(panel_pos)

    @property
    def cacheCoordinator(self) -> CacheCoordinator | None:
        """Return the cache coordinator when coordination is enabled."""
        return self._state.cache_coordinator

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
    def hooks(self) -> CuteCanvasHooks:
        """Expose internal hook helpers reserved for CuteCanvas feature installers.

        Hosts must use the CuteCanvas.register* facade methods instead of calling this property directly.
        """
        return self._hooks

    def viewSession(self) -> CanvasViewSession:
        """Return the detachable activation and presentation state."""
        return self._session

    def document(self) -> CanvasDocument:
        """Return the headless content aggregate mounted by this widget."""
        return self._document

    def documentRuntime(self) -> CanvasDocumentRuntime:
        """Return the ephemeral document-wide execution owner."""
        return self._execution_binding.document_runtime

    def _inspection_target_bounds(self, target_id: uuid.UUID) -> QRectF | None:
        """Return one composition's native coordinate bounds."""
        try:
            return QRectF(self.compositionService().record(target_id).canvas_bounds)
        except KeyError:
            return None
