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

"""Mount and observe a real CuteCanvas under Qt's offscreen platform."""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import MethodType, TracebackType

from cutecanvas import CuteCanvas
from PySide6.QtCore import QEvent, QPoint, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from qpane.scene.model import LayerKind
from qpane.scene.render_plan import SceneRenderPlan
from typing_extensions import Self

_ASYNC_SETTLE_TIMEOUT_MS = 15_000


@dataclass(frozen=True, slots=True)
class PixelMeasurement:
    """Record observation latency and the last sampled widget pixel."""

    latency_ms: float | None
    color: QColor


@dataclass(frozen=True, slots=True)
class PresentedMaskFrame:
    """Capture one renderer backing frame and its mask-layer presence."""

    image: QImage
    overscan_margin: int
    mask_layer_count: int
    mask_layer_ids: tuple[uuid.UUID, ...]
    mask_sample_scales: tuple[float, ...]
    mask_item_states: tuple[tuple[str, int, int, int, int, int], ...]

    def color_at(self, point: QPoint) -> QColor:
        """Return the backing-buffer color presented at a widget point."""
        return self.image.pixelColor(
            point.x() + self.overscan_margin,
            point.y() + self.overscan_margin,
        )


class PresentedFrameProbe:
    """Record every backing frame rendered while the probe is active."""

    def __init__(self, viewer: CuteCanvas) -> None:
        """Bind a mounted canvas without changing its rendering policy."""
        self._renderer = viewer.view().presenter.renderer
        self._original_paint: Callable[[SceneRenderPlan], None] | None = None
        self.frames: list[PresentedMaskFrame] = []

    @staticmethod
    def _mask_item_state(item: object) -> tuple[str, int, int, int, int, int]:
        """Return compact raster-product diagnostics for one mask render item."""
        source_image = getattr(item, "source_image", QImage())
        center_alpha = (
            0
            if source_image.isNull()
            else source_image.pixelColor(
                source_image.width() // 2,
                source_image.height() // 2,
            ).alpha()
        )
        return (
            type(item).__name__,
            len(getattr(item, "tiles", ())),
            len(getattr(item, "tiles_to_draw", ())),
            source_image.width(),
            source_image.height(),
            center_alpha,
        )

    def __enter__(self) -> Self:
        """Begin recording frames after normal renderer painting completes."""
        original_paint = self._renderer.paint
        self._original_paint = original_paint

        def tracked_paint(_renderer: object, plan: SceneRenderPlan) -> None:
            """Delegate production painting and retain its presented buffer."""
            original_paint(plan)
            buffer = self._renderer.get_base_buffer()
            if buffer is None:
                return
            mask_layer_count = sum(
                item.descriptor.kind is LayerKind.MASK for item in plan.render_items
            )
            mask_layer_ids = tuple(
                item.descriptor.layer_id
                for item in plan.render_items
                if item.descriptor.kind is LayerKind.MASK
            )
            mask_sample_scales = tuple(
                round(
                    tile.image_source_rect.width() / tile.source_rect.width(),
                    6,
                )
                for item in plan.render_items
                if item.descriptor.kind is LayerKind.MASK
                for tile in getattr(item, "tiles", ())
                if tile.source_rect.width() > 0.0
            )
            mask_item_states = tuple(
                self._mask_item_state(item)
                for item in plan.render_items
                if item.descriptor.kind is LayerKind.MASK
            )
            self.frames.append(
                PresentedMaskFrame(
                    image=buffer.copy(),
                    overscan_margin=self._renderer.buffer_overscan_physical_px,
                    mask_layer_count=mask_layer_count,
                    mask_layer_ids=mask_layer_ids,
                    mask_sample_scales=mask_sample_scales,
                    mask_item_states=mask_item_states,
                )
            )

        self._renderer.paint = MethodType(tracked_paint, self._renderer)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the renderer method after recording."""
        del exc_type, exc_value, traceback
        if self._original_paint is not None:
            self._renderer.paint = self._original_paint
            self._original_paint = None


class RendererPaintDurationProbe:
    """Record synchronous renderer work without copying presented frames."""

    def __init__(self, viewer: CuteCanvas) -> None:
        """Bind one mounted canvas renderer."""
        self._renderer = viewer.view().presenter.renderer
        self._original_paint: Callable[[SceneRenderPlan], None] | None = None
        self.durations_ms: list[float] = []

    def __enter__(self) -> Self:
        """Begin timing every production renderer invocation."""
        original_paint = self._renderer.paint
        self._original_paint = original_paint

        def timed_paint(_renderer: object, plan: SceneRenderPlan) -> None:
            """Delegate one render and retain its synchronous duration."""
            started = time.perf_counter()
            original_paint(plan)
            self.durations_ms.append((time.perf_counter() - started) * 1000.0)

        self._renderer.paint = MethodType(timed_paint, self._renderer)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the production renderer method."""
        del exc_type, exc_value, traceback
        if self._original_paint is not None:
            self._renderer.paint = self._original_paint
            self._original_paint = None


