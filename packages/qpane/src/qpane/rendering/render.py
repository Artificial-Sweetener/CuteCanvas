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

"""Rendering pipeline and metrics helpers for the QPane viewer."""

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from math import isclose
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPainter, QRegion, QTransform

from ..scene.render_plan import (
    RasterLayerRenderItem,
    RenderStrategy,
    SceneRenderItem,
    SceneRenderPlan,
)
from .coordinates import CoordinateContext
from .frame_buffer_presenter import FrameBufferPresenter
from .frame_patch_painter import FramePatchPainter
from .incremental_frame import IncrementalFrameMetrics, IncrementalFrameRefiner
from .item_compositor import SceneItemCompositor
from .navigation_buffer import navigation_buffer_transform
from .navigation_plan import (
    navigation_products_match,
    retained_raster_navigation_delta,
)
from .navigation_reuse_policy import requires_linear_scroll_storage
from .transient_raster import TransientRasterHandoff
from .transient_raster_damage import transient_raster_transition_damage
from .widget_surface import WidgetRenderSurface

if TYPE_CHECKING:
    from ..execution import ExecutionScope
    from ..viewer import QPane


@dataclass(frozen=True)
class RendererMetrics:
    """Runtime counters describing renderer buffer reuse behaviour."""

    base_buffer_allocations: int
    scroll_attempts: int
    scroll_hits: int
    scroll_misses: int
    scroll_repairs: int
    full_redraws: int
    partial_redraws: int
    last_paint_ms: float


