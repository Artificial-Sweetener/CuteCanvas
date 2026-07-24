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
"""Asynchronous mask render-work scheduling and result coordination."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QImage
from qpane.sdk.concurrency import TaskExecutorProtocol, TaskHandle, TaskRejected
from qpane.sdk.raster import (
    numpy_to_qimage_grayscale8,
)
from qpane.sdk.scene import RasterBounds

from .mask import MaskAssetStore, MaskLayer
from .mask_controller import MaskController
from .workers import MaskPrefetchWorker, MaskSnippetWorker, PrefetchedOverlay

logger = logging.getLogger(__name__)


SNIPPET_ASYNC_THRESHOLD_PX = 512 * 512


@dataclass(frozen=True, slots=True)
class MaskRenderWorkStats:
    """Bookkeeping for mask prefetch activity surfaced in diagnostics."""

    scheduled: int = 0
    completed: int = 0
    skipped: int = 0
    failed: int = 0
    last_message: str | None = None
    last_duration_ms: float | None = None


@dataclass(frozen=True, slots=True)
class _PrefetchHandle:
    """Track one queued prefetch and the render revisions it owns."""

    handle: TaskHandle
    mask_revisions: tuple[tuple[uuid.UUID, int], ...]


class MaskRenderWorkCoordinator:
    """Own asynchronous mask render scheduling, cancellation, and completion."""

    def __init__(
        self,
        *,
        assets: MaskAssetStore,
        controller: MaskController,
        executor: TaskExecutorProtocol | None,
        mask_ids_for_composition: Callable[[uuid.UUID], list[uuid.UUID]],
        composition_ids_for_mask: Callable[[uuid.UUID], tuple[uuid.UUID, ...]],
        current_composition_id: Callable[[], uuid.UUID | None],
        current_zoom: Callable[[], float],
        should_defer_prefetch: Callable[[uuid.UUID | None, uuid.UUID], bool],
        is_mask_busy: Callable[[uuid.UUID], bool],
        publish_status: Callable[..., None],
    ) -> None:
        """Store render-work collaborators and initialize owned task state."""
        self._assets = assets
        self._controller = controller
        self._executor = executor
        self._mask_ids_for_composition = mask_ids_for_composition
        self._composition_ids_for_mask = composition_ids_for_mask
        self._current_composition_id = current_composition_id
        self._current_zoom = current_zoom
        self._should_defer_prefetch = should_defer_prefetch
        self._is_mask_busy = is_mask_busy
        self._publish_status = publish_status
        self._enabled = True
        self._cancelled_task_ids: set[str] = set()
        self._prefetch_handles: dict[uuid.UUID, _PrefetchHandle] = {}
        self._snippet_handles: dict[uuid.UUID, TaskHandle] = {}
        self._deferred_overlays: dict[uuid.UUID, PrefetchedOverlay] = {}
        self._skipped = 0
        self._submission_failures = 0
        self._last_message: str | None = None
        self._last_duration_ms: float | None = None
        self._prefetch_scales: tuple[float, ...] = (0.5, 0.25)

    @property
    def enabled(self) -> bool:
        """Return whether asynchronous mask prefetch is enabled."""
        return self._enabled

    @property
    def stats(self) -> MaskRenderWorkStats:
        """Return one snapshot combining render metrics and scheduling state."""
        metrics = self._controller.renders.snapshot_metrics()
        return MaskRenderWorkStats(
            scheduled=metrics.prefetch_requested,
            completed=metrics.prefetch_completed,
            skipped=self._skipped,
            failed=metrics.prefetch_failed + self._submission_failures,
            last_message=self._last_message,
            last_duration_ms=self._last_duration_ms,
        )

    def has_pending_work(self) -> bool:
        """Return whether snippet, prefetch, or deferred render work remains."""
        return bool(
            self._snippet_handles or self._prefetch_handles or self._deferred_overlays
        )

    def is_prefetch_pending(self, image_id: uuid.UUID) -> bool:
        """Return whether image_id has an owned prefetch task."""
        return image_id in self._prefetch_handles

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable asynchronous mask render prefetch."""
        enabled = bool(enabled)
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if not enabled:
            self.cancel_prefetch(None)
            message = "Mask prefetch disabled; pending jobs cancelled."
            logger.info("Mask prefetch disabled; pending jobs cancelled")
        else:
            message = "Mask prefetch enabled."
            logger.info("Mask prefetch enabled")
        self._last_message = message
        self._last_duration_ms = None
        self._publish_status(message, label="Mask Prefetch")

    def resolve_prefetch_scales(
        self, scales: Sequence[float] | None
    ) -> tuple[float, ...]:
        """Normalize and de-duplicate requested overlay scales."""
        candidate = scales if scales is not None else self._prefetch_scales
        normalized: list[float] = []
        seen: set[float] = set()
        for value in candidate:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            scale_key = self._controller.renders.normalize_scale(numeric)
            if scale_key is None or scale_key in seen:
                continue
            seen.add(scale_key)
            normalized.append(scale_key)
        return tuple(normalized)

    def prefetch(
        self,
        image_id: uuid.UUID | None,
        *,
        reason: str = "navigation",
        scales: Sequence[float] | None = None,
    ) -> bool:
        """Warm mask renders for image_id using the background executor."""
        if not self._enabled:
            logger.debug("Mask prefetch skipped for %s: disabled", image_id)
            return False
        executor = self._executor
        if executor is None:
            logger.debug("Mask prefetch skipped for %s: executor unavailable", image_id)
            return False
        if image_id is None:
            return False
        mask_ids = [
            mask_id
            for mask_id in self._mask_ids_for_composition(image_id)
            if (
                (layer := self._assets.get_layer(mask_id)) is not None
                and not layer.coverage.has_retained_items
            )
        ]
        prefetch_scales = self.resolve_prefetch_scales(scales)
        if not mask_ids:
            self._record_skip(
                f"No masks to prefetch for image {self._format_uuid(image_id)}."
            )
            return False
        active_mask_id = self._controller.get_active_mask_id()
        next_top_mask = mask_ids[-1]
        if self._should_defer_prefetch(active_mask_id, next_top_mask):
            self._record_skip(
                "Prefetch deferred for image "
                f"{self._format_uuid(image_id)}; activation will run synchronously."
            )
            return False
        self.cancel_prefetch(image_id)
        worker = MaskPrefetchWorker(
            image_id=image_id,
            mask_ids=tuple(mask_ids),
            mask_manager=self._assets,
            controller=self._controller,
            coordinator=self,
            current_image_id=self._current_composition_id(),
            scales=prefetch_scales,
        )
        try:
            handle = executor.submit(worker, category="mask_prefetch")
        except Exception as exc:
            self._submission_failures += len(mask_ids)
            message = (
                f"Prefetch rejected for image {self._format_uuid(image_id)}: {exc}"
            )
            self._last_message = message
            self._last_duration_ms = None
            self._publish_status(message, label="Mask Prefetch Error")
            logger.exception("Failed to queue mask prefetch for image %s", image_id)
            return False
        worker.set_task_id(handle.task_id)
        mask_revisions = tuple(
            (mask_id, self._controller.renders.render_revision(mask_id))
            for mask_id in mask_ids
        )
        count = len(mask_revisions)
        self._prefetch_handles[image_id] = _PrefetchHandle(
            handle=handle,
            mask_revisions=mask_revisions,
        )
        self._last_message = (
            f"Prefetch queued for {count} mask(s) on {self._format_uuid(image_id)}."
        )
        self._last_duration_ms = None
        self._controller.renders.record_prefetch_request(count)
        self._publish_status(self._last_message, label="Mask Prefetch")
        logger.info(
            "Queued mask prefetch for image %s (%d mask(s), reason=%s)",
            image_id,
            count,
            reason,
        )
        return True

    def cancel_prefetch(self, image_id: uuid.UUID | None) -> bool:
        """Cancel queued mask prefetch work for image_id or for every image."""
        if image_id is None:
            cancelled_any = False
            for candidate in list(self._prefetch_handles):
                cancelled_any = self.cancel_prefetch(candidate) or cancelled_any
            return cancelled_any
        handle_entry = self._prefetch_handles.pop(image_id, None)
        if handle_entry is None:
            return False
        handle = handle_entry.handle
        mask_revisions = handle_entry.mask_revisions
        cancelled = False
        if self._executor is not None:
            try:
                cancelled = self._executor.cancel(handle)
            except Exception:
                logger.debug("Mask prefetch cancellation failed", exc_info=True)
        if cancelled:
            message = f"Prefetch cancelled for {self._format_uuid(image_id)}."
        else:
            message = (
                "Prefetch cancellation requested for "
                f"{self._format_uuid(image_id)}; task already running."
            )
        self._last_message = message
        self._last_duration_ms = None
        self._publish_status(message, label="Mask Prefetch")
        (logger.info if cancelled else logger.debug)(
            "Mask prefetch cancellation for image %s (cancelled=%s)",
            image_id,
            cancelled,
        )
        self._cancelled_task_ids.add(handle.task_id)
        metrics = self._controller.renders.snapshot_metrics()
        outstanding = metrics.prefetch_requested - (
            metrics.prefetch_completed + metrics.prefetch_failed
        )
        failed = min(len(mask_revisions), max(0, outstanding))
        if failed > 0:
            self._controller.renders.record_prefetch_completion(
                completed=0, failed=failed
            )
        for mask_id, render_revision in mask_revisions:
            self._controller.renders.complete_async(mask_id, render_revision)
        return cancelled

    def prioritize_interaction(self, mask_id: uuid.UUID) -> None:
        """Cancel competing derived work before direct mask interaction begins."""
        image_id = self._resolve_image_id(mask_id)
        if image_id is not None:
            self.cancel_prefetch(image_id)
        handle = self._snippet_handles.pop(mask_id, None)
        if handle is not None and self._executor is not None:
            try:
                self._executor.cancel(handle)
            except Exception:
                logger.debug("Mask snippet cancellation failed", exc_info=True)
        self._controller.renders.cancel_async(mask_id)

    def update_region(
        self,
        dirty_image_rect: QRect,
        mask_layer: MaskLayer,
        *,
        sub_mask_image: QImage | None = None,
        force_async_colorize: bool = False,
    ) -> None:
        """Update a dirty render region and schedule full-quality work as needed."""
        if mask_layer is None or dirty_image_rect.isNull():
            return
        mask_id = mask_layer.mask_id
        zoom = self._current_zoom() or 1.0
        if zoom <= 0.0:
            zoom = 1.0
        stride = max(1, round(1.0 / max(zoom, 1e-6))) if zoom < 1.0 else 1
        if sub_mask_image is None:
            sub_mask_image = self._snapshot_region(
                mask_layer,
                dirty_image_rect,
                stride=stride,
            )
            if sub_mask_image is not None and stride > 1:
                sub_mask_image.setText("qpane_preview_stride", str(stride))
                sub_mask_image.setText("qpane_preview_provisional", "1")
        snippet_source = sub_mask_image
        async_snippet = snippet_source
        if force_async_colorize:
            async_snippet = self._snapshot_region(
                mask_layer,
                dirty_image_rect,
                stride=1,
            )
        async_available = async_snippet is not None and not async_snippet.isNull()
        area = dirty_image_rect.width() * dirty_image_rect.height()
        should_request_async = (
            mask_id is not None
            and async_available
            and self._executor is not None
            and (
                force_async_colorize
                or (sub_mask_image is None and area > SNIPPET_ASYNC_THRESHOLD_PX)
            )
        )
        scheduled = False
        if should_request_async:
            scheduled = self.schedule_snippet(
                mask_id,
                dirty_image_rect,
                mask_layer,
                async_snippet,
            )
        if sub_mask_image is not None or not scheduled:
            self._controller.renders.update_region(
                dirty_image_rect,
                mask_layer,
                sub_mask_image=sub_mask_image,
            )

    def request_async_colorize(self, mask_id: uuid.UUID, mask_layer: MaskLayer) -> bool:
        """Queue asynchronous colorization for a full-mask cache miss."""
        render_revision = self._controller.renders.render_revision(mask_id)
        bounds = mask_layer.coverage.raster.bounds
        if bounds is None:
            self._controller.renders.complete_async(mask_id, render_revision)
            return False
        image_id = self._resolve_image_id(mask_id)
        if image_id is not None and self.prefetch(
            image_id,
            reason="cache-miss",
            scales=self._prefetch_scales,
        ):
            return True
        scheduled = self.schedule_snippet(
            mask_id,
            QRect(0, 0, bounds.width, bounds.height),
            mask_layer,
            mask_layer.mask_image.copy(),
        )
        if not scheduled:
            self._controller.renders.complete_async(mask_id, render_revision)
        return scheduled

    @staticmethod
    def _snapshot_region(
        mask_layer: MaskLayer,
        dirty_rect: QRect,
        *,
        stride: int,
    ) -> QImage | None:
        """Copy only a requested storage region for derived render work."""
        bounds = mask_layer.coverage.raster.bounds
        if bounds is None:
            return None
        storage_rect = QRect(0, 0, bounds.width, bounds.height)
        region = dirty_rect.intersected(storage_rect)
        if region.isNull() or region.isEmpty():
            return None
        pixels = mask_layer.coverage.raster.snapshot_storage_region(
            RasterBounds.from_qrect(region),
            stride=max(1, stride),
        )
        return numpy_to_qimage_grayscale8(pixels)

    def schedule_snippet(
        self,
        mask_id: uuid.UUID,
        dirty_image_rect: QRect,
        mask_layer: MaskLayer,
        snippet: QImage,
    ) -> bool:
        """Dispatch a snippet colorization worker for the dirty mask region."""
        if self._executor is None:
            return False
        render_revision = self._controller.renders.render_revision(mask_id)
        worker = MaskSnippetWorker(
            mask_id=mask_id,
            render_revision=render_revision,
            dirty_rect=QRect(dirty_image_rect),
            snippet=snippet,
            color=self._controller.color_for_mask(mask_id),
            controller=self._controller,
            coordinator=self,
        )
        previous = self._snippet_handles.pop(mask_id, None)
        if previous is not None:
            try:
                self._executor.cancel(previous)
            except Exception:
                logger.debug("Previous mask snippet cancellation failed", exc_info=True)
        try:
            handle = self._executor.submit(worker, category="mask_snippet")
        except TaskRejected as exc:
            message = (
                "Mask snippet colorization rejected for mask "
                f"{self._format_uuid(mask_id)}: {exc}"
            )
            logger.debug(message)
            self._publish_status(message, label="Mask Snippet Error")
            return False
        self._snippet_handles[mask_id] = handle
        return True

    def consume_snippet_result(
        self,
        *,
        mask_id: uuid.UUID,
        render_revision: int,
        handle: TaskHandle | None,
        dirty_rect: QRect,
        colorized_image: QImage | None,
        colorize_duration_ms: float | None = None,
    ) -> None:
        """Apply snippet colorization results and finalize async notifications."""
        if handle is not None:
            current = self._snippet_handles.get(mask_id)
            if current is None or current.task_id != handle.task_id:
                return
            self._snippet_handles.pop(mask_id, None)
        if render_revision != self._controller.renders.render_revision(
            mask_id
        ) or self._is_mask_busy(mask_id):
            self._controller.renders.complete_async(mask_id, render_revision)
            return
        if colorize_duration_ms is not None:
            self._controller.renders.record_background_colorize(
                colorize_duration_ms,
                source="snippet_async",
            )
        mask_layer = self._assets.get_layer(mask_id)
        if mask_layer is None:
            self._controller.renders.complete_async(mask_id, render_revision)
            return
        if colorized_image is None or colorized_image.isNull():
            self._controller.renders.update_region(dirty_rect, mask_layer)
        elif (
            mask_layer.coverage.raster.bounds is not None
            and dirty_rect
            == QRect(
                0,
                0,
                mask_layer.coverage.raster.bounds.width,
                mask_layer.coverage.raster.bounds.height,
            )
            and colorized_image.size()
            == QSize(
                mask_layer.coverage.raster.bounds.width,
                mask_layer.coverage.raster.bounds.height,
            )
        ):
            self._controller.renders.commit_native(
                mask_id,
                mask_layer,
                colorized_image,
            )
        else:
            self._controller.renders.update_region(
                dirty_rect,
                mask_layer,
                colorized_image=colorized_image,
            )
        self._controller.renders.complete_async(mask_id, render_revision)

    def consume_prefetch_results(
        self,
        *,
        image_id: uuid.UUID,
        warmed: Sequence[PrefetchedOverlay],
        failures: Mapping[uuid.UUID, str],
        duration_ms: float,
        error: BaseException | None,
        task_id: str | None = None,
    ) -> None:
        """Commit prefetched overlays and update diagnostics on the main thread."""
        active_handle = self._prefetch_handles.get(image_id)
        if task_id is not None and (
            active_handle is None or active_handle.handle.task_id != task_id
        ):
            self._cancelled_task_ids.discard(task_id)
            return
        owned_revisions = (
            dict(active_handle.mask_revisions)
            if active_handle is not None
            else {overlay.mask_id: overlay.render_revision for overlay in warmed}
        )
        self._prefetch_handles.pop(image_id, None)
        if task_id is not None and task_id in self._cancelled_task_ids:
            self._cancelled_task_ids.discard(task_id)
            return
        failure_messages = dict(failures)
        completed = 0
        deferred_mask_ids: set[uuid.UUID] = set()
        for overlay in warmed:
            mask_id = overlay.mask_id
            layer = self._assets.get_layer(mask_id)
            if layer is None or overlay.image.isNull():
                failure_messages[mask_id] = "layer unavailable"
                continue
            if not self._overlay_is_current(overlay):
                continue
            if overlay.colorize_duration_ms is not None:
                self._controller.renders.record_background_colorize(
                    overlay.colorize_duration_ms,
                    source="prefetch",
                )
            if self._is_mask_busy(mask_id):
                self._deferred_overlays[mask_id] = overlay
                deferred_mask_ids.add(mask_id)
                completed += 1
                continue
            self._controller.renders.commit_prefetched(
                mask_id,
                layer,
                overlay.image,
                scaled=overlay.scaled,
            )
            completed += 1
        for mask_id, render_revision in owned_revisions.items():
            if mask_id not in deferred_mask_ids:
                self._controller.renders.complete_async(mask_id, render_revision)
        if error is not None:
            failure_messages["worker"] = str(error)
        failure_count = len(failure_messages)
        duration_value = duration_ms if (completed or failure_count) else None
        self._controller.renders.record_prefetch_completion(
            completed=completed,
            failed=failure_count,
            duration_ms=duration_value,
        )
        summary_prefix = f"Prefetch warmed {completed} mask(s)"
        if failure_count:
            summary = (
                f"{summary_prefix} with {failure_count} failure(s) for "
                f"{self._format_uuid(image_id)}"
            )
        elif completed:
            summary = f"{summary_prefix} for {self._format_uuid(image_id)}"
        else:
            summary = f"Prefetch found cached renders for {self._format_uuid(image_id)}"
        if duration_ms is not None:
            summary = f"{summary} ({duration_ms:.1f} ms)"
        self._last_message = summary
        self._last_duration_ms = duration_ms
        if failure_count:
            label = "Mask Prefetch Error"
            logger.warning(
                "Mask prefetch completed with %d failure(s) for image %s",
                failure_count,
                image_id,
            )
            for failed_mask, failure_reason in failure_messages.items():
                logger.debug(
                    "Prefetch failure detail for %s: %s",
                    failed_mask,
                    failure_reason,
                )
        else:
            label = "Mask Prefetch"
            logger.info(
                "Mask prefetch completed for image %s (masks=%d)",
                image_id,
                completed,
            )
        self._publish_status(summary, label=label)
        for overlay in warmed:
            self.apply_deferred(overlay.mask_id)

    def handle_mask_idle(self, mask_id: uuid.UUID) -> None:
        """Apply deferred prefetch work once stroke work for mask_id completes."""
        try:
            self.apply_deferred(mask_id)
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "Deferred prefetch application failed for mask %s", mask_id
            )

    def apply_deferred(self, mask_id: uuid.UUID | None) -> bool:
        """Apply a stashed prefetched overlay when the mask is idle."""
        if mask_id is None or self._is_mask_busy(mask_id):
            return False
        overlay = self._deferred_overlays.pop(mask_id, None)
        if overlay is None:
            return False
        try:
            if not self._overlay_is_current(overlay):
                return False
            layer = self._assets.get_layer(mask_id)
            if layer is None or overlay.image.isNull():
                return False
            self._controller.renders.commit_prefetched(
                mask_id,
                layer,
                overlay.image,
                scaled=overlay.scaled,
            )
            return True
        finally:
            self._controller.renders.complete_async(
                mask_id,
                overlay.render_revision,
            )

    def discard_deferred(self, mask_id: uuid.UUID) -> None:
        """Discard deferred render work for an invalidated mask."""
        self._deferred_overlays.pop(mask_id, None)

    def diagnostics_summary(self) -> str:
        """Return a human-friendly description of current prefetch state."""
        state = "Enabled" if self._enabled else "Disabled"
        message = self._last_message or "No activity"
        if self._last_duration_ms is not None:
            message = f"{message} ({self._last_duration_ms:.1f} ms)"
        return f"{state} - {message}"

    def _record_skip(self, message: str) -> None:
        """Record a prefetch request that cannot be scheduled."""
        self._skipped += 1
        self._last_message = message
        self._last_duration_ms = None
        self._publish_status(message, label="Mask Prefetch")

    def _resolve_image_id(self, mask_id: uuid.UUID) -> uuid.UUID | None:
        """Return a likely image identifier for mask_id when available."""
        composition_ids = self._composition_ids_for_mask(mask_id)
        if composition_ids:
            return composition_ids[-1]
        try:
            return self._current_composition_id()
        except RuntimeError:  # pragma: no cover - widget teardown
            return None

    def _overlay_is_current(self, overlay: PrefetchedOverlay) -> bool:
        """Return whether an overlay still matches authoritative mask state."""
        return overlay.render_revision == self._controller.renders.render_revision(
            overlay.mask_id
        )

    @staticmethod
    def _format_uuid(value: uuid.UUID | None) -> str:
        """Return a short, diagnostics-friendly representation of value."""
        if isinstance(value, uuid.UUID):
            return value.hex[:8].upper()
        return "None"
