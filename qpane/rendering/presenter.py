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

"""Rendering presenter responsible for QPane's drawing pipeline."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping
from math import isclose
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, QSizeF
from PySide6.QtGui import QPainter, Qt, QTransform
from PySide6.QtWidgets import QWidget

from ..scene.identity import (
    SceneLayerTileKey,
)
from ..scene.model import (
    LayerDescriptor,
    SceneDescriptor,
)
from ..scene.render_plan import (
    RasterLayerRenderItem,
    SceneContentSnapshot,
    SceneLayerHitTestResult,
    SceneRenderItem,
    SceneRenderPlan,
    VectorLayerRenderItem,
)
from ..types import OverlayState, QPaneSceneOverlayLayer, QPaneSceneOverlayState
from ..vector.render_cache import VectorRenderCache
from ..vector.render_tiles import VectorRenderWorkCoordinator, VectorTileCache
from .compiled_scene import CompiledRenderScene
from .coordinates import CoordinateContext, PanelHitTest
from .floating_pixels import FloatingPixelRenderCompiler
from .frame_geometry import RenderFrameGeometry, visible_scene_rect
from .frame_projector import SceneFrameProjector
from .layer_effects import LayerEffectFrameCompiler
from .raster_planner import RasterRenderPlanner
from .raster_products import RasterPyramidProducts, RasterRenderProductStore
from .render import Renderer
from .scene_compiler import SceneRenderCompiler
from .scene_hit_testing import SceneRenderHitTester
from .tiles import TileManager
from .vector_planner import VectorRenderPlanner
from .viewport import Viewport, ViewportZoomMode

if TYPE_CHECKING:
    from ..cache.registry import CacheRegistry
    from ..catalog import ImageCatalog
    from ..concurrency import TaskExecutorProtocol
    from ..core import OverlayDrawFn, SceneOverlayDrawFn
    from ..qpane import QPane
    from ..scene.effects import LayerEffectRenderRegistry
    from ..scene.pixel_move_preview import RasterPixelMovePreview
    from ..scene.registry import SceneProviderRegistry
    from ..scene.source_capabilities import (
        PixelPresentationRegistry,
        RasterPatchPresentationRegistry,
        RasterPresentationRegistry,
        SourceHitTestRegistry,
        SourceMetadataRegistry,
        VectorPresentationRegistry,
    )
    from ..vector.text_layout import SemanticTextLayoutCache
logger = logging.getLogger(__name__)


class RenderingPresenter:
    """Encapsulate rendering-specific state and QWidget hooks for QPane."""

    def __init__(
        self,
        *,
        qpane: QPane,
        catalog: ImageCatalog,
        pyramid_products: RasterPyramidProducts,
        cache_registry: CacheRegistry | None,
        executor: TaskExecutorProtocol,
        scene_providers: SceneProviderRegistry,
        source_metadata: SourceMetadataRegistry,
        raster_sources: RasterPresentationRegistry,
        raster_patches: RasterPatchPresentationRegistry,
        source_hit_tests: SourceHitTestRegistry,
        pixel_presentation: PixelPresentationRegistry,
        vector_sources: VectorPresentationRegistry,
        layer_effects: LayerEffectRenderRegistry,
    ) -> None:
        """Compose viewport/tile/renderer collaborators owned by the presenter."""
        self._qpane = qpane
        self._catalog = catalog
        self.viewport = Viewport(qpane, qpane.settings)
        self.tile_manager = TileManager(qpane.settings, parent=qpane, executor=executor)
        if cache_registry is not None:
            cache_registry.attach_tile_manager(self.tile_manager)
        self.renderer = Renderer(qpane)
        self._raster_products = RasterRenderProductStore(
            pyramid_products,
            self.tile_manager,
        )
        if cache_registry is not None:
            cache_registry.attach_raster_render_products(self._raster_products)
        self._scene_providers = scene_providers
        self._source_hit_tests = source_hit_tests
        self._scene_compiler = SceneRenderCompiler(
            catalog=catalog,
            scene_providers=self._scene_providers,
            source_metadata=source_metadata,
            raster_sources=raster_sources,
            vector_sources=vector_sources,
        )
        self._frame_projector = SceneFrameProjector(self.viewport)
        self._raster_planner = RasterRenderPlanner(
            compiler=self._scene_compiler,
            projector=self._frame_projector,
            products=self._raster_products,
            raster_sources=raster_sources,
            raster_patches=raster_patches,
            tile_manager_provider=lambda: self.tile_manager,
            viewport=self.viewport,
        )
        self._vector_cache = VectorRenderCache()
        if cache_registry is not None:
            cache_registry.attach_vector_render_cache(self._vector_cache)
        self._vector_tile_cache = VectorTileCache()
        if cache_registry is not None:
            cache_registry.attach_vector_tile_cache(self._vector_tile_cache)
        self._vector_refinement = VectorRenderWorkCoordinator(
            executor=executor,
            cache=self._vector_tile_cache,
            ready=self._handle_vector_refinement_ready,
        )
        self._vector_planner = VectorRenderPlanner(
            sources=vector_sources,
            projector=self._frame_projector,
            cache=self._vector_cache,
            refinement=self._vector_refinement,
        )
        self._layer_effects = LayerEffectFrameCompiler(layer_effects)
        self._scene_hit_tester = SceneRenderHitTester()
        self._floating_pixels = FloatingPixelRenderCompiler(pixel_presentation)
        self._last_view_size = QSize()
        self._last_device_pixel_ratio = float(qpane.devicePixelRatioF())
        self._last_scroll_reuse_signature: tuple[object, ...] | None = None
        self._pixel_move_preview_provider: Callable[
            [], RasterPixelMovePreview | None
        ] = lambda: None

    def shutdown(self) -> None:
        """Cancel presenter-owned asynchronous derived rendering work."""
        self._vector_refinement.shutdown()

    def set_vector_text_layouts(self, layouts: SemanticTextLayoutCache) -> None:
        """Install the vector domain's focused semantic text derivative owner."""
        self._vector_cache.set_text_layouts(layouts)

    def set_placeholder_content_provider(
        self, provider: Callable[[], object | None]
    ) -> None:
        """Install the catalog-owned placeholder content provider."""
        self._scene_compiler.set_placeholder_content_provider(provider)

    def set_pixel_move_preview_provider(
        self,
        provider: Callable[[], RasterPixelMovePreview | None],
    ) -> None:
        """Install the transient selected-pixel preview provider."""
        self._pixel_move_preview_provider = provider

    def calculateRenderPlan(
        self,
        *,
        use_pan: QPointF | None = None,
        is_blank: bool = False,
    ) -> SceneRenderPlan | None:
        """Build the active scene render plan for the current viewport."""
        if is_blank:
            return None
        compiled = self._scene_compiler.compiled_scene()
        if compiled is None:
            return None
        frame = self._frame_geometry_for(compiled, use_pan=use_pan)
        raster_items = self._raster_planner.build_frame_items(compiled, frame)
        vector_items = self._vector_planner.build_frame_items(compiled, frame)
        effect_items = self._layer_effects.apply((*raster_items, *vector_items))
        items_by_layer_id: dict[uuid.UUID, list[SceneRenderItem]] = {}
        for item in effect_items:
            items_by_layer_id.setdefault(item.descriptor.layer_id, []).append(item)
        render_items = tuple(
            item
            for layer in compiled.scene.layers
            for item in items_by_layer_id.get(layer.layer_id, ())
        )
        if not render_items:
            return None
        return SceneRenderPlan(
            scene_id=compiled.scene.scene_id,
            scene_bounds=compiled.scene.bounds,
            content_bounds=compiled.scene.bounds,
            content_snapshot=compiled.content_snapshot,
            zoom=frame.zoom,
            current_pan=frame.current_pan,
            qpane_rect=frame.qpane_rect,
            physical_viewport_rect=frame.physical_viewport_rect,
            render_items=render_items,
            hit_test_items=compiled.hit_test_items,
            floating_pixels=self._floating_pixels.compile(
                self._pixel_move_preview_provider(),
                render_items,
            ),
        )

    def paint(
        self,
        *,
        is_blank: bool,
        content_overlays: Mapping[str, OverlayDrawFn],
        scene_overlays: Mapping[str, SceneOverlayDrawFn] | None = None,
        overlays_suspended: bool,
        draw_tool_overlay: Callable[[QPainter], None] | None,
    ) -> SceneRenderPlan | None:
        """Render the current frame and return the scene render plan used."""
        active_scene_overlays = scene_overlays or {}
        if is_blank:
            render_plan = (
                self.calculateRenderPlan(is_blank=is_blank)
                if content_overlays or active_scene_overlays
                else None
            )
            painter = QPainter(self._qpane)
            try:
                painter.fillRect(self._qpane.rect(), Qt.transparent)
                self._draw_content_overlays(
                    painter,
                    render_plan,
                    content_overlays,
                    overlays_suspended=overlays_suspended,
                )
                self._draw_scene_overlays(
                    painter,
                    render_plan,
                    active_scene_overlays,
                    overlays_suspended=overlays_suspended,
                )
            finally:
                painter.end()
            return render_plan
        render_plan = self.calculateRenderPlan(is_blank=is_blank)
        if render_plan:
            self._ensure_buffer_matches_widget()
            self.renderer.paint(render_plan)
            self._last_scroll_reuse_signature = self._scroll_reuse_signature_for_plan(
                render_plan
            )
        else:
            self._last_scroll_reuse_signature = None
        painter = QPainter(self._qpane)
        try:
            self.renderer.draw_base_buffer(painter)
            self._draw_content_overlays(
                painter,
                render_plan,
                content_overlays,
                overlays_suspended=overlays_suspended,
            )
            self._draw_scene_overlays(
                painter,
                render_plan,
                active_scene_overlays,
                overlays_suspended=overlays_suspended,
            )
            if draw_tool_overlay and not is_blank:
                draw_tool_overlay(painter)
        finally:
            painter.end()
        return render_plan

    def _draw_content_overlays(
        self,
        painter: QPainter,
        render_plan: SceneRenderPlan | None,
        content_overlays: Mapping[str, OverlayDrawFn],
        *,
        overlays_suspended: bool,
    ) -> None:
        """Draw public overlays from the base raster item when available."""
        if render_plan is None or overlays_suspended or not content_overlays:
            return
        overlay_state = self._build_overlay_state(render_plan)
        if overlay_state is None:
            return
        for draw_overlay in content_overlays.values():
            draw_overlay(painter, overlay_state)

    def _build_overlay_state(self, render_plan: SceneRenderPlan) -> OverlayState | None:
        """Project a scene render plan onto the public OverlayState surface."""
        base_item = render_plan.base_raster_item
        if base_item is None:
            return None
        return OverlayState(
            zoom=render_plan.zoom,
            qpane_rect=render_plan.qpane_rect,
            source_image=base_item.source_image,
            transform=base_item.transform,
            current_pan=render_plan.current_pan,
            physical_viewport_rect=render_plan.physical_viewport_rect,
        )

    def _draw_scene_overlays(
        self,
        painter: QPainter,
        render_plan: SceneRenderPlan | None,
        scene_overlays: Mapping[str, SceneOverlayDrawFn],
        *,
        overlays_suspended: bool,
    ) -> None:
        """Draw public scene overlays from rendered scene-layer geometry."""
        if render_plan is None or overlays_suspended or not scene_overlays:
            return
        overlay_state = self._build_scene_overlay_state(render_plan)
        if overlay_state is None:
            return
        for draw_overlay in scene_overlays.values():
            draw_overlay(painter, overlay_state)

    def _build_scene_overlay_state(
        self, render_plan: SceneRenderPlan
    ) -> QPaneSceneOverlayState | None:
        """Project a render plan onto the public scene-overlay surface."""
        scene_getter = getattr(self._qpane, "currentScene", None)
        if not callable(scene_getter):
            return None
        scene = scene_getter()
        if scene is None or scene.scene_id != render_plan.scene_id:
            return None
        layers_by_id = {layer.layer_id: layer for layer in scene.layers}
        layers: list[QPaneSceneOverlayLayer] = []
        for item in render_plan.render_items:
            if not isinstance(item, RasterLayerRenderItem):
                continue
            public_layer = layers_by_id.get(item.descriptor.layer_id)
            if public_layer is None:
                continue
            source_size = item.source_image.size()
            source_rect = QRectF(
                0.0,
                0.0,
                float(source_size.width()),
                float(source_size.height()),
            )
            layers.append(
                QPaneSceneOverlayLayer(
                    layer_id=public_layer.layer_id,
                    image_id=public_layer.image_id,
                    role=public_layer.role,
                    metadata=public_layer.metadata,
                    placement=QRectF(public_layer.placement),
                    source_size=source_size,
                    transform=item.transform,
                    panel_bounds=item.transform.mapRect(source_rect),
                    visible=item.descriptor.visible,
                )
            )
        if not layers:
            return None
        return QPaneSceneOverlayState(
            zoom=render_plan.zoom,
            qpane_rect=render_plan.qpane_rect,
            physical_viewport_rect=render_plan.physical_viewport_rect,
            composition_id=scene.composition_id,
            scene_id=render_plan.scene_id,
            scene_bounds=QRectF(
                render_plan.scene_bounds.x,
                render_plan.scene_bounds.y,
                render_plan.scene_bounds.width,
                render_plan.scene_bounds.height,
            ),
            layers=tuple(layers),
        )

    def mark_dirty(self, dirty_rect: QRect | QRectF | None = None) -> None:
        """Forward dirty-region notifications to the renderer."""
        self.renderer.markDirty(dirty_rect)

    def _handle_vector_refinement_ready(self) -> None:
        """Publish one atomic refined tile batch on the GUI thread."""
        self.renderer.markDirty()
        self._qpane.update()

    def handle_viewport_changed(self) -> bool:
        """Handle a viewport change with scroll reuse when only pan changed."""
        compiled = self._scene_compiler.compiled_scene()
        if compiled is None:
            self._last_scroll_reuse_signature = None
            return False
        previous_plan = self.renderer.get_current_render_plan()
        if previous_plan is None:
            return False
        if not isclose(
            previous_plan.zoom,
            self.viewport.zoom,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            return False
        current_signature = self._scroll_reuse_signature_for_plan(previous_plan)
        if current_signature != self._last_scroll_reuse_signature:
            return False
        if self.renderer.get_base_buffer() is None:
            return False
        candidate_plan = self.calculateRenderPlan(
            use_pan=QPointF(self.viewport.pan),
            is_blank=False,
        )
        candidate_signature = self._scroll_reuse_signature_for_plan(candidate_plan)
        if candidate_signature != self._last_scroll_reuse_signature:
            return False
        result = self.renderer.tryScrollBuffers(
            QPointF(self.viewport.pan),
            repair_plan=candidate_plan,
        )
        return result

    def allocate_buffers(self) -> None:
        """Allocate the renderer buffers to match the current widget size."""
        self._refresh_backing_buffers()

    def ensure_view_alignment(self, *, force: bool = False) -> None:
        """Reapply FIT/custom zoom and buffers when the qpane geometry changes."""
        current_size = self._qpane.size()
        current_dpr = float(self._qpane.devicePixelRatioF())
        dpr_changed = not isclose(
            current_dpr, self._last_device_pixel_ratio, rel_tol=1e-9, abs_tol=1e-9
        )
        if not force and current_size == self._last_view_size and not dpr_changed:
            return
        zoom_mode = self.viewport.get_zoom_mode()
        if zoom_mode == ViewportZoomMode.FIT:
            self.viewport.setZoomFit()
        else:
            self.viewport.setPan(self.viewport.pan)
        self.allocate_buffers()
        self._last_view_size = QSize(current_size)
        self._last_device_pixel_ratio = current_dpr

    def physical_viewport_rect(self) -> QRectF:
        """Return the viewport rectangle expressed in device pixels."""
        context = CoordinateContext(self._qpane)
        return context.logical_to_physical(QRectF(self._qpane.rect()))

    def panel_to_image_point(self, panel_pos: QPoint) -> QPoint | None:
        """Convert a panel coordinate into image space using the viewport."""
        return self.viewport.panel_to_content_point(panel_pos)

    def panel_hit_test(self, panel_pos: QPoint) -> PanelHitTest | None:
        """Return hit-test metadata for panel coordinates via the viewport."""
        return self.viewport.panel_hit_test(panel_pos)

    def scene_hit_test(self, panel_pos: QPoint) -> SceneLayerHitTestResult | None:
        """Return the top scene layer under ``panel_pos`` when one matches."""
        plan = self.calculateRenderPlan(
            is_blank=getattr(self._qpane, "_is_blank", False)
        )
        if plan is None:
            return None
        panel_point = QPointF(panel_pos)
        for item in reversed(plan.render_items):
            result = self._scene_hit_tester.hit_test(plan, item, panel_point)
            if result is not None:
                return result
        return None

    def scene_selection_hit_test(
        self, panel_pos: QPoint | QPointF
    ) -> SceneLayerHitTestResult | None:
        """Return the top selectable layer with source coverage under a panel point."""
        plan = self.calculateRenderPlan(
            is_blank=getattr(self._qpane, "_is_blank", False)
        )
        if plan is None:
            return None
        panel_point = QPointF(panel_pos)
        for item in reversed(plan.render_items):
            if not item.descriptor.interaction.selectable:
                continue
            result = self._scene_hit_tester.hit_test(plan, item, panel_point)
            if result is not None and self._source_hit_tests.contains(
                result.source,
                result.source_point,
            ):
                return result
        return None

    def panel_to_scene_point(self, panel_pos: QPoint | QPointF) -> QPointF | None:
        """Project a panel point into the active scene coordinate system."""
        geometry = self._active_scene_geometry()
        if geometry is None:
            return None
        compiled, frame = geometry
        transform = self._scene_to_panel_transform(compiled, frame)
        inverse, invertible = transform.inverted()
        if not invertible:
            return None
        local = inverse.map(QPointF(panel_pos))
        return QPointF(
            local.x() + compiled.scene.bounds.x,
            local.y() + compiled.scene.bounds.y,
        )

    def scene_to_panel_transform(self) -> QTransform | None:
        """Return a transform mapping absolute scene coordinates into the panel."""
        geometry = self._active_scene_geometry()
        if geometry is None:
            return None
        compiled, frame = geometry
        local_to_panel = self._scene_to_panel_transform(compiled, frame)
        origin = local_to_panel.map(QPointF())
        x_axis = local_to_panel.map(QPointF(1.0, 0.0))
        y_axis = local_to_panel.map(QPointF(0.0, 1.0))
        x_scale_x = x_axis.x() - origin.x()
        x_scale_y = x_axis.y() - origin.y()
        y_scale_x = y_axis.x() - origin.x()
        y_scale_y = y_axis.y() - origin.y()
        scene_bounds = compiled.scene.bounds
        return QTransform(
            x_scale_x,
            x_scale_y,
            y_scale_x,
            y_scale_y,
            origin.x() - scene_bounds.x * x_scale_x - scene_bounds.y * y_scale_x,
            origin.y() - scene_bounds.x * x_scale_y - scene_bounds.y * y_scale_y,
        )

    def panel_to_layer_source_point(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        panel_pos: QPoint | QPointF,
    ) -> QPointF | None:
        """Project a panel point into one layer's authoritative source space."""
        geometry = self._layer_coordinate_geometry(scene_id, layer_id)
        if geometry is None:
            return None
        compiled, frame, layer = geometry
        panel_transform = self._scene_to_panel_transform(compiled, frame)
        inverse_panel, invertible = panel_transform.inverted()
        if not invertible or layer.transform is None:
            return None
        scene_point = inverse_panel.map(QPointF(panel_pos))
        scene_point += QPointF(compiled.scene.bounds.x, compiled.scene.bounds.y)
        local_point = layer.transform.inverse_map(scene_point)
        if local_point is None:
            return None
        raster_bounds = layer.raster_bounds
        if raster_bounds is None:
            return local_point
        return QPointF(
            local_point.x() - raster_bounds.x,
            local_point.y() - raster_bounds.y,
        )

    def layer_source_to_panel_point(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        source_point: QPoint | QPointF,
    ) -> QPointF | None:
        """Project authoritative layer-source coordinates into the panel."""
        geometry = self._layer_coordinate_geometry(scene_id, layer_id)
        if geometry is None:
            return None
        compiled, frame, layer = geometry
        if layer.transform is None:
            return None
        local_point = QPointF(source_point)
        raster_bounds = layer.raster_bounds
        if raster_bounds is not None:
            local_point += QPointF(raster_bounds.x, raster_bounds.y)
        scene_point = layer.transform.map_point(local_point)
        scene_local_point = scene_point - QPointF(
            compiled.scene.bounds.x,
            compiled.scene.bounds.y,
        )
        return self._scene_to_panel_transform(compiled, frame).map(scene_local_point)

    def image_to_panel_point(self, image_point: QPoint) -> QPointF | None:
        """Project an image-space coordinate into the widget."""
        return self.viewport.content_to_panel_point(image_point)

    def handle_resize(self) -> None:
        """Respond to QWidget resize events."""
        if self.viewport.get_zoom_mode() == ViewportZoomMode.FIT:
            self._handle_resize_fit_mode()
        else:
            self._handle_resize_custom_mode()
        self.allocate_buffers()

    def minimum_size_hint(self) -> QSize:
        """Return the safe minimum widget size for the current image."""
        content_snapshot = self.current_content_snapshot()
        if content_snapshot is None:
            base_hint = QWidget.minimumSizeHint(self._qpane)
            if base_hint.isValid() and not base_hint.isNull():
                return base_hint
            return QSize(1, 1)
        safe_min_zoom = getattr(self._qpane.settings, "safe_min_zoom", 1e-3)
        min_zoom = max(self.viewport.min_zoom(), safe_min_zoom)
        base_size = content_snapshot.base_image_size
        min_width = max(1, round(base_size.width() * min_zoom))
        min_height = max(1, round(base_size.height() * min_zoom))
        return QSize(min_width, min_height)

    def current_content_snapshot(self) -> SceneContentSnapshot | None:
        """Return geometry for the current rendered content when available."""
        compiled = self._scene_compiler.compiled_scene()
        return compiled.content_snapshot if compiled is not None else None

    def current_scene_descriptor(self) -> SceneDescriptor | None:
        """Return the active scene descriptor without building render items."""
        compiled = self._scene_compiler.compiled_scene()
        return compiled.scene if compiled is not None else None

    def coordinate_scene_descriptor(self) -> SceneDescriptor | None:
        """Return scene geometry already resolved for the active input frame."""
        compiled = (
            self._scene_compiler.cached_scene() or self._scene_compiler.compiled_scene()
        )
        return compiled.scene if compiled is not None else None

    def invalidate_content_cache(self) -> None:
        """Drop cached active scene/content geometry."""
        self._scene_compiler.invalidate()
        self._last_scroll_reuse_signature = None

    def has_renderable_content(self) -> bool:
        """Return True when the presenter can resolve content for rendering."""
        return self.current_content_snapshot() is not None

    def content_rect(self) -> QRect:
        """Return the current base content rectangle in content coordinates."""
        snapshot = self.current_content_snapshot()
        if snapshot is None:
            return QRect()
        return QRect(QPoint(0, 0), snapshot.base_image_size)

    def _qpane_physical_size(self) -> QSize:
        """Return the qpane's current size expressed in device pixels."""
        context = CoordinateContext(self._qpane)
        logical_size = QSizeF(self._qpane.size())
        return context.logical_to_physical(logical_size).toSize()

    def _refresh_backing_buffers(self) -> None:
        """Rebuild renderer buffers based on the current widget DPR and size."""
        physical_size = self._qpane_physical_size()
        dpr = self._qpane.devicePixelRatioF()
        self.renderer.allocate_buffers(physical_size, dpr)
        self._last_scroll_reuse_signature = None

    def _ensure_buffer_matches_widget(self) -> None:
        """Reallocate renderer buffers when the widget size has changed."""
        base_buffer = self.renderer.get_base_buffer()
        if base_buffer is None:
            self.allocate_buffers()
            return
        expected_size = self._qpane_physical_size()
        if not self.renderer.buffer_matches_viewport(
            expected_size,
            float(self._qpane.devicePixelRatioF()),
        ):
            self.allocate_buffers()

    @staticmethod
    def _scroll_reuse_signature_for_plan(
        plan: SceneRenderPlan | None,
    ) -> tuple[object, ...] | None:
        """Return static render-plan inputs that must stay stable for scroll reuse."""
        if not isinstance(plan, SceneRenderPlan):
            return None
        image_items = tuple(
            (
                item.descriptor.layer_id,
                item.descriptor.kind,
                item.descriptor.visible,
                item.descriptor.opacity,
                item.descriptor.blend_mode,
                item.descriptor.placement,
                item.descriptor.clip,
                item.descriptor.effects,
                item.descriptor.source,
                item.descriptor.source_revision,
                item.asset_key,
                item.pyramid_asset_key,
                item.source_image.cacheKey(),
                item.pyramid_scale,
                item.strategy,
                item.render_hint_enabled,
                item.tile_size,
                item.tile_overlap,
                item.max_tile_cols,
                item.max_tile_rows,
                item.visible_tile_range,
                tuple(
                    (tile.draw_pos, tile.image.cacheKey())
                    for tile in item.tiles_to_draw
                ),
                item.debug_draw_tile_grid,
                item.effect_clip_path,
            )
            for item in plan.render_items
            if isinstance(item, RasterLayerRenderItem)
        )
        vector_items = tuple(
            (
                item.descriptor.layer_id,
                item.descriptor.visible,
                item.descriptor.opacity,
                item.descriptor.placement,
                item.descriptor.clip,
                item.descriptor.effects,
                item.descriptor.source,
                item.descriptor.source_revision,
                item.source_size,
                item.effect_clip_path,
                tuple(
                    (
                        tile.image.cacheKey(),
                        tile.source_rect,
                        tile.image_source_rect,
                    )
                    for tile in item.refined_tiles
                ),
            )
            for item in plan.render_items
            if isinstance(item, VectorLayerRenderItem)
        )
        return (
            plan.scene_id,
            plan.scene_bounds,
            plan.content_bounds,
            image_items,
            vector_items,
            plan.zoom,
            plan.qpane_rect,
            plan.physical_viewport_rect,
        )

    # Internal helpers

    def get_tile_draw_position(self, key: SceneLayerTileKey) -> QPointF:
        """Return the upper-left draw position for ``key`` in source coords."""
        return self._raster_planner.tile_draw_position(key)

    def dirty_rect_for_tile_key(self, key: SceneLayerTileKey) -> QRect | None:
        """Return the panel dirty rect for a visible ready tile."""
        if getattr(self._qpane, "_is_blank", False):
            return None
        compiled = self._scene_compiler.compiled_scene()
        if compiled is None:
            return None
        return self._raster_planner.dirty_rect_for_tile_key(
            key,
            compiled=compiled,
            frame=self._frame_geometry_for(compiled, use_pan=None),
        )

    def _handle_resize_fit_mode(self) -> None:
        """Keep the viewport zoom aligned with the available widget size in FIT mode."""
        self.viewport.setZoomFit()

    def _handle_resize_custom_mode(self) -> None:
        """Reapply the current pan so it is clamped after a custom-mode resize."""
        self.viewport.setPan(self.viewport.pan)

    def _frame_geometry_for(
        self,
        compiled: CompiledRenderScene,
        *,
        use_pan: QPointF | None,
    ) -> RenderFrameGeometry:
        """Return viewport-dependent geometry for one render-planning frame."""
        current_pan = use_pan if use_pan is not None else self.viewport.pan
        physical_viewport_rect = self.physical_viewport_rect()
        return RenderFrameGeometry(
            content_snapshot=compiled.content_snapshot,
            zoom=self.viewport.zoom,
            native_zoom=self.viewport.nativeZoom(),
            current_pan=current_pan,
            qpane_rect=self._qpane.rect(),
            physical_viewport_rect=physical_viewport_rect,
            visible_scene_rect=visible_scene_rect(
                scene=compiled.scene,
                zoom=self.viewport.zoom,
                current_pan=current_pan,
                physical_viewport_rect=physical_viewport_rect,
            ),
            debug_draw_tile_grid=self._qpane.settings.draw_tile_grid,
            tile_size=self.tile_manager.tile_size,
            tile_overlap=self.tile_manager.tile_overlap,
        )

    def _active_scene_geometry(
        self,
    ) -> tuple[CompiledRenderScene, RenderFrameGeometry] | None:
        """Resolve current scene geometry without resolving render-source pixels."""
        if getattr(self._qpane, "_is_blank", False):
            return None
        compiled = (
            self._scene_compiler.cached_scene() or self._scene_compiler.compiled_scene()
        )
        if compiled is None:
            return None
        return compiled, self._frame_geometry_for(compiled, use_pan=None)

    def _layer_coordinate_geometry(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> tuple[CompiledRenderScene, RenderFrameGeometry, LayerDescriptor] | None:
        """Resolve one layer and its current viewport geometry without raster work."""
        geometry = self._active_scene_geometry()
        if geometry is None:
            return None
        compiled, frame = geometry
        if compiled.scene.scene_id != scene_id:
            return None
        layer = next(
            (item for item in compiled.scene.layers if item.layer_id == layer_id), None
        )
        if layer is None:
            return None
        return compiled, frame, layer

    def _scene_to_panel_transform(
        self,
        compiled: CompiledRenderScene,
        frame: RenderFrameGeometry,
    ) -> QTransform:
        """Return the authoritative scene-local to panel transform for one frame."""
        return self._frame_projector.scene_to_panel(compiled.scene, frame)