class Renderer:
    """Own the offscreen buffers plus reuse heuristics for the QPane widget."""

    _COMPOSITING_PATCH_PHYSICAL_PX = 512
    _BUFFER_OVERSCAN_PHYSICAL_PX = 64
    _LARGE_VIEWPORT_GUARD_PHYSICAL_PX = 512
    _FOUR_K_VIEWPORT_GUARD_PHYSICAL_PX = 1024
    _NAVIGATION_RECENTER_GUARD_FRACTION = 0.5
    _SCROLL_REPAIR_BLEED_PHYSICAL_PX = 8
    _OPAQUE_IMAGE_CACHE_LIMIT = 64
    _OPAQUE_PRESENTATION_EDGE_GUARD_LOGICAL_PX = 2

    def __init__(
        self,
        qpane: "QPane",
        *,
        execution_scope: "ExecutionScope | None" = None,
    ):
        """Bind rendering to `qpane` while tracking buffer reuse health."""
        self._qpane = qpane
        self._current_render_plan: SceneRenderPlan | None = None
        self._buffer_render_plan: SceneRenderPlan | None = None
        self._surface = WidgetRenderSurface()
        self._dirty_region = QRegion()
        self._buffer_pan = QPointF(0, 0)
        self._subpixel_pan_offset = QPointF(0, 0)
        self._buffer_overscan_physical_px = self._BUFFER_OVERSCAN_PHYSICAL_PX
        self._buffer_guard_valid = False
        self._buffer_valid_region = QRegion()
        self._presentation_transform = QTransform()
        self._viewport_physical_size = QSize()
        self._last_paint_duration_ms = 0.0
        self._paint_duration_sum_ms = 0.0
        self._paint_duration_count = 0
        self._paint_duration_max_ms = 0.0
        self._base_buffer_allocations = 0
        self._scroll_attempts = 0
        self._scroll_hits = 0
        self._scroll_misses = 0
        self._scroll_repairs = 0
        self._full_redraws = 0
        self._partial_redraws = 0
        self._transient_raster_handoff = TransientRasterHandoff()
        self._items = SceneItemCompositor()
        self._frame_presenter = FrameBufferPresenter()
        self._patch_painter = FramePatchPainter(
            qpane,
            lambda: self._buffer_overscan_physical_px,
        )
        self._navigation_refiner = IncrementalFrameRefiner(
            parent=qpane if isinstance(qpane, QObject) else None,
            execution_scope=execution_scope,
            prepare=self._surface.prepare_staging,
            discard=self._surface.discard_staging,
            transfer_patch=self._surface.transfer_staging_patch,
            publish=self._publish_navigation_refinement,
            failed=self._navigation_refinement_failed,
        )
        self._opaque_image_cache: OrderedDict[int, bool] = OrderedDict()

    @property
    def qpane(self) -> "QPane":
        """Return the QPane associated with this renderer."""
        return self._qpane

    def paint(self, plan: SceneRenderPlan):
        """Prepare offscreen buffers for the requested scene without drawing to the widget."""
        start_time = time.perf_counter()
        plan, requires_full_redraw = self._transient_raster_handoff.settled_plan(plan)
        if requires_full_redraw:
            self.markDirty()
        transient_damage = transient_raster_transition_damage(
            self._current_render_plan,
            plan,
        )
        if transient_damage is not None:
            self.markDirty(transient_damage)
        self._current_render_plan = plan
        # Ensure buffers are allocated. The QPane is responsible for calling
        # _allocate_buffers on resize, but we need to handle the initial case.
        if not self._surface.is_allocated:
            self.markDirty(plan.qpane_rect)  # Mark entire view dirty for first paint
        # Redraw dirty buffers if any region has been marked as dirty.
        if not self._dirty_region.isEmpty():
            # Pass the entire region object and plan to the redraw methods.
            self._redraw_base_image_buffer(self._dirty_region, plan)
        # Clear the dirty region now that buffer painting is complete for this frame.
        self._dirty_region = QRegion()
        end_time = time.perf_counter()
        self._last_paint_duration_ms = (end_time - start_time) * 1000
        if self._last_paint_duration_ms > 0.0:
            self._paint_duration_sum_ms += self._last_paint_duration_ms
            self._paint_duration_count += 1
            self._paint_duration_max_ms = max(
                self._paint_duration_max_ms, self._last_paint_duration_ms
            )

        self._mark_diagnostics_dirty()

    def allocate_buffers(self, physical_size: QSize, dpr: float):
        """Allocate and clear the base buffer sized to the physical viewport."""
        self._navigation_refiner.cancel()
        self._viewport_physical_size = QSize(physical_size)
        self._buffer_overscan_physical_px = self._overscan_for_viewport(physical_size)
        self._surface.allocate(
            self._overscanned_buffer_size(physical_size),
            dpr,
        )
        self._buffer_guard_valid = False
        self._buffer_valid_region = QRegion()
        self._presentation_transform.reset()
        self._buffer_render_plan = None
        self._base_buffer_allocations += 1
        # Mark the entire view as dirty since the buffers are new.
        self.markDirty()

    def buffer_matches_viewport(self, physical_size: QSize, dpr: float) -> bool:
        """Return True when the allocated backing store matches the viewport."""
        return self._viewport_physical_size == physical_size and self._surface.matches(
            self._overscanned_buffer_size(physical_size),
            dpr,
        )

    def markDirty(self, dirty_rect: QRect | QRectF | QRegion | None = None):
        """Mark a region dirty for the next render pass; None targets the full viewport."""
        self._navigation_refiner.cancel()
        if dirty_rect is None:
            self._dirty_region += QRect(-100000, -100000, 200000, 200000)
            return
        if isinstance(dirty_rect, QRegion):
            if not dirty_rect.isEmpty():
                self._dirty_region += QRegion(dirty_rect)
            return
        if isinstance(dirty_rect, QRectF):
            dirty_rect = dirty_rect.toAlignedRect()
        if isinstance(dirty_rect, QRect):
            if dirty_rect.isEmpty():
                return
            self._dirty_region += dirty_rect
            return
        raise TypeError(f"Unsupported dirty input: {type(dirty_rect)!r}")

    def item_panel_bounds(self, item: SceneRenderItem) -> QRect:
        """Return conservative panel damage bounds for one resolved primitive."""
        return self._items.item_panel_bounds(item)

    def has_scroll_buffer_overlap(self, new_pan: QPointF) -> bool:
        """Return whether the current buffer overlaps the requested pan position."""
        if not self._surface.is_allocated:
            return False
        buffer = self._surface.pixmap
        delta = new_pan - self._buffer_pan
        return abs(delta.x()) < buffer.width() and abs(delta.y()) < buffer.height()

    def has_guard_coverage(self, new_pan: QPointF) -> bool:
        """Return whether settled guard pixels cover a requested pan."""

        if (
            not self._surface.is_allocated
            or not self._buffer_guard_valid
            or not self._presentation_transform.isIdentity()
        ):
            return False
        delta = QPointF(new_pan) - self._buffer_pan
        guard = self._buffer_overscan_physical_px
        return (
            abs(delta.x()) <= guard
            and abs(delta.y()) <= guard
            and self._visible_buffer_crop_is_valid(
                QPoint(round(delta.x()), round(delta.y()))
            )
        )

    def tryPresentGuardedPan(self, plan: SceneRenderPlan) -> bool:
        """Present an exact pan directly from already-rendered guard pixels."""
        self._navigation_refiner.cancel()
        buffer_plan = self._buffer_render_plan
        if (
            buffer_plan is None
            or not self._surface.is_allocated
            or not self._buffer_guard_valid
            or not self._presentation_transform.isIdentity()
            or not isclose(
                buffer_plan.zoom,
                plan.zoom,
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
            or not navigation_products_match(buffer_plan, plan)
        ):
            return False
        physical_delta = retained_raster_navigation_delta(
            buffer_plan,
            plan,
            device_pixel_ratio=self._surface.pixmap.devicePixelRatio(),
        )
        if physical_delta is None:
            return False
        recenter_distance = max(
            1,
            round(
                self._buffer_overscan_physical_px
                * self._NAVIGATION_RECENTER_GUARD_FRACTION
            ),
        )
        if (
            abs(physical_delta.x()) > recenter_distance
            or abs(physical_delta.y()) > recenter_distance
        ):
            return False
        if not self._visible_buffer_crop_is_valid(physical_delta):
            return False
        self._subpixel_pan_offset = self._canonical_subpixel_offset(physical_delta)
        self._current_render_plan = plan
        self._dirty_region = QRegion()
        self._scroll_hits += 1
        self.qpane.update()
        self._mark_diagnostics_dirty()
        return True

    def settle_equivalent_navigation_presentation(
        self,
        refined_plan: SceneRenderPlan,
    ) -> bool:
        """Restore exact buffer cropping when transformed zoom returns to its scale."""
        current = self._current_render_plan
        settled = self._buffer_render_plan
        if (
            current is None
            or settled is None
            or not self._surface.is_allocated
            or not self._buffer_guard_valid
            or not isclose(
                current.zoom,
                settled.zoom,
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
            or not navigation_products_match(settled, refined_plan)
        ):
            return False
        delta = current.current_pan - self._buffer_pan
        guard = self._buffer_overscan_physical_px
        if abs(delta.x()) > guard or abs(delta.y()) > guard:
            return False
        physical_delta = retained_raster_navigation_delta(
            settled,
            refined_plan,
            device_pixel_ratio=self._surface.pixmap.devicePixelRatio(),
        )
        if physical_delta is None:
            return False
        self._presentation_transform.reset()
        self._subpixel_pan_offset = QPointF(physical_delta)
        return True

    def tryScrollBuffers(
        self,
        new_pan: QPointF,
        *,
        repair_plan: SceneRenderPlan | None = None,
    ) -> bool:
        """Attempts to reuse the existing buffer by scrolling and repairing edge strips."""
        self._navigation_refiner.cancel()
        if not self._surface.is_allocated:
            return False
        self._scroll_attempts += 1
        surface = self._surface.pixmap
        qpane_view = getattr(self.qpane, "view", None)
        view = qpane_view() if callable(qpane_view) else None
        plan_calculate = getattr(view, "calculateRenderPlan", None)
        if not callable(plan_calculate):
            raise AttributeError(  # noqa: TRY004 - missing protocol member
                "QPane view must provide calculateRenderPlan for buffer repair"
            )
        plan = repair_plan or plan_calculate(use_pan=new_pan)
        if not self._plan_supports_exact_scroll_reuse(plan):
            self._scroll_misses += 1
            return False
        buffer_plan = self._buffer_render_plan
        if buffer_plan is None:
            self._scroll_misses += 1
            return False
        physical_delta = retained_raster_navigation_delta(
            buffer_plan,
            plan,
            device_pixel_ratio=surface.devicePixelRatio(),
        )
        if physical_delta is None:
            self._scroll_misses += 1
            return False
        if not self._presentation_transform.isIdentity():
            # A retained zoom preview is derived from the last settled frame.
            # Reprojecting it after another navigation delta compounds source
            # rounding and can move the whole composited frame.  Settle exactly
            # before accepting another pan instead.
            self._scroll_misses += 1
            return False
        if physical_delta.isNull():
            self._scroll_hits += 1
            subpixel_offset = self._canonical_subpixel_offset(
                QPointF(plan.current_pan) - self._buffer_pan
            )
            if (
                not subpixel_offset.isNull()
                and not self._surface.storage_origin.isNull()
            ):
                self._surface.normalize_storage()
            self._subpixel_pan_offset = subpixel_offset
            self._current_render_plan = plan
            self.qpane.update()
            return True
        dx = physical_delta.x()
        dy = physical_delta.y()
        if abs(dx) >= surface.width() or abs(dy) >= surface.height():
            self._scroll_misses += 1
            return False
        target_buffer_pan = QPointF(plan.current_pan)
        settled_plan = plan
        if not self._plan_supports_strip_repair(settled_plan):
            self._scroll_misses += 1
            return False
        if not navigation_products_match(buffer_plan, settled_plan):
            self._scroll_misses += 1
            return False
        if requires_linear_scroll_storage(settled_plan):
            self._surface.scroll_linear(dx, dy)
        else:
            self._surface.scroll(dx, dy)
        self._mark_diagnostics_dirty()
        self._buffer_pan = target_buffer_pan
        surface_region = QRegion(surface.rect())
        self._buffer_valid_region = self._buffer_valid_region.translated(
            dx,
            dy,
        ).intersected(surface_region)
        missing_region = surface_region.subtracted(self._buffer_valid_region)
        bleed = self._SCROLL_REPAIR_BLEED_PHYSICAL_PX
        repair_region = QRegion()
        for rect in missing_region:
            repair_region = repair_region.united(
                QRegion(rect.adjusted(-bleed, -bleed, bleed, bleed))
            )
        repair_region = repair_region.intersected(surface_region)
        repair_rects = [QRect(rect) for rect in repair_region]
        if (
            repair_rects
            and settled_plan
            and self._repair_base_buffer_strips(repair_rects, settled_plan) is False
        ):
            self.markDirty()
            self._scroll_misses += 1
            self._buffer_valid_region = QRegion()
            self.qpane.update()
            return False
        self._buffer_valid_region += repair_region
        self._scroll_hits += 1
        self._scroll_repairs += 1
        self._buffer_render_plan = settled_plan
        self._buffer_guard_valid = True
        self._subpixel_pan_offset = QPointF()
        self._current_render_plan = plan
        self.qpane.update()
        self._mark_diagnostics_dirty()
        return True

    def tryTransformBuffers(self, plan: SceneRenderPlan) -> bool:
        """Reuse the composited frame for an immediate zoom presentation."""
        self._navigation_refiner.cancel()
        previous_plan = self._current_render_plan
        if previous_plan is not None and (
            previous_plan.zoom <= 0.0 or plan.zoom <= 0.0
        ):
            return False
        base_image = self._surface.pixmap if self._surface.is_allocated else None
        buffer_plan = self._buffer_render_plan
        if (
            previous_plan is None
            or base_image is None
            or buffer_plan is None
            or isclose(previous_plan.zoom, plan.zoom, rel_tol=1e-9, abs_tol=1e-9)
            or not self._plan_supports_exact_scroll_reuse(previous_plan)
            or not self._plan_supports_exact_scroll_reuse(plan)
        ):
            return False
        return self._update_navigation_presentation(plan)

    def _update_navigation_presentation(self, plan: SceneRenderPlan) -> bool:
        """Present a new pan/zoom from settled pixels without copying the frame."""
        buffer_plan = self._buffer_render_plan
        if buffer_plan is None:
            return False
        presentation_transform = navigation_buffer_transform(
            buffer_plan,
            plan,
            overscan=self._buffer_overscan_physical_px,
            device_pixel_ratio=self._surface.pixmap.devicePixelRatio(),
        )
        if not self._frame_presenter.transformed_viewport_is_covered(
            self._surface.pixmap,
            viewport_rect=self.qpane.rect(),
            overscan_physical_px=self._buffer_overscan_physical_px,
            presentation_transform=presentation_transform,
        ):
            return False
        source_rect = self._frame_presenter.transformed_source_rect(
            self._surface.pixmap,
            viewport_rect=self.qpane.rect(),
            overscan_physical_px=self._buffer_overscan_physical_px,
            presentation_transform=presentation_transform,
        )
        if (
            source_rect.isEmpty()
            or not QRegion(source_rect).subtracted(self._buffer_valid_region).isEmpty()
        ):
            return False
        self._presentation_transform = presentation_transform
        self._current_render_plan = plan
        self._subpixel_pan_offset = QPointF()
        self._dirty_region = QRegion()
        self.qpane.update()
        self._mark_diagnostics_dirty()
        return True

    def get_last_paint_duration_ms(self) -> float:
        """Return the duration of the last paint call in milliseconds."""
        return self._last_paint_duration_ms

    def get_current_render_plan(self) -> SceneRenderPlan | None:
        """Return the most recent scene render plan captured during painting."""
        return self._current_render_plan

    def invalidate_current_render_plan(self) -> None:
        """Retire the painted plan after authoritative scene state changes."""
        self._navigation_refiner.cancel()
        self._current_render_plan = None

    def refine_navigation_frame(self, plan: SceneRenderPlan) -> bool:
        """Stage one exact navigation frame without blocking widget painting."""
        if not self._surface.is_allocated:
            return False
        return self._navigation_refiner.begin(
            plan,
            physical_size=self._surface.pixmap.size(),
            device_pixel_ratio=self._surface.pixmap.devicePixelRatio(),
            overscan_physical_px=self._buffer_overscan_physical_px,
        )

    @property
    def navigation_refinement_pending(self) -> bool:
        """Return whether an exact navigation frame is being staged."""
        return self._navigation_refiner.pending

    def navigation_refinement_metrics(self) -> IncrementalFrameMetrics:
        """Return bounded staged-frame lifecycle and latency metrics."""
        return self._navigation_refiner.snapshot_metrics()

    def cancel_navigation_refinement(self) -> None:
        """Discard one incomplete exact navigation frame."""
        self._navigation_refiner.cancel()

    def get_base_buffer(self) -> QImage | None:
        """Return an image snapshot of the current native backing surface."""
        if not self._surface.is_allocated:
            return None
        return self._surface.snapshot()

    def has_base_buffer(self) -> bool:
        """Return whether the native backing surface is allocated."""
        return self._surface.is_allocated

    def get_subpixel_pan_offset(self) -> QPointF:
        """Return the subpixel offset applied when scrolling reused buffers."""
        return self._subpixel_pan_offset

    @staticmethod
    def _canonical_subpixel_offset(offset: QPointF) -> QPointF:
        """Remove floating-point residue while preserving visible fractional pan."""
        return QPointF(
            0.0 if isclose(offset.x(), 0.0, rel_tol=0.0, abs_tol=1e-9) else offset.x(),
            0.0 if isclose(offset.y(), 0.0, rel_tol=0.0, abs_tol=1e-9) else offset.y(),
        )

    @property
    def buffer_overscan_physical_px(self) -> int:
        """Return the active physical navigation guard around the viewport."""
        return self._buffer_overscan_physical_px

    def draw_base_buffer(self, painter: QPainter) -> None:
        """Composite only scene-covered pixels from the retained frame buffer."""
        if not self._surface.is_allocated:
            return
        content_region = self._presentation_content_region()
        if content_region.isEmpty():
            return
        opaque_region = self._presentation_opaque_region().intersected(content_region)
        if self._presentation_transform.isIdentity():
            self._draw_base_buffer_region(
                painter,
                opaque_region,
                QPainter.CompositionMode_Source,
            )
            alpha_region = content_region.subtracted(opaque_region)
        else:
            alpha_region = content_region
        self._draw_base_buffer_region(
            painter,
            alpha_region,
            QPainter.CompositionMode_SourceOver,
        )

    def _draw_base_buffer_region(
        self,
        painter: QPainter,
        region: QRegion,
        composition_mode: QPainter.CompositionMode,
    ) -> None:
        """Present one source-alpha class under a conservative panel clip."""
        if region.isEmpty():
            return
        painter.save()
        try:
            painter.setClipRegion(region, Qt.ClipOperation.IntersectClip)
            painter.setCompositionMode(composition_mode)
            self._frame_presenter.draw(
                painter,
                self._surface.pixmap,
                viewport_physical_size=self._viewport_physical_size,
                viewport_rect=self.qpane.rect(),
                overscan_physical_px=self._buffer_overscan_physical_px,
                subpixel_pan_offset=self._subpixel_pan_offset,
                presentation_transform=self._presentation_transform,
                storage_origin_physical=self._surface.storage_origin,
            )
        finally:
            painter.restore()

    def _presentation_content_region(self) -> QRegion:
        """Return conservative widget pixels that may contain scene output."""
        plan = self._current_render_plan
        if plan is None:
            return QRegion()
        viewport_region = QRegion(self.qpane.rect())
        if plan.presentation_effects or plan.transient_raster is not None:
            return viewport_region
        content_region = QRegion()
        for item in plan.render_items:
            if item.descriptor.visible:
                content_region += self._items.item_panel_bounds(item)
        return content_region.intersected(viewport_region)

    def _presentation_opaque_region(self) -> QRegion:
        """Return pixels guaranteed opaque by a full-alpha base raster."""
        plan = self._current_render_plan
        if plan is None:
            return QRegion()
        base_item = plan.base_raster_item
        if (
            base_item is None
            or not base_item.descriptor.visible
            or not isclose(base_item.descriptor.opacity, 1.0)
            or base_item.clip is not None
            or base_item.descriptor.effects
            or base_item.transform.type().value
            > QTransform.TransformationType.TxScale.value
            or not self._image_is_fully_opaque(base_item.source_image)
        ):
            return QRegion()
        transient = plan.transient_raster
        if (
            transient is not None
            and transient.layer_id == base_item.descriptor.layer_id
        ):
            return QRegion()
        source_rect = QRectF(base_item.source_image.rect())
        opaque_rect = base_item.transform.mapRect(source_rect).toAlignedRect()
        edge_guard = self._OPAQUE_PRESENTATION_EDGE_GUARD_LOGICAL_PX
        opaque_rect.adjust(edge_guard, edge_guard, -edge_guard, -edge_guard)
        return QRegion(opaque_rect).intersected(QRegion(self.qpane.rect()))

    def _image_is_fully_opaque(self, image: QImage) -> bool:
        """Classify immutable raster alpha once per Qt image cache key."""
        if image.isNull():
            return False
        if not image.hasAlphaChannel():
            return True
        cache_key = image.cacheKey()
        cached = self._opaque_image_cache.get(cache_key)
        if cached is not None:
            self._opaque_image_cache.move_to_end(cache_key)
            return cached
        alpha = image.convertToFormat(QImage.Format.Format_Alpha8)
        pixels = bytes(alpha.constBits())
        width = alpha.width()
        stride = alpha.bytesPerLine()
        opaque = all(
            pixels[offset : offset + width].count(255) == width
            for offset in range(0, stride * alpha.height(), stride)
        )
        self._opaque_image_cache[cache_key] = opaque
        self._opaque_image_cache.move_to_end(cache_key)
        while len(self._opaque_image_cache) > self._OPAQUE_IMAGE_CACHE_LIMIT:
            self._opaque_image_cache.popitem(last=False)
        return opaque

    def snapshot_metrics(self) -> RendererMetrics:
        """Return current renderer reuse counters for diagnostics displays."""
        return RendererMetrics(
            base_buffer_allocations=self._base_buffer_allocations,
            scroll_attempts=self._scroll_attempts,
            scroll_hits=self._scroll_hits,
            scroll_misses=self._scroll_misses,
            scroll_repairs=self._scroll_repairs,
            full_redraws=self._full_redraws,
            partial_redraws=self._partial_redraws,
            last_paint_ms=self._last_paint_duration_ms,
        )

    def paint_stats(self) -> tuple[float, float, float]:
        """Return (last, average, max) paint durations in milliseconds."""
        average = (
            self._paint_duration_sum_ms / self._paint_duration_count
            if self._paint_duration_count > 0
            else 0.0
        )
        return (
            self._last_paint_duration_ms,
            average,
            self._paint_duration_max_ms,
        )

    @classmethod
    def _plan_supports_exact_scroll_reuse(
        cls,
        plan: SceneRenderPlan | None,
    ) -> bool:
        """Return whether every visible primitive tolerates integer translation."""
        if (
            plan is None
            or plan.transient_raster is not None
            or plan.presentation_effects
        ):
            return False
        visible_items = tuple(
            item for item in plan.render_items if item.descriptor.visible
        )
        if not visible_items:
            return False
        return all(
            item.transform.isAffine()
            and SceneItemCompositor.item_panel_bounds(item).isValid()
            for item in visible_items
        )

    @classmethod
    def _plan_supports_strip_repair(cls, plan: SceneRenderPlan | None) -> bool:
        """Return whether every visible item can be clipped to exposed strips."""
        if not cls._plan_supports_exact_scroll_reuse(plan) or plan is None:
            return False
        return all(
            not SceneItemCompositor.item_panel_bounds(item).isEmpty()
            for item in plan.render_items
            if item.descriptor.visible
        )

    def _repair_base_buffer_strips(
        self,
        repair_rects: list[QRect],
        plan: SceneRenderPlan,
    ) -> bool:
        """Repair newly exposed scene strips after backing-buffer scrolling."""
        if not plan.render_items:
            return True
        if self._can_repair_base_strips_directly(plan):
            self._repair_base_raster_strips_directly(repair_rects, plan)
            return True
        return self._repair_layered_strips(repair_rects, plan)

    def _can_repair_base_strips_directly(self, plan: SceneRenderPlan) -> bool:
        """Return whether repair can use the single-raster fast path."""
        base_item = self._base_only_raster_item(plan)
        return base_item is not None and base_item.strategy == RenderStrategy.DIRECT

    def _repair_base_raster_strips_directly(
        self,
        repair_rects: list[QRect],
        plan: SceneRenderPlan,
    ) -> None:
        """Repair single-raster strips through the normal raster draw path."""
        base_item = plan.base_raster_item
        if base_item is None:
            return
        self._paint_repair_patches(
            repair_rects,
            lambda painter, panel_clips: self._items.draw_raster_item(
                painter,
                plan,
                base_item,
                panel_clips=panel_clips,
            ),
        )

    def _repair_layered_strips(
        self,
        repair_rects: list[QRect],
        plan: SceneRenderPlan,
    ) -> bool:
        """Repair layered strips through the normal item compositor."""
        repair_region = self._patch_painter.logical_region(repair_rects)
        if repair_region.isEmpty():
            return True
        visible_items = []
        if plan.presentation_effects:
            visible_items = [
                item for item in plan.render_items if item.descriptor.visible
            ]
        else:
            for item in plan.render_items:
                if not item.descriptor.visible:
                    continue
                item_bounds = self._items.item_panel_bounds(item)
                if item_bounds.isEmpty():
                    return False
                visible_items.append(item)

        def draw_items(
            painter: QPainter,
            panel_clips: tuple[QRectF, ...],
        ) -> None:
            """Draw visible repair contributors into one isolated patch."""
            if plan.presentation_effects:
                self._items.draw_visible_items(
                    painter,
                    plan,
                    panel_clips=panel_clips,
                )
                return
            for item in visible_items:
                if not any(
                    self._items.item_panel_bounds(item).intersects(
                        panel_clip.toAlignedRect()
                    )
                    for panel_clip in panel_clips
                ):
                    continue
                painter.save()
                try:
                    self._items.draw_item(
                        painter,
                        plan,
                        item,
                        panel_clips=panel_clips,
                    )
                finally:
                    painter.restore()

        self._paint_repair_patches(repair_rects, draw_items)
        return True

    def _paint_repair_patches(
        self,
        repair_rects: list[QRect],
        draw: Callable[[QPainter, tuple[QRectF, ...]], None],
    ) -> None:
        """Recompose disjoint physical repair rectangles in native storage."""

        def paint(painter: QPainter) -> None:
            """Clear and recompose each disjoint patch under its native clip."""
            self._patch_painter.paint(painter, repair_rects, draw)

        logical_region = QRegion()
        for rect in repair_rects:
            logical_region += rect
        self._surface.paint_native(
            paint,
            logical_region=logical_region,
        )

    def _publish_navigation_refinement(self, plan: SceneRenderPlan) -> None:
        """Atomically promote one completed exact navigation surface."""
        self._surface.publish_staging()
        self._current_render_plan = plan
        self._buffer_render_plan = plan
        self._buffer_pan = QPointF(plan.current_pan)
        self._subpixel_pan_offset = QPointF()
        self._buffer_guard_valid = True
        self._buffer_valid_region = QRegion(self._surface.pixmap.rect())
        self._presentation_transform.reset()
        self._dirty_region = QRegion()
        self.qpane.update()
        self._mark_diagnostics_dirty()

    def _navigation_refinement_failed(self) -> None:
        """Recover one rejected worker frame through canonical synchronous damage."""
        self.markDirty()
        self.qpane.update()

    def _redraw_base_image_buffer(self, dirty_region: QRegion, plan: SceneRenderPlan):
        """Repaint damage without mixing exact and retained navigation geometry."""
        if not self._surface.is_allocated:
            return
        qpane_rect = plan.qpane_rect
        qpane_region = QRegion(qpane_rect)
        full_viewport_dirty = dirty_region.intersected(
            qpane_region
        ) == qpane_region or self._partial_damage_requires_full_repaint(plan)
        if full_viewport_dirty:
            self._full_redraws += 1
        else:
            self._partial_redraws += 1
        self._current_render_plan = plan
        physical_rects = (
            [QRect(self._surface.pixmap.rect())]
            if full_viewport_dirty
            else self._physical_buffer_rects_for_damage(dirty_region)
        )
        if not physical_rects:
            return
        if full_viewport_dirty:
            self._surface.begin_full_repaint()
        base_only_item = self._base_only_raster_item(plan)

        def draw(
            painter: QPainter,
            panel_clips: tuple[QRectF, ...],
        ) -> None:
            """Draw the current plan through its most direct canonical path."""
            if base_only_item is not None:
                self._items.draw_raster_item(
                    painter,
                    plan,
                    base_only_item,
                    panel_clips=panel_clips,
                )
                return
            self._items.draw_visible_items(
                painter,
                plan,
                panel_clips=panel_clips,
            )

        if full_viewport_dirty:
            for physical_rect in physical_rects:
                self._paint_repair_patches([physical_rect], draw)
        else:
            self._paint_repair_patches(physical_rects, draw)
        if full_viewport_dirty:
            self._buffer_pan = QPointF(plan.current_pan)
            self._subpixel_pan_offset = QPointF()
            self._buffer_guard_valid = True
            self._buffer_valid_region = QRegion(self._surface.pixmap.rect())
            self._buffer_render_plan = plan
            self._presentation_transform.reset()

    def _partial_damage_requires_full_repaint(self, plan: SceneRenderPlan) -> bool:
        """Reject patch painting while the backing buffer uses another viewport."""

        buffer_plan = self._buffer_render_plan
        if (
            buffer_plan is None
            or not self._presentation_transform.isIdentity()
            or not self._subpixel_pan_offset.isNull()
        ):
            return True
        return not (
            isclose(buffer_plan.zoom, plan.zoom, rel_tol=1e-9, abs_tol=1e-9)
            and isclose(
                buffer_plan.current_pan.x(),
                plan.current_pan.x(),
                rel_tol=0.0,
                abs_tol=1e-9,
            )
            and isclose(
                buffer_plan.current_pan.y(),
                plan.current_pan.y(),
                rel_tol=0.0,
                abs_tol=1e-9,
            )
            and buffer_plan.qpane_rect == plan.qpane_rect
        )

    def _physical_buffer_rects_for_damage(
        self,
        dirty_region: QRegion,
    ) -> list[QRect]:
        """Map logical widget damage into disjoint physical buffer rectangles."""
        context = CoordinateContext(self.qpane)
        margin = self._buffer_overscan_physical_px
        physical_region = QRegion()
        surface_rect = self._surface.pixmap.rect()
        for logical_rect in dirty_region:
            physical_rect = context.logical_to_physical(QRectF(logical_rect))
            if not isinstance(physical_rect, QRectF):
                raise TypeError("logical rectangle conversion must return QRectF")
            aligned = physical_rect.translated(float(margin), float(margin))
            clipped = aligned.toAlignedRect().intersected(surface_rect)
            if not clipped.isEmpty():
                physical_region = physical_region.united(QRegion(clipped))
        return self._canonical_patch_rects(physical_region)

    def _visible_buffer_crop_is_valid(self, physical_delta: QPoint) -> bool:
        """Return whether retained pixels cover the requested visible crop."""
        visible_crop = QRect(
            self._buffer_overscan_physical_px - physical_delta.x(),
            self._buffer_overscan_physical_px - physical_delta.y(),
            self._viewport_physical_size.width(),
            self._viewport_physical_size.height(),
        )
        if not self._surface.pixmap.rect().contains(visible_crop):
            return False
        return QRegion(visible_crop).subtracted(self._buffer_valid_region).isEmpty()

    def _canonical_patch_rects(self, region: QRegion) -> list[QRect]:
        """Expand physical damage to globally anchored compositing patches."""
        if region.isEmpty():
            return []
        patch_size = self._COMPOSITING_PATCH_PHYSICAL_PX
        surface_rect = self._surface.pixmap.rect()
        patches: dict[tuple[int, int], QRect] = {}
        for rect in region:
            start_column = max(0, rect.left() // patch_size)
            end_column = max(0, rect.right() // patch_size)
            start_row = max(0, rect.top() // patch_size)
            end_row = max(0, rect.bottom() // patch_size)
            for row in range(start_row, end_row + 1):
                for column in range(start_column, end_column + 1):
                    patch = QRect(
                        column * patch_size,
                        row * patch_size,
                        patch_size,
                        patch_size,
                    ).intersected(surface_rect)
                    if not patch.isEmpty():
                        patches[(row, column)] = patch
        return [patches[index] for index in sorted(patches)]

    @staticmethod
    def _base_only_raster_item(plan: SceneRenderPlan) -> RasterLayerRenderItem | None:
        """Return the sole base raster item when a plan matches old-QPane shape."""
        if plan.transient_raster is not None or plan.presentation_effects:
            return None
        return Renderer._sole_base_raster_item(plan)

    @staticmethod
    def _sole_base_raster_item(plan: SceneRenderPlan) -> RasterLayerRenderItem | None:
        """Return the sole base raster item independent of presentation effects."""
        if plan.transient_raster is not None:
            return None
        if len(plan.render_items) != 1:
            return None
        item = plan.render_items[0]
        if not isinstance(item, RasterLayerRenderItem):
            return None
        if item is not plan.base_raster_item:
            return None
        if not item.descriptor.visible:
            return None
        if not isclose(item.descriptor.opacity, 1.0, rel_tol=0.0, abs_tol=1e-9):
            return None
        if item.clip is not None:
            return None
        if item.effect_clip_path is not None:
            return None
        if item.placement != plan.scene_bounds:
            return None
        if item.source_image.isNull():
            return None
        return item

    def _overscanned_buffer_size(self, viewport_size: QSize) -> QSize:
        """Return the backing-buffer size including physical overscan."""
        margin = self._buffer_overscan_physical_px * 2
        return QSize(
            max(0, viewport_size.width() + margin),
            max(0, viewport_size.height() + margin),
        )

    @classmethod
    def _overscan_for_viewport(cls, viewport_size: QSize) -> int:
        """Return bounded navigation guard storage for a physical viewport."""
        pixels = max(0, viewport_size.width()) * max(0, viewport_size.height())
        if pixels >= 3840 * 2160:
            return cls._FOUR_K_VIEWPORT_GUARD_PHYSICAL_PX
        if pixels >= 2560 * 1440:
            return cls._LARGE_VIEWPORT_GUARD_PHYSICAL_PX
        return cls._BUFFER_OVERSCAN_PHYSICAL_PX

    def _mark_diagnostics_dirty(self) -> None:
        """Mark render diagnostics dirty on the QPane if available."""
        diagnostics = getattr(self.qpane, "diagnostics", None)
        if not callable(diagnostics):
            return
        try:
            manager = diagnostics()
        except RuntimeError:  # pragma: no cover - diagnostics teardown
            return
        if manager is not None:
            manager.set_dirty("render")
