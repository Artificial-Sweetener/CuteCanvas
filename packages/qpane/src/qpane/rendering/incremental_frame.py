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
"""Asynchronous construction of atomic exact navigation frames."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QImage, QPainter

from ..execution import (
    CancellationToken,
    ExecutionHandle,
    ExecutionOutcome,
    ExecutionRejected,
    ExecutionRequest,
    ExecutionRequirements,
    ExecutionResource,
    ExecutionScope,
    ExecutionState,
    ExecutionUrgency,
)
from ..scene.render_plan import SceneRenderPlan
from .item_compositor import SceneItemCompositor

logger = logging.getLogger(__name__)
_TRANSFER_PATCH_PHYSICAL_PX = 1024
_TRANSFER_STEP_BUDGET_MS = 4.0


@dataclass(frozen=True, slots=True)
class IncrementalFrameMetrics:
    """Describe exact-frame lifecycle and GUI publication latency."""

    completed_frames: int
    cancelled_frames: int
    maximum_step_ms: float
    maximum_publish_ms: float
    maximum_worker_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class _FrameRequest:
    """Carry detached geometry and products into one worker composition."""

    generation: int
    plan: SceneRenderPlan
    physical_size: QSize
    device_pixel_ratio: float
    overscan_physical_px: int

    def __post_init__(self) -> None:
        """Detach mutable Qt geometry from the GUI-owned renderer."""
        object.__setattr__(self, "physical_size", QSize(self.physical_size))


@dataclass(frozen=True, slots=True)
class _FrameResult:
    """Return one complete worker-rendered frame for atomic adoption."""

    generation: int
    plan: SceneRenderPlan
    image: QImage
    worker_ms: float


class IncrementalFrameRefiner(QObject):
    """Build exact frames off-thread and publish only the newest complete result."""

    def __init__(
        self,
        *,
        parent: QObject | None,
        execution_scope: ExecutionScope | None,
        prepare: Callable[[], None],
        discard: Callable[[], None],
        transfer_patch: Callable[[QImage, QRect], None],
        publish: Callable[[SceneRenderPlan], None],
        failed: Callable[[], None],
    ) -> None:
        """Bind execution, atomic publication, and contained failure recovery."""
        super().__init__(parent)
        self._execution_scope = (
            None
            if execution_scope is None
            else execution_scope.open_child(
                f"{execution_scope.owner_id}:navigation-frame"
            )
        )
        self._prepare = prepare
        self._discard = discard
        self._transfer_patch = transfer_patch
        self._publish = publish
        self._failed = failed
        self._handle: ExecutionHandle[_FrameResult, object] | None = None
        self._awaiting_adoption_generation: int | None = None
        self._result: _FrameResult | None = None
        self._patches: tuple[QRect, ...] = ()
        self._next_patch = 0
        self._generation = 0
        self._completed_frames = 0
        self._cancelled_frames = 0
        self._maximum_step_ms = 0.0
        self._maximum_publish_ms = 0.0
        self._maximum_worker_ms = 0.0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._advance_transfer)

    @property
    def pending(self) -> bool:
        """Return whether a complete exact frame is still being composed."""
        handle = self._handle
        return (
            (handle is not None and not handle.state.is_terminal)
            or self._awaiting_adoption_generation is not None
            or self._result is not None
        )

    def begin(
        self,
        plan: SceneRenderPlan,
        *,
        physical_size: QSize,
        device_pixel_ratio: float,
        overscan_physical_px: int,
    ) -> bool:
        """Replace stale work with one exact full-surface composition request."""
        scope = self._execution_scope
        if scope is None:
            return False
        self.cancel()
        request_data = _FrameRequest(
            self._generation,
            plan,
            physical_size,
            device_pixel_ratio,
            overscan_physical_px,
        )
        started = time.perf_counter()
        request = ExecutionRequest[_FrameResult, object](
            operation="render.navigation_frame",
            requirements=ExecutionRequirements(
                resource=ExecutionResource.NATIVE_CPU,
                resource_id=f"{scope.owner_id}:navigation-frame",
                urgency=ExecutionUrgency.INTERACTIVE,
                maximum_concurrency=1,
                estimated_retained_bytes=max(
                    0,
                    physical_size.width() * physical_size.height() * 4,
                ),
            ),
            tags=(("generation", request_data.generation),),
            work=lambda context: _compose_frame(
                request_data,
                context.cancellation,
            ),
        )
        self._awaiting_adoption_generation = request_data.generation
        try:
            handle = scope.submit(request, adopt=self._adopt)
        except ExecutionRejected:
            if self._awaiting_adoption_generation == request_data.generation:
                self._awaiting_adoption_generation = None
            self._maximum_step_ms = max(
                self._maximum_step_ms,
                (time.perf_counter() - started) * 1000.0,
            )
            return False
        self._handle = None if handle.state.is_terminal else handle
        handle.add_done_callback(
            lambda outcome: self._settled(
                handle,
                request_data.generation,
                outcome,
            )
        )
        self._maximum_step_ms = max(
            self._maximum_step_ms,
            (time.perf_counter() - started) * 1000.0,
        )
        return True

    def cancel(self) -> None:
        """Cancel one stale frame without disturbing the presented surface."""
        self._generation += 1
        self._awaiting_adoption_generation = None
        handle = self._handle
        self._handle = None
        cancelled = handle is not None and handle.cancel(
            reason="navigation_frame_replaced"
        )
        if self._result is not None:
            self._timer.stop()
            self._discard()
            self._clear_transfer()
            cancelled = True
        if cancelled:
            self._cancelled_frames += 1

    def snapshot_metrics(self) -> IncrementalFrameMetrics:
        """Return immutable worker lifecycle and GUI latency metrics."""
        return IncrementalFrameMetrics(
            self._completed_frames,
            self._cancelled_frames,
            self._maximum_step_ms,
            self._maximum_publish_ms,
            self._maximum_worker_ms,
        )

    def _adopt(self, result: _FrameResult) -> None:
        """Begin a bounded native transfer for one current worker image."""
        if (
            result.generation != self._generation
            or result.generation != self._awaiting_adoption_generation
        ):
            return
        self._awaiting_adoption_generation = None
        started = time.perf_counter()
        self._prepare()
        self._result = result
        patch_size = _TRANSFER_PATCH_PHYSICAL_PX
        image_rect = result.image.rect()
        self._patches = tuple(
            QRect(column, row, patch_size, patch_size).intersected(image_rect)
            for row in range(image_rect.top(), image_rect.bottom() + 1, patch_size)
            for column in range(
                image_rect.left(),
                image_rect.right() + 1,
                patch_size,
            )
        )
        self._next_patch = 0
        self._maximum_step_ms = max(
            self._maximum_step_ms,
            (time.perf_counter() - started) * 1000.0,
        )
        self._maximum_worker_ms = max(self._maximum_worker_ms, result.worker_ms)
        self._timer.start()

    def _advance_transfer(self) -> None:
        """Copy exact pixels into native staging within one GUI time slice."""
        result = self._result
        if result is None:
            return
        started = time.perf_counter()
        try:
            while self._next_patch < len(self._patches):
                self._transfer_patch(
                    result.image,
                    self._patches[self._next_patch],
                )
                self._next_patch += 1
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                if elapsed_ms >= _TRANSFER_STEP_BUDGET_MS:
                    self._maximum_step_ms = max(self._maximum_step_ms, elapsed_ms)
                    self._timer.start()
                    return
            self._maximum_step_ms = max(
                self._maximum_step_ms,
                (time.perf_counter() - started) * 1000.0,
            )
            publish_started = time.perf_counter()
            self._publish(result.plan)
            self._maximum_publish_ms = max(
                self._maximum_publish_ms,
                (time.perf_counter() - publish_started) * 1000.0,
            )
        except Exception:
            logger.exception("Exact navigation frame transfer failed")
            self._discard()
            self._clear_transfer()
            self._failed()
            return
        self._clear_transfer()
        self._completed_frames += 1

    def _clear_transfer(self) -> None:
        """Release one completed, cancelled, or failed native transfer."""
        self._result = None
        self._patches = ()
        self._next_patch = 0

    def _settled(
        self,
        handle: ExecutionHandle[_FrameResult, object],
        generation: int,
        outcome: ExecutionOutcome[_FrameResult],
    ) -> None:
        """Release the current handle and recover from worker failures."""
        if self._handle is handle:
            self._handle = None
        if (
            generation == self._generation
            and outcome.state is not ExecutionState.SUCCEEDED
            and self._awaiting_adoption_generation == generation
        ):
            self._awaiting_adoption_generation = None
        if generation == self._generation and outcome.state is ExecutionState.FAILED:
            logger.error(
                "Exact navigation frame composition failed: %s",
                outcome.error,
            )
            self._failed()


def _compose_frame(
    request: _FrameRequest,
    cancellation: CancellationToken,
) -> _FrameResult:
    """Compose one complete detached frame with the canonical global phase."""
    cancellation.raise_if_cancelled()
    started = time.perf_counter()
    image = QImage(
        request.physical_size,
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    image.setDevicePixelRatio(request.device_pixel_ratio)
    image.fill(Qt.GlobalColor.transparent)
    logical_width = request.physical_size.width() / request.device_pixel_ratio
    logical_height = request.physical_size.height() / request.device_pixel_ratio
    buffer_rect = QRectF(0.0, 0.0, logical_width, logical_height)
    margin = request.overscan_physical_px / request.device_pixel_ratio
    panel_clip = QRectF(
        -margin,
        -margin,
        logical_width,
        logical_height,
    )
    painter = QPainter(image)
    try:
        painter.setClipRect(buffer_rect)
        painter.translate(QPointF(margin, margin))
        SceneItemCompositor().draw_visible_items(
            painter,
            request.plan,
            panel_clips=(panel_clip,),
        )
    finally:
        painter.end()
    cancellation.raise_if_cancelled()
    return _FrameResult(
        request.generation,
        request.plan,
        image,
        (time.perf_counter() - started) * 1000.0,
    )
