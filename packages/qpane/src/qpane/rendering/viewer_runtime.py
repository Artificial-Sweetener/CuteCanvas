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
"""Rendering lifecycle owner behind the standalone QPane widget facade."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping

from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, QSize, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget

from ..core import Config, OverlayDrawFn, SceneOverlayDrawFn
from ..execution import ExecutionScope
from ..scene.effects import LayerEffectRenderRegistry
from ..scene.identity import SceneLayerTileKey, SourceRenderAssetKey
from ..scene.model import LayerClip
from ..scene.presentation_effects import (
    LayerPresentationEffect,
    LayerPresentationStyle,
)
from ..scene.render_plan import SceneRenderPlan
from ..scene.source_capabilities import LayerSourceCapabilities
from .coordinates import PanelHitTest
from .presenter import RenderingPresenter
from .pyramid import PyramidManager
from .sdk import RasterSource, RenderScene
from .sdk_adapter import RenderSceneController
from .viewport import Viewport


class ViewerRenderingRuntime(QObject):
    """Own scene adaptation, render products, invalidation, and frame painting."""

    sceneChanged = Signal(object)
    """Emit the accepted immutable scene or ``None``."""
    zoomChanged = Signal(float)
    """Emit effective viewport zoom after navigation."""
    diagnosticsDirty = Signal()
    """Request refresh of render and cache diagnostic rows."""

    def __init__(
        self,
        pane: QWidget,
        config: Config,
        execution_scope: ExecutionScope,
    ) -> None:
        """Assemble QPane's sole scene compiler and renderer collaboration."""
        super().__init__(pane)
        self._pane = pane
        self._execution_scope = execution_scope.open_child(
            f"{execution_scope.owner_id}:rendering"
        )
        self._sources = LayerSourceCapabilities.create()
        self._scenes = RenderSceneController(self._sources)
        self._pyramids = PyramidManager(
            config,
            parent=self,
            execution_scope=self._execution_scope,
        )
        self._presenter = RenderingPresenter(
            qpane=pane,
            pyramid_products=self._pyramids,
            cache_registry=None,
            execution_scope=self._execution_scope,
            scene_provider=self._scenes.scene_descriptor,
            scene_revision=self._scenes.revision,
            source_metadata=self._sources.metadata,
            raster_sources=self._sources.rasters,
            raster_patches=self._sources.raster_patches,
            source_hit_tests=self._sources.hit_tests,
            vector_sources=self._sources.vectors,
            hybrid_sources=self._sources.hybrids,
            sampled_sources=self._sources.sampled,
            layer_effects=LayerEffectRenderRegistry(),
        )
        self._blank = True
        self.viewport.viewChanged.connect(self._viewport_changed)
        self._pyramids.pyramidReady.connect(self._pyramid_ready)
        self._presenter.tile_manager.tileReady.connect(self._tile_ready)

    @property
    def presenter(self) -> RenderingPresenter:
        """Return the focused frame presenter for diagnostics."""
        return self._presenter

    @property
    def pyramids(self) -> PyramidManager:
        """Return the shared raster pyramid product owner."""
        return self._pyramids

    @property
    def viewport(self) -> Viewport:
        """Return the authoritative viewport transform owner."""
        return self._presenter.viewport

    @property
    def is_blank(self) -> bool:
        """Return whether no render scene is active."""
        return self._blank

    @property
    def scene(self) -> RenderScene | None:
        """Return the immutable scene accepted by the SDK adapter."""
        return self._scenes.scene

    def add_layer_presentation_effect(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        style: LayerPresentationStyle,
        *,
        effect_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        """Register one transient effect against an active rendered layer."""
        return self._presenter.add_layer_presentation_effect(
            scene_id,
            layer_id,
            style,
            effect_id=effect_id,
        )

    def update_layer_presentation_effect(
        self,
        effect_id: uuid.UUID,
        style: LayerPresentationStyle,
    ) -> bool:
        """Replace one registered effect style while preserving its order."""
        return self._presenter.update_layer_presentation_effect(effect_id, style)

    def remove_layer_presentation_effect(self, effect_id: uuid.UUID) -> bool:
        """Remove one registered transient effect when present."""
        return self._presenter.remove_layer_presentation_effect(effect_id)

    def clear_layer_presentation_effects(
        self,
        *,
        scene_id: uuid.UUID | None = None,
        layer_id: uuid.UUID | None = None,
    ) -> int:
        """Remove matching transient effects and return the removal count."""
        return self._presenter.clear_layer_presentation_effects(
            scene_id=scene_id,
            layer_id=layer_id,
        )

    def layer_presentation_effects(self) -> tuple[LayerPresentationEffect, ...]:
        """Return every registered transient effect in deterministic order."""
        return self._presenter.layer_presentation_effects()

    def set_layer_presentation_clip(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        clip: LayerClip,
    ) -> bool:
        """Set one transient layer clip without replacing durable scene content."""
        return self._presenter.set_layer_presentation_clip(
            scene_id,
            layer_id,
            clip,
        )

    def set_scene(self, scene: RenderScene | None, *, fit: bool) -> bool:
        """Replace the scene, synchronize viewport geometry, and repaint."""
        changed = self._scenes.set_scene(scene)
        if not changed:
            return False
        self._presenter.reconcile_layer_presentation_clips(
            None if scene is None else scene.scene_id,
            () if scene is None else tuple(layer.layer_id for layer in scene.layers),
        )
        self._blank = scene is None
        self._presenter.invalidate_content_cache()
        self._presenter.mark_dirty()
        if scene is None:
            self.viewport.setContentSize(QSize())
        else:
            self.viewport.setContentSize(scene.canvas.size().toSize())
            if fit:
                self.viewport.setZoomFit()
        self._pane.update()
        self.sceneChanged.emit(scene)
        self.diagnosticsDirty.emit()
        return True

    def apply_config(self, config: Config) -> None:
        """Apply validated renderer and viewport configuration."""
        self._presenter.apply_config(config)
        self._pyramids.apply_config(config)
        self._presenter.mark_dirty()
        self._pane.update()
        self.diagnosticsDirty.emit()

    def validate_config(self, config: Config) -> None:
        """Validate renderer settings before the widget publishes a snapshot."""
        self._presenter.validate_config(config)

    def calculate_plan(
        self,
        *,
        use_pan: QPointF | None = None,
    ) -> SceneRenderPlan | None:
        """Return the current compiled frame plan."""
        return self._presenter.calculateRenderPlan(
            use_pan=use_pan,
            is_blank=self._blank,
        )

    def paint(
        self,
        *,
        content_overlays: Mapping[str, OverlayDrawFn],
        scene_overlays: Mapping[str, SceneOverlayDrawFn],
        draw_tool_overlay: Callable[[QPainter], None],
    ) -> None:
        """Paint one frame and every registered transient contribution."""
        self._presenter.ensure_view_alignment()
        self._presenter.paint(
            is_blank=self._blank,
            content_overlays=content_overlays,
            scene_overlays=scene_overlays,
            overlays_suspended=False,
            draw_tool_overlay=draw_tool_overlay,
        )

    def resize(self) -> None:
        """Realign physical viewport and renderer buffers after widget resize."""
        self._presenter.handle_resize()
        self._presenter.ensure_view_alignment(force=True)
        self._pane.update()

    def physical_viewport_rect(self) -> QRectF:
        """Return current physical panel geometry."""
        return self._presenter.physical_viewport_rect()

    def panel_hit_test(self, point: QPoint | QPointF) -> PanelHitTest | None:
        """Project one logical widget point through active scene geometry."""
        return self._presenter.panel_hit_test(QPointF(point).toPoint())

    def minimum_size_hint(self) -> QSize:
        """Return the renderer's configured widget minimum."""
        return self._presenter.minimum_size_hint()

    def shutdown(self) -> None:
        """Stop presenter and derived-product work without waiting on Qt."""
        self._presenter.shutdown()
        self._pyramids.shutdown(wait=False)
        self._execution_scope.close(reason="viewer_rendering_shutdown")

    def discard_sources(self, sources: tuple[RasterSource, ...]) -> None:
        """Discard raster products for resources removed from viewer ownership."""
        for source in sources:
            asset_key = SourceRenderAssetKey(
                source_id=source.source_id,
                source_kind=source.source_kind,
                source_revision=source.revision,
                source_path=source.path,
            )
            self._presenter.tile_manager.remove_tiles_for_source_asset(asset_key)
            self._pyramids.remove_pyramid(asset_key)
        self._presenter.mark_dirty()
        self.diagnosticsDirty.emit()

    def _viewport_changed(self) -> None:
        """Reuse scroll buffers, invalidate when needed, and publish zoom."""
        if not self._presenter.handle_viewport_changed():
            self._presenter.mark_dirty()
        self._pane.update()
        self.diagnosticsDirty.emit()
        self.zoomChanged.emit(float(self.viewport.zoom))

    def _pyramid_ready(self, _asset_key: SourceRenderAssetKey) -> None:
        """Invalidate the frame after a requested source pyramid completes."""
        if self._presenter.note_navigation_full_product_ready():
            return
        self._presenter.invalidate_frame_plan()
        self._presenter.mark_dirty()
        self._pane.update()
        self.diagnosticsDirty.emit()

    def _tile_ready(self, key: SceneLayerTileKey) -> None:
        """Invalidate only the region covered by one completed tile."""
        if self._presenter.note_navigation_raster_tile_ready(key):
            return
        self._presenter.invalidate_frame_plan()
        dirty_rect = self._presenter.dirty_rect_for_tile_key(key)
        if dirty_rect is not None:
            self._presenter.mark_dirty(dirty_rect)
            self._pane.update()
        self.diagnosticsDirty.emit()