class NavigationTransformDurationProbe:
    """Record synchronous composited-buffer transforms during zoom."""

    def __init__(self, viewer: CuteCanvas) -> None:
        """Bind one mounted canvas renderer."""
        self._renderer = viewer.view().presenter.renderer
        self._original_transform: Callable[[SceneRenderPlan], bool] | None = None
        self.durations_ms: list[float] = []

    def __enter__(self) -> Self:
        """Begin timing every production zoom-buffer transform."""
        original_transform = self._renderer.tryTransformBuffers
        self._original_transform = original_transform

        def timed_transform(_renderer: object, plan: SceneRenderPlan) -> bool:
            """Delegate one transform and retain its synchronous duration."""
            started = time.perf_counter()
            result = original_transform(plan)
            self.durations_ms.append((time.perf_counter() - started) * 1000.0)
            return result

        self._renderer.tryTransformBuffers = MethodType(
            timed_transform,
            self._renderer,
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the production transform method."""
        del exc_type, exc_value, traceback
        if self._original_transform is not None:
            self._renderer.tryTransformBuffers = self._original_transform
            self._original_transform = None


class MountedQPaneHarness:
    """Own a shown production CuteCanvas and its event-loop observation boundary."""

    def __init__(
        self,
        qapp: QApplication,
        *,
        source_image: QImage | None = None,
        image_size: QSize | None = None,
        widget_size: QSize | None = None,
        mask_count: int = 1,
        brush_size: int = 30,
        cache_budget_mb: int = 1024,
    ) -> None:
        """Create a mounted brush-mode pane backed by an in-memory image."""
        if mask_count < 1:
            raise ValueError("mask_count must be at least one")
        if cache_budget_mb < 1:
            raise ValueError("cache_budget_mb must be at least one")
        if source_image is not None and source_image.isNull():
            raise ValueError("source_image must not be null")
        if source_image is not None and image_size is not None:
            raise ValueError("source_image and image_size are mutually exclusive")
        image_size = (
            QSize(source_image.size())
            if source_image is not None
            else QSize(400, 400) if image_size is None else QSize(image_size)
        )
        widget_size = QSize(400, 400) if widget_size is None else QSize(widget_size)
        self.qapp = qapp
        self.host = QWidget()
        self.host.resize(widget_size)
        host_layout = QVBoxLayout(self.host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)
        self.viewer = CuteCanvas(features=("mask",))
        self.viewer.setParent(self.host)
        host_layout.addWidget(self.viewer)
        self.viewer.applySettings(
            touch_inertia_enabled=False,
            cache={"mode": "hard", "budget_mb": cache_budget_mb},
        )
        self.viewer.resize(widget_size)
        self.host.show()
        self.image = (
            QImage(source_image)
            if source_image is not None
            else QImage(image_size, QImage.Format.Format_ARGB32)
        )
        if source_image is None:
            self.image.fill(Qt.GlobalColor.white)
        self.image_id = self.viewer.createCompositionFromImage(
            self.image,
            title="Abuse harness",
            label="Background",
        )
        self.mask_ids = tuple(self._create_mask(image_size) for _ in range(mask_count))
        self.viewer.setActiveMaskID(self.mask_ids[0])
        self.viewer.setControlMode(self.viewer.CONTROL_MODE_DRAW_BRUSH)
        self.viewer.setBrushSize(brush_size)
        self.drain_events(wait_ms=5)
        center = QPoint(widget_size.width() // 2, widget_size.height() // 2)
        if source_image is None:
            ready = (
                self.wait_for_background(center, timeout_ms=3000).latency_ms is not None
            )
        else:
            deadline = time.perf_counter() + 3.0
            renderer = self.viewer.view().presenter.renderer
            while not renderer.has_base_buffer() and time.perf_counter() < deadline:
                self.qapp.processEvents()
                QTest.qWait(1)
            ready = renderer.has_base_buffer()
        if not ready:
            self.close()
            raise RuntimeError(
                "Mounted CuteCanvas did not present source pixels before input"
            )

    def close(self) -> None:
        """Dispose the pane and await its harness-owned execution workers."""
        execution_runtime = self.viewer.documentRuntime().execution_runtime
        for document in tuple(self.viewer.editor.compositions):
            if document.state.policy.removable:
                document.remove()
        self.drain_events(wait_ms=25)
        execution_runtime.shutdown(wait=True)
        self.qapp.processEvents()
        self.host.close()
        self.viewer.deleteLater()
        self.host.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.qapp.processEvents()

    def activate_mask(self, index: int) -> uuid.UUID:
        """Activate and return the mask at ``index``."""
        mask_id = self.mask_ids[index]
        if not self.viewer.setActiveMaskID(mask_id):
            raise RuntimeError(f"CuteCanvas rejected active mask {mask_id}")
        self.drain_events()
        return mask_id

    def drain_events(self, *, wait_ms: int = 0) -> None:
        """Process queued Qt work and optionally allow timers to advance."""
        self.qapp.processEvents()
        if wait_ms > 0:
            QTest.qWait(wait_ms)
            self.qapp.processEvents()

    def capture(self) -> QImage:
        """Return the real mounted widget's current composited pixels."""
        self.drain_events()
        return self.viewer.grab().toImage().copy()

    def observe_presented_frames(self) -> PresentedFrameProbe:
        """Return a scoped probe for every renderer frame during an operation."""
        return PresentedFrameProbe(self.viewer)

    def observe_renderer_paint_durations(self) -> RendererPaintDurationProbe:
        """Return a scoped probe for synchronous frame-render durations."""
        return RendererPaintDurationProbe(self.viewer)

    def observe_navigation_transform_durations(
        self,
    ) -> NavigationTransformDurationProbe:
        """Return a scoped probe for synchronous zoom-preview transforms."""
        return NavigationTransformDurationProbe(self.viewer)

    def capture_active_mask_render(self) -> QImage:
        """Return the cached mask render nearest the pane's displayed scale."""
        service = getattr(self.viewer, "mask_service", None)
        if service is None:
            return QImage()
        mask_id = service.getActiveMaskId()
        if mask_id is None:
            return QImage()
        cache = getattr(service.controller, "_colorized_mask_cache", {})
        candidates = [
            (key, pixmap)
            for key, pixmap in cache.items()
            if key.mask_id == mask_id and pixmap is not None and not pixmap.isNull()
        ]
        if not candidates:
            return QImage()
        displayed_scale = max(1e-6, float(self.viewer.currentZoom()))

        def render_rank(candidate) -> tuple[float, int]:
            """Prefer the nearest pyramid scale and newest content revision."""
            key, _pixmap = candidate
            scale = 1.0 if key.scale_key is None else float(key.scale_key)
            return (
                abs(math.log(max(scale, 1e-6) / displayed_scale)),
                -int(key.render_revision),
            )

        _key, pixmap = min(candidates, key=render_rank)
        return pixmap.toImage().copy()

    def wait_for_mask_render_idle(
        self,
        *,
        timeout_ms: int = _ASYNC_SETTLE_TIMEOUT_MS,
    ) -> bool:
        """Wait until production mask rendering can no longer change the frame."""
        deadline = time.perf_counter() + timeout_ms / 1000.0
        while time.perf_counter() < deadline:
            self.qapp.processEvents()
            service = getattr(self.viewer, "mask_service", None)
            if service is not None and not service.hasPendingRenderWork():
                self.qapp.processEvents()
                return True
            QTest.qWait(1)
        return False

    def wait_for_render_refinement_idle(
        self,
        *,
        timeout_ms: int = _ASYNC_SETTLE_TIMEOUT_MS,
        include_prefetch: bool = False,
    ) -> bool:
        """Wait until sampled and navigation refinement both remain quiescent."""
        deadline = time.perf_counter() + timeout_ms / 1000.0
        idle_since: float | None = None
        while time.perf_counter() < deadline:
            self.qapp.processEvents()
            presenter = self.viewer.view().presenter
            coordinator = presenter._render_refinement
            idle = (
                coordinator.pending_count == 0
                and not presenter.navigation_refinement_pending
                and (not include_prefetch or not coordinator.prefetch_pending)
            )
            now = time.perf_counter()
            idle_since = now if idle and idle_since is None else idle_since
            if not idle:
                idle_since = None
            if idle_since is not None and now - idle_since >= 0.025:
                self.qapp.processEvents()
                return True
            QTest.qWait(1)
        return False

    def wait_for_sampled_render_idle(
        self,
        *,
        timeout_ms: int = _ASYNC_SETTLE_TIMEOUT_MS,
        include_prefetch: bool = False,
    ) -> bool:
        """Wait until sampled source refinement reaches continuous quiescence."""
        deadline = time.perf_counter() + timeout_ms / 1000.0
        idle_since: float | None = None
        while time.perf_counter() < deadline:
            self.qapp.processEvents()
            coordinator = self.viewer.view().presenter._render_refinement
            idle = coordinator.pending_count == 0 and (
                not include_prefetch or not coordinator.prefetch_pending
            )
            now = time.perf_counter()
            idle_since = now if idle and idle_since is None else idle_since
            if not idle:
                idle_since = None
            if idle_since is not None and now - idle_since >= 0.025:
                self.qapp.processEvents()
                return True
            QTest.qWait(1)
        return False

    def wait_for_raster_render_idle(
        self,
        *,
        timeout_ms: int = _ASYNC_SETTLE_TIMEOUT_MS,
    ) -> bool:
        """Wait through pyramid completion and a continuous queued-event quiescence."""
        deadline = time.perf_counter() + timeout_ms / 1000.0
        idle_since: float | None = None
        while time.perf_counter() < deadline:
            self.qapp.processEvents()
            pyramids = self.viewer.view()._pyramid_manager
            tile_metrics = self.viewer.view().tile_manager.snapshot_metrics()
            idle = (
                not pyramids.pending_asset_keys()
                and not pyramids.pending_retry_asset_keys()
                and tile_metrics.active_jobs == 0
                and tile_metrics.pending_retries == 0
            )
            now = time.perf_counter()
            idle_since = now if idle and idle_since is None else idle_since
            if not idle:
                idle_since = None
            if idle_since is not None and now - idle_since >= 0.025:
                self.qapp.processEvents()
                return True
            QTest.qWait(1)
        return False

    def wait_for_mask_undo_depth(
        self,
        mask_id: uuid.UUID,
        expected_depth: int,
        *,
        timeout_ms: int = _ASYNC_SETTLE_TIMEOUT_MS,
    ) -> bool:
        """Wait until durable mask history reaches ``expected_depth``."""
        deadline = time.perf_counter() + timeout_ms / 1000.0
        while time.perf_counter() < deadline:
            self.qapp.processEvents()
            state = self.viewer.getMaskUndoState(mask_id)
            if state is not None and state.undo_depth == expected_depth:
                return True
            QTest.qWait(1)
        return False

    def save_capture(self, path: Path) -> None:
        """Save the current composited widget image or raise on failure."""
        path.parent.mkdir(parents=True, exist_ok=True)
        if not self.capture().save(str(path)):
            raise RuntimeError(f"Failed to save CuteCanvas capture to {path}")

    def color_at(self, point: QPoint) -> QColor:
        """Sample one pixel from the mounted widget composition."""
        return self.capture().pixelColor(point)

    def wait_for_mask_tint(
        self,
        point: QPoint,
        *,
        timeout_ms: int = 150,
    ) -> PixelMeasurement:
        """Wait until the default mask overlay is visible at ``point``."""
        return self.wait_for_color(point, self.is_mask_tint, timeout_ms=timeout_ms)

    def wait_for_background(
        self,
        point: QPoint,
        *,
        timeout_ms: int = 150,
    ) -> PixelMeasurement:
        """Wait until the white source image is visible at ``point``."""
        return self.wait_for_color(point, self.is_background, timeout_ms=timeout_ms)

    def wait_for_color(
        self,
        point: QPoint,
        predicate: Callable[[QColor], bool],
        *,
        timeout_ms: int,
    ) -> PixelMeasurement:
        """Poll real widget pixels until ``predicate`` accepts the sample."""
        started_at = time.perf_counter()
        deadline = started_at + timeout_ms / 1000.0
        color = QColor()
        while time.perf_counter() < deadline:
            self.qapp.processEvents()
            color = self.viewer.grab().toImage().pixelColor(point)
            if predicate(color):
                return PixelMeasurement(
                    latency_ms=(time.perf_counter() - started_at) * 1000.0,
                    color=color,
                )
            QTest.qWait(1)
        return PixelMeasurement(latency_ms=None, color=color)

    def diagnostics_rows(self) -> tuple[tuple[str, str], ...]:
        """Collect the pane's supported diagnostics as serializable rows."""
        return self.viewer.diagnostics().gather().rows()

    @staticmethod
    def is_mask_tint(color: QColor) -> bool:
        """Return whether ``color`` contains a saturated mask overlay tint."""
        channels = (color.red(), color.green(), color.blue())
        return max(channels) - min(channels) >= 20 and min(channels) < 245

    @staticmethod
    def is_background(color: QColor) -> bool:
        """Return whether ``color`` is the unmasked white source image."""
        return color.red() >= 250 and color.green() >= 250 and color.blue() >= 250

    def _create_mask(self, image_size: QSize) -> uuid.UUID:
        """Create one mask through the public facade and require success."""
        mask_id = self.viewer.createBlankMask(image_size)
        if mask_id is None:
            raise RuntimeError("CuteCanvas failed to create a blank abuse-harness mask")
        return mask_id
