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
"""QPane's focused viewer facade over the declarative rendering SDK."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QEnterEvent,
    QHideEvent,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPaintEvent,
    QResizeEvent,
    QShowEvent,
    QTabletEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from .catalog import (
    ViewerCatalog,
    ViewerCatalogEntry,
    ViewerContent,
    ViewerNavigation,
    ViewerPlaceholder,
    ViewerPlaceholderState,
    ViewerPrefetch,
    ViewerPrefetchSnapshot,
)
from .compare import CompareDividerInteraction, ViewerComparison
from .core import (
    Config,
    Diagnostics,
    DiagnosticsProvider,
    DiagnosticsSnapshot,
    OverlayDrawFn,
    OverlayRegistry,
    SceneOverlayDrawFn,
)
from .execution import (
    DefaultExecutionPolicy,
    ExecutionRuntime,
    QtOwnerDispatcher,
    create_default_execution_runtime,
)
from .interaction import (
    ViewerInteractionController,
    ViewerInteractionHost,
    ViewerTool,
)
from .rendering import ViewerRenderingRuntime
from .rendering.coordinates import PanelHitTest
from .rendering.scene_coordinates import SceneCoordinateSystem
from .rendering.sdk import RasterSource, RenderLayer, RenderScene
from .scene.presentation_effects import (
    LayerPresentationEffect,
    LayerPresentationStyle,
)
from .scene.render_plan import SceneRenderPlan
from .types import (
    ComparisonDividerState,
    ComparisonOrientation,
    ComparisonState,
    LinkedGroup,
)
from .ui import ViewerDiagnostics


class QPane(QWidget):
    """Render large raster and semantic vector scenes with smooth pan and zoom."""

    sceneChanged = Signal(object)
    """Emit the active immutable ``RenderScene`` or ``None`` after replacement."""
    zoomChanged = Signal(float)
    """Emit the effective viewport zoom after navigation changes."""
    controlModeChanged = Signal(str)
    """Emit the active viewer-tool identifier after activation."""
    dragOutRequested = Signal(object)
    """Emit after QPane starts its configured drag-out operation."""
    diagnosticsOverlayToggled = Signal(bool)
    """Emit when the built-in live diagnostics overlay changes visibility."""
    diagnosticsDomainToggled = Signal(str, bool)
    """Emit a detail-domain identifier and its new enabled state."""
    catalogChanged = Signal()
    """Emit after viewer catalog resources, order, or selection changes."""
    catalogSelectionChanged = Signal(object)
    """Emit the selected ``ViewerCatalogEntry`` or ``None``."""
    comparisonChanged = Signal(object)
    """Emit the immutable ``ComparisonState`` after effective changes."""
    linkGroupsChanged = Signal()
    """Emit after catalog viewport-link policy changes."""
    placeholderChanged = Signal(object)
    """Emit ``ViewerPlaceholderState`` after placeholder lifecycle changes."""

    CONTROL_MODE_PANZOOM = "panzoom"
    CONTROL_MODE_CURSOR = "cursor"

    def __init__(
        self,
        *,
        config: Config | None = None,
        execution_runtime: ExecutionRuntime | None = None,
        execution_policy: DefaultExecutionPolicy | None = None,
    ) -> None:
        """Build an independently usable rendering widget.

        Args:
            config: Optional detached rendering configuration.
            execution_runtime: Optional host-owned runtime shared across widgets.
            execution_policy: Standalone runtime policy used only when QPane
                creates its own runtime.
        """
        super().__init__()
        if execution_runtime is not None and execution_policy is not None:
            raise ValueError(
                "execution_policy cannot configure a host-owned execution_runtime"
            )
        self.settings = Config() if config is None else config.copy()
        self._owns_execution_runtime = execution_runtime is None
        self._execution_runtime = (
            execution_runtime
            if execution_runtime is not None
            else create_default_execution_runtime(execution_policy)
        )
        self._execution_dispatcher = QtOwnerDispatcher(self)
        self._execution_scope = self._execution_runtime.open_scope(
            owner_id=f"qpane:{id(self)}",
            dispatcher=self._execution_dispatcher,
        )
        self._rendering = ViewerRenderingRuntime(
            self,
            self.settings,
            self._execution_scope,
        )
        self.viewport = self._rendering.viewport
        self._content = ViewerContent(self.scene)
        self._viewer_diagnostics = ViewerDiagnostics(
            pane=self,
            presenter=self._rendering.presenter,
            pyramids=self._rendering.pyramids,
            execution_runtime=self._execution_runtime,
            overlay_changed=self.diagnosticsOverlayToggled.emit,
            detail_changed=self.diagnosticsDomainToggled.emit,
        )
        self._host_navigation_locked = False
        self._placeholder_navigation_locked = False
        self._overlays = OverlayRegistry(self.update)
        self._catalog = ViewerCatalog(self)
        self._comparison = ViewerComparison(
            self._catalog,
            lambda scene, fit: self._apply_scene(scene, fit=fit),
            self,
        )
        self._catalog_navigation = ViewerNavigation(
            self._catalog,
            self.viewport,
            self,
        )
        self._catalog_prefetch = ViewerPrefetch(
            self._catalog,
            self._rendering.pyramids,
            self.settings,
            lambda: self._viewer_diagnostics.broker.set_dirty("swap"),
        )
        self._viewer_diagnostics.register_provider(
            self._catalog_prefetch.diagnostics,
            domain="swap",
            detail=True,
        )
        self._placeholder = ViewerPlaceholder(
            catalog=self._catalog,
            viewport=self.viewport,
            execution_scope=self._execution_scope.open_child(
                f"{self._execution_scope.owner_id}:placeholder"
            ),
            set_scene=lambda scene, fit: self._apply_scene(scene, fit=fit),
            set_navigation_enabled=self._set_placeholder_navigation_enabled,
            parent=self,
        )
        self._placeholder.changed.connect(self.placeholderChanged)
        self._compare_interaction = CompareDividerInteraction(
            qpane=self,
            service=self._comparison,
        )
        self._interaction = ViewerInteractionController(
            ViewerInteractionHost(
                widget=self,
                viewport=self.viewport,
                settings=lambda: self.settings,
                is_content_empty=lambda: self._rendering.is_blank,
                physical_viewport_rect=self.physicalViewportRect,
                is_drag_out_allowed=self._is_drag_out_allowed,
                repaint=self.update,
                emit_mode_changed=self.controlModeChanged.emit,
                emit_drag_out_requested=self._request_drag_out,
                claim_external_touch=self._compare_interaction.handle_touch_begin,
                update_external_touch=self._compare_interaction.handle_touch_update,
                finish_external_touch=self._compare_interaction.handle_touch_end,
                cancel_external_touch=self._compare_interaction.cancel_drag,
                handle_external_mouse_press=(
                    self._compare_interaction.handle_mouse_press
                ),
                handle_external_mouse_move=self._compare_interaction.handle_mouse_move,
                handle_external_mouse_release=(
                    self._compare_interaction.handle_mouse_release
                ),
                external_cursor=self._compare_interaction.cursor,
                begin_navigation=(
                    self._rendering.presenter.begin_navigation_interaction
                ),
                finish_navigation=(
                    self._rendering.presenter.finish_navigation_interaction
                ),
            )
        )
        self._catalog.changed.connect(self.catalogChanged)
        self._catalog.selectionChanged.connect(self.catalogSelectionChanged)
        self._catalog.resourcesInvalidated.connect(self._rendering.discard_sources)
        self._comparison.changed.connect(self.comparisonChanged)
        self._rendering.sceneChanged.connect(self._handle_rendering_scene_changed)
        self._rendering.zoomChanged.connect(self.zoomChanged)
        self._rendering.diagnosticsDirty.connect(
            self._viewer_diagnostics.mark_render_dirty
        )
        self.destroyed.connect(self._shutdown)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.setTabletTracking(True)
        self._placeholder.apply_config(self.settings)
        self._apply_diagnostics_preferences()

    def setScene(self, scene: RenderScene | None, *, fit: bool = True) -> bool:
        """Submit or clear one immutable raster/vector scene.

        Args:
            scene: Declarative scene to display, or ``None`` to clear.
            fit: Refit the canvas after a changed scene is accepted.

        Returns:
            ``True`` when the active scene changed.

        Side effects:
            Invalidates compiled render products, repaints the widget, and emits
            ``sceneChanged``. Reusable source products remain cache-addressed by
            source identity rather than layer placement.
        """
        comparison = getattr(self, "_comparison", None)
        if comparison is not None:
            comparison.abandon()
        placeholder = getattr(self, "_placeholder", None)
        if placeholder is not None:
            placeholder.suspend()
        return self._apply_scene(scene, fit=fit)

    def _apply_scene(self, scene: RenderScene | None, *, fit: bool) -> bool:
        """Apply a scene already reconciled with viewer presentation state."""
        return self._rendering.set_scene(scene, fit=fit)

    def scene(self) -> RenderScene | None:
        """Return the active immutable render scene."""
        return self._rendering.scene

    @property
    def currentImage(self) -> QImage | None:
        """Return the current base raster through an implicitly shared handle."""
        return self._content.image()

    @property
    def currentImagePath(self) -> Path | None:
        """Return the current base raster's source path when one exists."""
        return self._content.path()

    def copyCurrentImageToClipboard(self) -> bool:
        """Copy the current base raster to the system clipboard."""
        return self._content.copy_to_clipboard()

    def setImage(self, image: QImage, *, fit: bool = True) -> RasterSource:
        """Display one image through the same declarative rendering pipeline.

        Args:
            image: Non-null source image.
            fit: Refit the image after submission.

        Returns:
            Reusable source handle suitable for additional ``RenderLayer`` values.
        """
        source = RasterSource.from_image(image)
        scene = RenderScene.from_size(source.size, (RenderLayer(source),))
        self.setScene(scene, fit=fit)
        return source

    def clear(self) -> None:
        """Clear the submitted scene while retaining reusable cache budgets."""
        self.setScene(None)

    def setZoomFit(self) -> None:
        """Fit the active scene canvas inside the widget."""
        self.viewport.setZoomFit()

    def setZoom1To1(self, anchor: QPointF | None = None) -> None:
        """Show one source pixel per physical device pixel."""
        self.viewport.setZoom1To1(anchor=anchor)

    def applyZoom(self, zoom: float, anchor: QPointF | None = None) -> None:
        """Apply a clamped custom zoom around an optional widget anchor."""
        self.viewport.applyZoom(zoom, anchor=anchor)

    def currentZoom(self) -> float:
        """Return the effective viewport zoom."""
        return float(self.viewport.zoom)

    def currentPan(self) -> QPointF:
        """Return detached physical viewport translation."""
        return QPointF(self.viewport.pan)

    def setPan(self, pan: QPointF) -> None:
        """Apply physical viewport translation."""
        self.viewport.setPan(QPointF(pan))

    def setPanZoomLocked(self, locked: bool) -> None:
        """Enable or disable every viewport navigation path."""
        self._host_navigation_locked = bool(locked)
        self._apply_navigation_lock()

    def panZoomLocked(self) -> bool:
        """Return whether viewport navigation is disabled."""
        return self.viewport.is_locked()

    def applySettings(
        self,
        config: Config | None = None,
        **overrides: object,
    ) -> None:
        """Atomically apply viewer configuration and refresh its collaborators.

        Args:
            config: Optional complete configuration snapshot.
            **overrides: Individual configuration values applied afterward.
        """
        candidate = self.settings.copy() if config is None else config.copy()
        if overrides:
            candidate.configure(**overrides)
        self._viewer_diagnostics.validate_preferences(candidate)
        self._rendering.validate_config(candidate)
        self.settings = candidate
        self._rendering.apply_config(candidate)
        self._catalog_prefetch.apply_config(candidate)
        self._placeholder.apply_config(candidate)
        self._viewer_diagnostics.apply_preferences(candidate)

    def registerTool(
        self,
        mode: str,
        factory: Callable[[], ViewerTool],
        *,
        dependencies: Callable[[], object] | None = None,
    ) -> None:
        """Register a custom viewer tool through QPane's input and overlay host.

        Args:
            mode: Stable control-mode identifier.
            factory: Callable producing one ``ViewerTool`` instance.
            dependencies: Optional lazy activation-port provider. An empty
                mapping is supplied when omitted.
        """
        self._interaction.register_tool(mode, factory, dependencies)

    def unregisterTool(self, mode: str) -> None:
        """Remove an inactive custom viewer tool."""
        self._interaction.unregister_tool(mode)

    def setControlMode(self, mode: str) -> None:
        """Activate a registered viewer tool."""
        self._interaction.activate(mode)

    def controlMode(self) -> str:
        """Return the active viewer-tool identifier."""
        return self._interaction.active_mode()

    def availableControlModes(self) -> tuple[str, ...]:
        """Return registered viewer-tool identifiers."""
        return self._interaction.available_modes()

    def catalog(self) -> ViewerCatalog:
        """Return the viewer's ordered reusable image catalog."""
        return self._catalog

    def addImage(
        self,
        image: QImage,
        *,
        label: str = "Untitled",
        path: Path | None = None,
        source_id: uuid.UUID | None = None,
        select: bool = True,
    ) -> ViewerCatalogEntry:
        """Add an image to the built-in catalog and optionally display it."""
        return self._catalog.add_image(
            image,
            label=label,
            path=path,
            source_id=source_id,
            select=select,
        )

    def selectCatalogImage(self, entry_id: uuid.UUID) -> bool:
        """Select and display one catalog resource by stable identity."""
        current = self._catalog.current
        if current is not None and current.entry_id == entry_id:
            return self._comparison.show_selection(fit=False)
        return self._catalog.select_entry(entry_id)

    def selectNextImage(self) -> bool:
        """Select the next catalog resource with wraparound."""
        if len(self._catalog.entries) == 1:
            return self._comparison.show_selection(fit=False)
        return self._catalog.step(1)

    def selectPreviousImage(self) -> bool:
        """Select the previous catalog resource with wraparound."""
        if len(self._catalog.entries) == 1:
            return self._comparison.show_selection(fit=False)
        return self._catalog.step(-1)

    def removeCatalogImage(self, entry_id: uuid.UUID) -> ViewerCatalogEntry:
        """Remove one catalog resource and display its nearest neighbor."""
        return self._catalog.remove(entry_id)

    def clearCatalog(self) -> None:
        """Remove every catalog resource and clear catalog presentation."""
        self._catalog.clear()

    def linkedImageGroups(self) -> tuple[LinkedGroup, ...]:
        """Return image groups that share one normalized viewport state."""
        return self._catalog_navigation.groups()

    def setLinkedImageGroups(self, groups: Iterable[LinkedGroup]) -> None:
        """Replace groups whose catalog images share pan and zoom state."""
        snapshot = tuple(groups)
        self._catalog_navigation.set_groups(snapshot)
        self.linkGroupsChanged.emit()

    def setAllImagesLinked(self, enabled: bool) -> None:
        """Link every catalog image's viewport state or clear all links."""
        self._catalog_navigation.set_all_linked(bool(enabled))
        self.linkGroupsChanged.emit()

    def catalogPrefetchState(self) -> ViewerPrefetchSnapshot:
        """Return immutable neighboring-pyramid prefetch counters."""
        return self._catalog_prefetch.snapshot()

    def placeholderState(self) -> ViewerPlaceholderState:
        """Return the configured placeholder's immutable lifecycle state."""
        return self._placeholder.state()

    def setPlaceholderImage(
        self,
        image: QImage | None,
        *,
        path: Path | None = None,
    ) -> None:
        """Install an already-decoded empty-catalog placeholder image."""
        self._placeholder.set_image(image, path=path)

    def compareWithNextImage(self) -> bool:
        """Reveal the next catalog source over the selected image."""
        return self._comparison.compare_with_next()

    def setComparisonImage(self, entry_id: uuid.UUID) -> None:
        """Reveal one catalog source over the selected image."""
        self._comparison.set_source(entry_id)

    def clearComparison(self) -> None:
        """Disable the current image comparison."""
        self._comparison.clear()

    def setComparisonSplit(
        self,
        position: float,
        orientation: ComparisonOrientation | str | None = None,
    ) -> None:
        """Set the normalized comparison divider and optional orientation."""
        self._comparison.set_split(position, orientation)

    def comparisonState(self) -> ComparisonState:
        """Return the immutable catalog-comparison snapshot."""
        return self._comparison.state()

    def setComparisonDividerInteractive(self, enabled: bool) -> None:
        """Enable or disable built-in mouse and touch divider dragging."""
        self._compare_interaction.set_interactive(enabled)
        self._interaction.refresh_cursor()

    def comparisonDividerInteractive(self) -> bool:
        """Return whether comparison divider dragging is enabled."""
        return self._compare_interaction.interactive()

    def comparisonDividerState(self) -> ComparisonDividerState:
        """Return projected divider geometry for optional host drawing."""
        return self._compare_interaction.state()

    def diagnostics(self) -> Diagnostics:
        """Return QPane's live source-neutral diagnostics broker."""
        return self._viewer_diagnostics.broker

    def gatherDiagnostics(self) -> DiagnosticsSnapshot:
        """Collect a current renderer, viewport, tile, pyramid, and worker snapshot."""
        return self._viewer_diagnostics.gather()

    def createStatusOverlay(self, *, parent: QWidget | None = None) -> QWidget:
        """Create a live diagnostics HUD bound to this viewer."""
        return self._viewer_diagnostics.create_status_overlay(parent)

    def setDiagnosticsOverlayEnabled(self, enabled: bool) -> None:
        """Show or hide QPane's built-in live diagnostics HUD."""
        self._viewer_diagnostics.set_overlay_enabled(enabled)

    def diagnosticsOverlayEnabled(self) -> bool:
        """Return whether the live diagnostics HUD is visible."""
        return self._viewer_diagnostics.overlay_enabled()

    def diagnosticsDomains(self) -> tuple[str, ...]:
        """Return optional live diagnostics detail domains."""
        return self._viewer_diagnostics.domains()

    def setDiagnosticsDomainEnabled(self, domain: str, enabled: bool) -> None:
        """Enable or disable one optional diagnostics detail domain."""
        self._viewer_diagnostics.set_domain_enabled(domain, enabled)

    def diagnosticsDomainEnabled(self, domain: str) -> bool:
        """Return whether one optional diagnostics detail domain is enabled."""
        return self._viewer_diagnostics.domain_enabled(domain)

    def registerDiagnosticsProvider(
        self,
        provider: DiagnosticsProvider,
        *,
        domain: str = "custom",
        detail: bool = False,
    ) -> None:
        """Add one host diagnostics provider to the live QPane broker."""
        self._viewer_diagnostics.register_provider(
            provider,
            domain=domain,
            detail=detail,
        )

    def registerOverlay(self, name: str, draw_fn: OverlayDrawFn) -> None:
        """Register one named overlay drawn relative to the base raster source."""
        self._overlays.register_content(name, draw_fn)

    def unregisterOverlay(self, name: str) -> None:
        """Remove one content overlay when present."""
        self._overlays.unregister_content(name)

    def registerSceneOverlay(self, name: str, draw_fn: SceneOverlayDrawFn) -> None:
        """Register one named overlay drawn with ordered scene-layer geometry."""
        self._overlays.register_scene(name, draw_fn)

    def unregisterSceneOverlay(self, name: str) -> None:
        """Remove one scene overlay when present."""
        self._overlays.unregister_scene(name)

    def addLayerPresentationEffect(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        style: LayerPresentationStyle,
        *,
        effect_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        """Add one ordered transient effect over a rendered scene layer."""
        return self._rendering.add_layer_presentation_effect(
            scene_id,
            layer_id,
            style,
            effect_id=effect_id,
        )

    def updateLayerPresentationEffect(
        self,
        effect_id: uuid.UUID,
        style: LayerPresentationStyle,
    ) -> bool:
        """Replace one effect style without changing its identity or order."""
        return self._rendering.update_layer_presentation_effect(effect_id, style)

    def removeLayerPresentationEffect(self, effect_id: uuid.UUID) -> bool:
        """Remove one transient effect when present."""
        return self._rendering.remove_layer_presentation_effect(effect_id)

    def clearLayerPresentationEffects(
        self,
        *,
        scene_id: uuid.UUID | None = None,
        layer_id: uuid.UUID | None = None,
    ) -> int:
        """Remove matching transient effects and return the removal count."""
        return self._rendering.clear_layer_presentation_effects(
            scene_id=scene_id,
            layer_id=layer_id,
        )

    def layerPresentationEffects(self) -> tuple[LayerPresentationEffect, ...]:
        """Return registered transient effects in deterministic draw order."""
        return self._rendering.layer_presentation_effects()

    def calculateRenderPlan(
        self,
        *,
        use_pan: QPointF | None = None,
    ) -> SceneRenderPlan | None:
        """Return the renderer plan for diagnostics and renderer buffer repair."""
        return self._rendering.calculate_plan(use_pan=use_pan)

    def view(self) -> QPane:
        """Return the focused view boundary expected by renderer collaborators."""
        return self

    def physicalViewportRect(self) -> QRectF:
        """Return the current widget viewport in physical pixels."""
        return self._rendering.physical_viewport_rect()

    def panelHitTest(self, point: QPoint | QPointF) -> PanelHitTest | None:
        """Project one widget point into scene and source coordinates."""
        return self._rendering.panel_hit_test(point)

    def coordinateSystem(self) -> SceneCoordinateSystem:
        """Return the typed authoritative coordinate projection service."""
        return self._rendering.presenter.coordinates

    def minimumSizeHint(self) -> QSize:
        """Return the configured minimum viewer size."""
        return self._rendering.minimum_size_hint()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Render the active scene through QPane's shared compositor."""
        del event
        self._rendering.paint(
            content_overlays=self._overlays.content,
            scene_overlays=self._overlays.scene,
            draw_tool_overlay=self._interaction.draw_overlay,
        )

    def event(self, event: QEvent) -> bool:
        """Route touch frames through QPane's normalized pointer controller."""
        interaction = getattr(self, "_interaction", None)
        if interaction is not None and interaction.handle_event(event):
            event.accept()
            return True
        return super().event(event)

    def tabletEvent(self, event: QTabletEvent) -> None:
        """Route tablet samples through QPane's normalized pointer controller."""
        if self._interaction.handle_tablet(event):
            event.accept()
            return
        super().tabletEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Realign viewport geometry after widget resize."""
        super().resizeEvent(event)
        self._rendering.resize()

    def showEvent(self, event: QShowEvent) -> None:
        """Enable visible-view input observation and refresh the cursor."""
        super().showEvent(event)
        self._interaction.set_visible(True)
        self._interaction.refresh_cursor()

    def hideEvent(self, event: QHideEvent) -> None:
        """Release global input observation while the viewer is hidden."""
        self._interaction.set_visible(False)
        super().hideEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Route wheel input through the active QPane tool."""
        self._interaction.handle_wheel(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Route pointer presses through the active QPane tool."""
        self._interaction.handle_mouse_press(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Route pointer movement through the active QPane tool."""
        self._interaction.handle_mouse_move(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Route pointer releases through the active QPane tool."""
        self._interaction.handle_mouse_release(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Route double-click navigation through the active QPane tool."""
        self._interaction.handle_mouse_double_click(event)

    def enterEvent(self, event: QEnterEvent) -> None:
        """Reconcile pointer modality and active-tool cursor on entry."""
        self._interaction.handle_enter(event)

    def leaveEvent(self, event: QEvent) -> None:
        """Clear direct-input feedback and notify the active tool on exit."""
        self._interaction.handle_leave(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Route key presses through the active QPane tool."""
        self._interaction.handle_key_press(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        """Route key releases through the active QPane tool."""
        self._interaction.handle_key_release(event)

    def _handle_rendering_scene_changed(self, scene: RenderScene | None) -> None:
        """Publish accepted scenes and reconcile active-tool cursor policy."""
        self._interaction.refresh_cursor()
        self.sceneChanged.emit(scene)

    def _shutdown(self, _object: object | None = None) -> None:
        """Stop viewer-owned asynchronous rendering work."""
        interaction = getattr(self, "_interaction", None)
        if interaction is not None:
            interaction.shutdown()
        catalog_prefetch = getattr(self, "_catalog_prefetch", None)
        if catalog_prefetch is not None:
            catalog_prefetch.shutdown()
        placeholder = getattr(self, "_placeholder", None)
        if placeholder is not None:
            placeholder.shutdown()
        rendering = getattr(self, "_rendering", None)
        if rendering is not None:
            rendering.shutdown()
        viewer_diagnostics = getattr(self, "_viewer_diagnostics", None)
        if viewer_diagnostics is not None:
            viewer_diagnostics.close()
        execution_scope = getattr(self, "_execution_scope", None)
        if execution_scope is not None:
            execution_scope.close(reason="qpane_shutdown")
        execution_runtime = getattr(self, "_execution_runtime", None)
        if (
            getattr(self, "_owns_execution_runtime", False)
            and execution_runtime is not None
        ):
            execution_runtime.shutdown(wait=False)

    def _is_drag_out_allowed(self) -> bool:
        """Return whether current content fits and host drag-out is enabled."""
        placeholder_policy = self._placeholder.drag_out_allowed()
        drag_enabled = (
            bool(self.settings.drag_out_enabled)
            if placeholder_policy is None
            else placeholder_policy
        )
        if self._rendering.is_blank or not drag_enabled:
            return False
        size = self.viewport.content_size
        panel = self.physicalViewportRect().size()
        return (
            size.width() * self.viewport.zoom <= panel.width()
            and size.height() * self.viewport.zoom <= panel.height()
        )

    def _request_drag_out(self, event: object) -> None:
        """Perform QPane's default drag-out behavior and publish the request."""
        mouse_event = event if isinstance(event, QMouseEvent) else None
        self._content.start_drag(self, mouse_event)
        self.dragOutRequested.emit(event)

    def _set_placeholder_navigation_enabled(self, enabled: bool) -> None:
        """Apply placeholder navigation as policy beside the host lock."""
        self._placeholder_navigation_locked = not bool(enabled)
        self._apply_navigation_lock()

    def _apply_navigation_lock(self) -> None:
        """Project host and placeholder policy into the viewport."""
        self._interaction.set_navigation_locked(
            self._host_navigation_locked or self._placeholder_navigation_locked
        )

    def _apply_diagnostics_preferences(self) -> None:
        """Apply configured detail domains and overlay visibility at startup."""
        self._viewer_diagnostics.apply_preferences(self.settings)
