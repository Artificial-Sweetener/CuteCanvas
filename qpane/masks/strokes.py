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

"""Stroke queueing and preview helpers owned by the mask workflow."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass, field, replace
from itertools import count
from uuid import UUID

import numpy as np
from PySide6.QtCore import QRect

from ..concurrency import TaskExecutorProtocol, TaskHandle
from ..coverage import CoverageSnapshot
from ..scene.raster import RasterBounds
from .mask import MaskAssetStore
from .mask_controller import MaskController
from .mask_diagnostics import MaskStrokeDiagnostics
from .stroke_models import (
    MaskStrokeJobResult,
    MaskStrokeJobSpec,
    MaskStrokeSegmentPayload,
)
from .stroke_preview import DecimatedStrokePreview
from .stroke_regions import MaskStrokeRegionPlanner
from .stroke_worker import MaskStrokeWorker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MaskStrokeDebugSnapshot:
    """Represent pending stroke bookkeeping for assertions and diagnostics."""

    preview_state_ids: tuple[UUID, ...] = ()
    preview_tokens: dict[UUID, int] = field(default_factory=dict)
    pending_jobs: dict[UUID, tuple[TaskHandle, ...]] = field(default_factory=dict)
    invalidated_job_tokens: tuple[tuple[UUID, int], ...] = ()


class MaskStrokePipeline:
    """Own mask stroke preview state, worker submission, and diagnostics."""

    def __init__(
        self,
        *,
        assets: MaskAssetStore,
        controller: MaskController,
        executor: TaskExecutorProtocol | None,
        mask_feature_available: Callable[[], bool],
        current_image_id: Callable[[], UUID | None],
        ensure_active: Callable[[UUID | None], bool],
        mask_ids_for_image: Callable[[UUID], list[UUID]],
        view: Callable[[], object],
        update_region: Callable[..., None],
        diagnostics: MaskStrokeDiagnostics | None = None,
        selection_constraint: Callable[[UUID], CoverageSnapshot | None] | None = None,
    ) -> None:
        """Initialize stroke pipeline state, tokens, and optional diagnostics."""
        self._assets = assets
        self._controller = controller
        self._task_executor = executor
        self._mask_feature_available = mask_feature_available
        self._current_image_id = current_image_id
        self._ensure_active = ensure_active
        self._mask_ids_for_image = mask_ids_for_image
        self._view = view
        self._update_region = update_region
        self._region_planner = MaskStrokeRegionPlanner(
            controller.edits.prepare_writable_region
        )
        self._preview_states: dict[UUID, DecimatedStrokePreview] = {}
        self._preview_tokens: dict[UUID, int] = {}
        self._pending_jobs: dict[UUID, set[TaskHandle]] = {}
        self._pending_job_tokens: dict[TaskHandle, int] = {}
        self._invalidated_job_tokens: set[tuple[UUID, int]] = set()
        self._job_token_counter = count(1)
        self._diagnostics = diagnostics
        self._selection_constraint = selection_constraint or (lambda _mask_id: None)
        self._idle_callback: Callable[[UUID], None] | None = None

    @property
    def diagnostics(self) -> MaskStrokeDiagnostics | None:
        """Return the diagnostics tracker backing stroke metrics when set."""
        return self._diagnostics

    def set_diagnostics(self, tracker: MaskStrokeDiagnostics | None) -> None:
        """Replace the diagnostics tracker used for job telemetry."""
        self._diagnostics = tracker

    def set_idle_callback(self, callback: Callable[[UUID], None] | None) -> None:
        """Register a callback invoked when a mask finishes stroke work."""
        self._idle_callback = callback

    def set_selection_constraint(
        self,
        provider: Callable[[UUID], CoverageSnapshot | None] | None,
    ) -> None:
        """Replace the composition-owned mask stroke constraint provider."""
        self._selection_constraint = provider or (lambda _mask_id: None)

    def is_mask_busy(self, mask_id: UUID) -> bool:
        """Return True when a mask tracks preview state or pending jobs."""
        if mask_id in self._preview_states:
            return True
        if mask_id in self._preview_tokens:
            return True
        pending = self._pending_jobs.get(mask_id)
        return bool(pending)

    def configure_diagnostics(self, *, enabled: bool) -> None:
        """Apply runtime toggles to the current diagnostics tracker."""
        tracker = self._diagnostics
        if tracker is None:
            return
        tracker.configure(enabled=enabled)

    def diagnostics_snapshot(self):
        """Return the snapshot emitted by the diagnostics tracker when available."""
        tracker = self._diagnostics
        if tracker is None:
            return None
        return tracker.snapshot()

    def debug_snapshot(self) -> MaskStrokeDebugSnapshot:
        """Expose pending state for tests without leaking internal dicts."""
        pending = {
            mask_id: tuple(handles)
            for mask_id, handles in self._pending_jobs.items()
            if handles
        }
        return MaskStrokeDebugSnapshot(
            preview_state_ids=tuple(self._preview_states.keys()),
            preview_tokens=dict(self._preview_tokens),
            pending_jobs=pending,
            invalidated_job_tokens=tuple(self._invalidated_job_tokens),
        )

    def reset_state(
        self,
        mask_id: UUID | None,
        *,
        clear_counter: bool = False,
        request_redraw: bool = True,
    ) -> None:
        """Cancel pending stroke jobs and drop preview state."""
        preview_states: MutableMapping[UUID, DecimatedStrokePreview] = (
            self._preview_states
        )
        preview_tokens: MutableMapping[UUID, int] = self._preview_tokens
        pending_jobs = self._pending_jobs
        pending_job_tokens = self._pending_job_tokens
        invalidated_job_tokens = self._invalidated_job_tokens
        executor = self._executor
        manager = self._assets
        diagnostics = self._diagnostics
        target_ids: set[UUID] = set()
        if mask_id is None:
            target_ids.update(preview_states.keys())
            target_ids.update(preview_tokens.keys())
            target_ids.update(pending_jobs.keys())
        else:
            target_ids.add(mask_id)
        for target in tuple(target_ids):
            had_state = False
            handles = pending_jobs.get(target)
            had_pending_jobs = bool(handles)
            if handles:
                had_state = True
                for handle in tuple(handles):
                    job_token = pending_job_tokens.pop(handle, None)
                    cancelled = False
                    if executor is not None and hasattr(executor, "cancel"):
                        try:
                            cancelled = bool(executor.cancel(handle))
                        except Exception:  # pragma: no cover - defensive guard
                            logger.debug(
                                "Failed to cancel pending mask stroke job (mask=%s).",
                                target,
                                exc_info=True,
                            )
                    if not cancelled and job_token is not None:
                        invalidated_job_tokens.add((target, job_token))
                handles.clear()
                pending_jobs.pop(target, None)
            else:
                pending_jobs.pop(target, None)
            preview_state = preview_states.pop(target, None)
            preview_dirty_rect = (
                None if preview_state is None else preview_state.dirty_rect()
            )
            if preview_state is not None:
                had_state = True
            if target in preview_tokens:
                had_state = True
                preview_tokens.pop(target, None)
            if had_state:
                if request_redraw and manager is not None:
                    layer = manager.get_layer(target)
                    if layer is not None and not layer.mask_image.isNull():
                        if had_pending_jobs or preview_dirty_rect is None:
                            self._update_region(layer.mask_image.rect(), layer)
                        else:
                            durable_region = layer.mask_image.copy(preview_dirty_rect)
                            self._update_region(
                                preview_dirty_rect,
                                layer,
                                sub_mask_image=durable_region,
                            )
                if diagnostics is not None:
                    diagnostics.cancel_mask_jobs(target)
        if mask_id is None:
            pending_jobs.clear()
            pending_job_tokens.clear()
            preview_states.clear()
            preview_tokens.clear()
            if clear_counter and not invalidated_job_tokens:
                self._job_token_counter = count(1)
                if diagnostics is not None:
                    diagnostics.reset()
        elif clear_counter and not invalidated_job_tokens:
            self._job_token_counter = count(1)
        for target in target_ids:
            self._notify_idle_if_clear(target)

    @property
    def _executor(self) -> TaskExecutorProtocol | None:
        """Return the executor used for background stroke work."""
        return self._task_executor

    def _allocate_job_token(self) -> int:
        """Return the next stroke job token for diagnostics and ordering."""
        return next(self._job_token_counter)

    def _register_job_token(self, mask_id: UUID, token: int) -> int | None:
        """Record the current preview token for ``mask_id`` and return the previous."""
        previous = self._preview_tokens.get(mask_id)
        self._preview_tokens[mask_id] = token
        return previous

    def _restore_job_token(self, mask_id: UUID, token: int | None) -> None:
        """Restore or clear the preview token for ``mask_id`` after a submit."""
        if token is None:
            self._preview_tokens.pop(mask_id, None)
        else:
            self._preview_tokens[mask_id] = token

    def _submit_stroke_job(
        self,
        spec: MaskStrokeJobSpec,
        *,
        source: str,
        commit: bool,
        job_token: int,
    ) -> bool:
        """Queue a stroke worker and wire finalize callbacks/diagnostics."""
        executor = self._executor
        handle_box: dict[str, TaskHandle | None] = {"handle": None}
        completed = {"value": False}
        diagnostics = self._diagnostics
        pending_jobs = self._pending_jobs
        if diagnostics is not None:
            pending_handles = pending_jobs.get(spec.mask_id)
            pending_count = len(pending_handles) if pending_handles else 0
            stride_value = None
            metadata_mapping = (
                spec.metadata if isinstance(spec.metadata, Mapping) else None
            )
            if metadata_mapping is not None:
                stride_candidate = metadata_mapping.get("stride")
                try:
                    stride_value = int(stride_candidate)
                except (TypeError, ValueError):
                    stride_value = None
            diagnostics.record_submitted(
                mask_id=spec.mask_id,
                job_token=job_token,
                generation=spec.generation,
                pending_count=pending_count,
                source=source,
                stride=stride_value,
            )

        def finalize(result: MaskStrokeJobResult) -> None:
            """Finalize stroke results and propagate completion state."""
            completed["value"] = True
            self._finalize_stroke_result(
                result,
                handle=handle_box["handle"],
                commit=commit,
            )

        logger.debug(
            "queue stroke job mask=%s gen=%s token=%s source=%s",
            spec.mask_id,
            spec.generation,
            job_token,
            source,
        )
        worker = MaskStrokeWorker(spec=spec, finalize=finalize)
        if executor is None:
            worker.run()
            return True
        try:
            handle = executor.submit(
                worker,
                category="mask_stroke",
                device=str(spec.mask_id),
            )
        except Exception:
            logger.exception(
                "Failed to queue mask stroke worker (mask=%s source=%s); executing synchronously.",
                spec.mask_id,
                source,
            )
            worker.run()
            return True
        handle_box["handle"] = handle
        if not completed["value"]:
            pending = pending_jobs.setdefault(spec.mask_id, set())
            pending.add(handle)
            self._pending_job_tokens[handle] = job_token
        return True

    def _finalize_stroke_result(
        self,
        result: MaskStrokeJobResult,
        *,
        handle: TaskHandle | None,
        commit: bool,
    ) -> None:
        """Merge a completed stroke, update diagnostics, and clean pending state."""
        controller = self._controller
        mask_id = result.mask_id
        diagnostics = self._diagnostics
        log_fn = logger.debug
        pending = self._pending_jobs.get(mask_id)
        if pending is not None:
            if handle is not None:
                pending.discard(handle)
            if not pending:
                self._pending_jobs.pop(mask_id, None)
        metadata_mapping = (
            result.metadata if isinstance(result.metadata, Mapping) else {}
        )
        job_token = metadata_mapping.get("job_token")
        if handle is not None:
            self._pending_job_tokens.pop(handle, None)

        def _clear_pending_token(target_mask_id: UUID, token_value: int | None) -> None:
            """Drop preview token if it matches the finalized job token."""
            if token_value is None:
                return
            if self._preview_tokens.get(target_mask_id) == token_value:
                self._preview_tokens.pop(target_mask_id, None)

        def _record_completion(
            status: str,
            *,
            detail: str | None = None,
            target_mask_id: UUID | None = mask_id,
            token_value: int | None = job_token,
        ) -> None:
            """Record a completed job outcome with optional detail."""
            if diagnostics is None:
                return
            diagnostics.record_completed(
                mask_id=target_mask_id,
                job_token=token_value,
                status=status,
                detail=detail,
            )

        def _record_drop(
            reason: str,
            *,
            detail: str | None = None,
            target_mask_id: UUID | None = mask_id,
            token_value: int | None = job_token,
        ) -> None:
            """Record a dropped job outcome with optional detail."""
            if diagnostics is None:
                return
            diagnostics.record_drop(
                mask_id=target_mask_id,
                job_token=token_value,
                reason=reason,
                detail=detail,
            )

        def _notify_idle() -> None:
            """Trigger idle callback when no pending work remains for mask."""
            self._notify_idle_if_clear(mask_id)

        invalidated_token = (mask_id, job_token) if isinstance(job_token, int) else None
        if (
            invalidated_token is not None
            and invalidated_token in self._invalidated_job_tokens
        ):
            self._invalidated_job_tokens.discard(invalidated_token)
            _clear_pending_token(mask_id, job_token)
            _record_drop("invalidated_job", detail="reset_state")
            _notify_idle()
            return

        mask_manager = self._assets
        mask_layer = mask_manager.get_layer(mask_id)
        if mask_layer is None:
            logger.warning(
                "Mask stroke finalizer skipped: layer missing (mask=%s).",
                mask_id,
            )
            _clear_pending_token(mask_id, job_token)
            _record_drop("missing_layer")
            _notify_idle()
            return
        active_mask_id = controller.get_active_mask_id()
        if commit and active_mask_id is not None and active_mask_id != mask_id:
            logger.info(
                "Discarding stroke finalize for mask %s; active mask changed to %s.",
                mask_id,
                active_mask_id,
            )
            self._update_region(result.dirty_rect, mask_layer)
            controller.edits.commit_stroke(mask_id)
            _clear_pending_token(mask_id, job_token)
            _record_drop(
                "mask_changed",
                detail=f"active={active_mask_id}",
            )
            _notify_idle()
            return
        expected_generation = controller.edits.async_epoch(mask_id)
        allow_rebase = bool(metadata_mapping.get("allow_generation_rebase"))
        if result.generation != expected_generation:
            if result.generation > expected_generation:
                logger.debug(
                    "clamping future stroke job generation (mask=%s job_gen=%s expected=%s)",
                    mask_id,
                    result.generation,
                    expected_generation,
                )
                job_result = replace(result, generation=expected_generation)
            elif allow_rebase and result.generation < expected_generation:
                logger.debug(
                    "rebasing stroke job generation (mask=%s job_gen=%s expected=%s)",
                    mask_id,
                    result.generation,
                    expected_generation,
                )
                job_result = replace(result, generation=expected_generation)
            else:
                job_result = result
        else:
            job_result = result

        def _on_stale(
            stale_job: MaskStrokeJobResult,
            *,
            reason: str = "stale_generation",
            detail: str | None = None,
        ) -> None:
            """Handle stale results by reverting preview state and logging drops."""
            stale_metadata = stale_job.metadata
            stale_token = (
                stale_metadata.get("job_token")
                if isinstance(stale_metadata, Mapping)
                else None
            )
            _clear_pending_token(stale_job.mask_id, stale_token)
            latest_layer = mask_manager.get_layer(stale_job.mask_id)
            if latest_layer is not None:
                self._update_region(stale_job.dirty_rect, latest_layer)
                self._refresh_active_preview(stale_job.mask_id, latest_layer)
            if diagnostics is not None:
                diagnostics.record_drop(
                    mask_id=stale_job.mask_id,
                    job_token=stale_token,
                    reason=reason,
                    detail=detail,
                )
            self._notify_idle_if_clear(stale_job.mask_id)

        expected_token = self._preview_tokens.get(mask_id)
        if (
            job_token is not None
            and expected_token is not None
            and job_token != expected_token
        ):
            log_fn(
                "stroke finalize dropped due to stale token (mask=%s job_token=%s expected=%s)",
                mask_id,
                job_token,
                expected_token,
            )
            _on_stale(
                job_result,
                reason="stale_token",
                detail=f"expected={expected_token}",
            )
            _notify_idle()
            return
        applied = controller.edits.apply_stroke_job(job_result, on_stale=_on_stale)
        if not applied:
            log_fn(
                "stroke finalize dropped: mask=%s gen=%s expected=%s pending=%s",
                job_result.mask_id,
                job_result.generation,
                controller.edits.async_epoch(job_result.mask_id),
                bool(self._pending_jobs.get(job_result.mask_id)),
            )
            if commit:
                controller.edits.commit_stroke(job_result.mask_id)
            _clear_pending_token(job_result.mask_id, job_token)
            _record_drop("controller_rejected")
            _notify_idle()
            return
        preview_image = job_result.preview_image
        if preview_image is not None:
            stride_value = job_result.metadata.get("stride")
            if stride_value is not None:
                try:
                    stride_text = str(int(stride_value))
                except (TypeError, ValueError):
                    stride_text = None
                if stride_text is not None:
                    preview_image.setText("qpane_preview_stride", stride_text)
            preview_image.setText(
                "qpane_preview_provisional",
                "0" if commit else "1",
            )
            self._update_region(
                job_result.dirty_rect,
                mask_layer,
                sub_mask_image=preview_image,
            )
        else:
            self._update_region(job_result.dirty_rect, mask_layer)
        if commit:
            controller.edits.commit_stroke(job_result.mask_id)
            _record_completion("committed")
        else:
            _record_completion("applied", detail="preview")
        self._refresh_active_preview(job_result.mask_id, mask_layer)
        _clear_pending_token(job_result.mask_id, job_token)
        _notify_idle()

    def apply_stroke_segment(
        self,
        segment: MaskStrokeSegmentPayload,
    ) -> None:
        """Render a preview segment and enqueue work for the active mask."""
        if not self._mask_feature_available():
            return
        current_image_id = self._current_image_id()
        if not self._ensure_active(current_image_id):
            logger.info(
                "Brush stroke skipped: no mask is ready for image %s.",
                current_image_id,
            )
            return
        active_mask_id = self._controller.get_active_mask_id()
        if active_mask_id is None:
            logger.warning("Brush stroke skipped: no active mask selected.")
            return
        mask_manager = self._assets
        if current_image_id is not None:
            mask_ids = self._mask_ids_for_image(current_image_id)
            if active_mask_id not in mask_ids:
                logger.warning(
                    "Brush stroke skipped: active mask %s is not linked to image %s.",
                    active_mask_id,
                    current_image_id,
                )
                return
        mask_layer = mask_manager.get_layer(active_mask_id)
        if mask_layer is None:
            logger.warning(
                "Brush stroke skipped: mask %s has no backing layer.",
                active_mask_id,
            )
            return
        if mask_layer.surface.is_null():
            logger.warning(
                "Brush stroke skipped: mask %s image is null.",
                active_mask_id,
            )
            return
        controller = self._controller
        existing_state = self._preview_states.get(active_mask_id)
        constraint = (
            existing_state.constraint
            if existing_state is not None
            else self._selection_constraint(active_mask_id)
        )
        prepared = self._region_planner.prepare(
            active_mask_id,
            mask_layer,
            segment,
            constraint,
        )
        if prepared is None:
            return
        if existing_state is not None:
            existing_state.translate_storage(
                prepared.rebase_x,
                prepared.rebase_y,
            )
        dirty_rect = prepared.dirty_rect
        segment = prepared.segment
        try:
            view = self._view()
        except AttributeError:
            logger.debug("Mask preview requested before view initialization")
            return
        viewport = view.viewport
        zoom = getattr(viewport, "zoom", 1.0) or 1.0
        stride = controller.renders.preview_stride(active_mask_id, zoom)
        state = self._preview_states.get(active_mask_id)
        if state is not None and state.stride != stride:
            logger.debug(
                "flushing preview state due to stride change (mask=%s old_stride=%s new_stride=%s segments=%s)",
                active_mask_id,
                state.stride,
                stride,
                len(state._segments),
            )
            state.flush_to_mask(
                controller=controller,
                submit_job=self._submit_stroke_job,
                source="stroke-final",
                commit=False,
                allocate_job_token=self._allocate_job_token,
                register_job_token=self._register_job_token,
                restore_job_token=self._restore_job_token,
            )
            self._preview_states.pop(active_mask_id, None)
            state = None
        if dirty_rect.isNull() or dirty_rect.isEmpty():
            self._update_region(dirty_rect, mask_layer)
            return
        if state is None:
            state = DecimatedStrokePreview(
                mask_id=active_mask_id,
                stride=stride,
                constraint=constraint,
                constraint_region=(
                    None
                    if constraint is None
                    else lambda rect, sample_stride: self._constraint_storage_region(
                        mask_layer,
                        constraint,
                        rect,
                        sample_stride,
                    )
                ),
            )
            self._preview_states[active_mask_id] = state
        preview = state.preview_segment(
            dirty_rect=dirty_rect,
            segment=segment,
            snapshot_region=lambda rect, preview_stride: (
                mask_layer.surface.snapshot_storage_region(
                    RasterBounds.from_qrect(rect),
                    stride=preview_stride,
                )
            ),
        )
        self._update_region(
            preview.rect,
            mask_layer,
            sub_mask_image=preview.image,
        )

    @staticmethod
    def _constraint_storage_region(
        mask_layer: object,
        constraint: CoverageSnapshot,
        storage_rect: QRect,
        stride: int,
    ) -> np.ndarray:
        """Return selection coverage aligned to current mask storage coordinates."""
        surface = getattr(mask_layer, "surface", None)
        surface_bounds = None if surface is None else surface.bounds
        constraint_bounds = constraint.bounds
        full = np.zeros(
            (storage_rect.height(), storage_rect.width()),
            dtype=np.uint8,
        )
        if surface_bounds is None or constraint_bounds is None:
            return full[:: max(1, stride), :: max(1, stride)]
        local = RasterBounds(
            surface_bounds.x + storage_rect.x(),
            surface_bounds.y + storage_rect.y(),
            storage_rect.width(),
            storage_rect.height(),
        )
        overlap = local.intersection(constraint_bounds)
        if overlap is not None:
            source_x = overlap.x - constraint_bounds.x
            source_y = overlap.y - constraint_bounds.y
            target_x = overlap.x - local.x
            target_y = overlap.y - local.y
            full[
                target_y : target_y + overlap.height,
                target_x : target_x + overlap.width,
            ] = constraint.pixels[
                source_y : source_y + overlap.height,
                source_x : source_x + overlap.width,
            ]
        sample_stride = max(1, stride)
        return full[::sample_stride, ::sample_stride]

    def commit_active_stroke(self) -> None:
        """Flush any recorded stroke segments for the active mask."""
        if not self._mask_feature_available():
            return
        mask_id = self._controller.get_active_mask_id()
        if mask_id is None:
            logger.warning("commit_active_stroke skipped: no active mask selected.")
            return
        controller = self._controller
        state = self._preview_states.pop(mask_id, None)
        if state is None:
            logger.debug(
                "commit_active_stroke skipped: no preview state for mask %s.",
                mask_id,
            )
            return
        queued = state.flush_to_mask(
            controller=controller,
            submit_job=self._submit_stroke_job,
            source="stroke-final",
            commit=True,
            allocate_job_token=self._allocate_job_token,
            register_job_token=self._register_job_token,
            restore_job_token=self._restore_job_token,
        )
        if not queued:
            controller.edits.commit_stroke(mask_id)
        self._notify_idle_if_clear(mask_id)

    def cancel_active_stroke(self) -> None:
        """Discard active preview and pending work without committing undo content."""
        mask_id = self._controller.get_active_mask_id()
        if mask_id is None:
            return
        self.reset_state(mask_id, request_redraw=True)
        self._controller.edits.begin_stroke()

    def _refresh_active_preview(self, mask_id: UUID, mask_layer: object) -> None:
        """Reapply a newer live stroke after an older worker updates its cache."""
        state = self._preview_states.get(mask_id)
        if state is None:
            return
        surface = getattr(mask_layer, "surface", None)
        if surface is None or surface.is_null():
            return
        preview = state.current_preview(
            lambda rect, preview_stride: surface.snapshot_storage_region(
                RasterBounds.from_qrect(rect),
                stride=preview_stride,
            )
        )
        if preview is None:
            return
        self._update_region(
            preview.rect,
            mask_layer,
            sub_mask_image=preview.image,
        )

    def _notify_idle_if_clear(self, mask_id: UUID | None) -> None:
        """Invoke the idle callback when ``mask_id`` has no pending stroke state."""
        if mask_id is None:
            return
        if self.is_mask_busy(mask_id):
            return
        callback = self._idle_callback
        if callback is None:
            return
        try:
            callback(mask_id)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Idle callback for mask %s failed", mask_id)
