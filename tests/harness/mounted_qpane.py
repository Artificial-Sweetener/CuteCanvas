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

"""Mount and observe a real QPane under Qt's offscreen platform."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
from pathlib import Path
import time
from types import MethodType, TracebackType
import uuid

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from qpane import QPane
from qpane.scene.render_plan import MaskLayerRenderItem, SceneRenderPlan


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

    def color_at(self, point: QPoint) -> QColor:
        """Return the backing-buffer color presented at a widget point."""
        return self.image.pixelColor(
            point.x() + self.overscan_margin,
            point.y() + self.overscan_margin,
        )


class PresentedFrameProbe:
    """Record every backing frame rendered while the probe is active."""

    def __init__(self, harness: "MountedQPaneHarness") -> None:
        """Bind the mounted pane without changing its rendering policy."""
        self._renderer = harness.viewer.view().presenter.renderer
        self._original_paint: Callable[[SceneRenderPlan], None] | None = None
        self.frames: list[PresentedMaskFrame] = []

    def __enter__(self) -> "PresentedFrameProbe":
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
                isinstance(item, MaskLayerRenderItem) for item in plan.render_items
            )
            self.frames.append(
                PresentedMaskFrame(
                    image=buffer.copy(),
                    overscan_margin=self._renderer._BUFFER_OVERSCAN_PHYSICAL_PX,
                    mask_layer_count=mask_layer_count,
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


class MountedQPaneHarness:
    """Own a shown production QPane and its event-loop observation boundary."""

    def __init__(
        self,
        qapp: QApplication,
        *,
        image_size: QSize = QSize(400, 400),
        widget_size: QSize = QSize(400, 400),
        mask_count: int = 1,
        brush_size: int = 30,
        cache_budget_mb: int = 1024,
    ) -> None:
        """Create a mounted brush-mode pane backed by an in-memory image."""
        if mask_count < 1:
            raise ValueError("mask_count must be at least one")
        if cache_budget_mb < 1:
            raise ValueError("cache_budget_mb must be at least one")
        self.qapp = qapp
        self.host = QWidget()
        self.host.resize(widget_size)
        host_layout = QVBoxLayout(self.host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)
        self.viewer = QPane(features=("mask",))
        self.viewer.setParent(self.host)
        host_layout.addWidget(self.viewer)
        self.viewer.applySettings(
            touch_inertia_enabled=False,
            cache={"mode": "hard", "budget_mb": cache_budget_mb},
        )
        self.viewer.resize(widget_size)
        self.host.show()
        self.image = QImage(image_size, QImage.Format.Format_ARGB32)
        self.image.fill(Qt.GlobalColor.white)
        self.image_id = uuid.uuid4()
        self.viewer.setImagesByID(
            self.viewer.imageMapFromLists(
                [self.image],
                [None],
                [self.image_id],
            ),
            self.image_id,
        )
        self.mask_ids = tuple(self._create_mask(image_size) for _ in range(mask_count))
        self.viewer.setActiveMaskID(self.mask_ids[0])
        self.viewer.setControlMode(self.viewer.CONTROL_MODE_DRAW_BRUSH)
        self.viewer.setBrushSize(brush_size)
        self.drain_events(wait_ms=5)
        center = QPoint(widget_size.width() // 2, widget_size.height() // 2)
        readiness = self.wait_for_background(center, timeout_ms=3000)
        if readiness.latency_ms is None:
            self.close()
            raise RuntimeError(
                "Mounted QPane did not present source pixels before input "
                f"(center={readiness.color.getRgb()})"
            )

    def close(self) -> None:
        """Dispose the pane and drain its queued Qt work."""
        self.viewer.clearImages()
        self.drain_events(wait_ms=25)
        self.host.close()
        self.viewer.deleteLater()
        self.host.deleteLater()
        self.qapp.processEvents()

    def activate_mask(self, index: int) -> uuid.UUID:
        """Activate and return the mask at ``index``."""
        mask_id = self.mask_ids[index]
        if not self.viewer.setActiveMaskID(mask_id):
            raise RuntimeError(f"QPane rejected active mask {mask_id}")
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
        return self.viewer.grab().toImage()

    def observe_presented_frames(self) -> PresentedFrameProbe:
        """Return a scoped probe for every renderer frame during an operation."""
        return PresentedFrameProbe(self)

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
        timeout_ms: int = 3000,
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

    def save_capture(self, path: Path) -> None:
        """Save the current composited widget image or raise on failure."""
        path.parent.mkdir(parents=True, exist_ok=True)
        if not self.capture().save(str(path)):
            raise RuntimeError(f"Failed to save QPane capture to {path}")

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
            raise RuntimeError("QPane failed to create a blank abuse-harness mask")
        return mask_id
