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

"""Coordinate debounced, stale-safe mask autosaves."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from qpane.sdk.execution import (
    ExecutionHandle,
    ExecutionOutcome,
    ExecutionRejected,
    ExecutionRequest,
    ExecutionRequirements,
    ExecutionResource,
    ExecutionScope,
    ExecutionState,
    ExecutionUrgency,
    QtDelayScheduler,
    RetryController,
    RetryPolicy,
)

from ..core.config_features import MaskConfigSlice
from ..runtime.latest_requests import DocumentLatestRequestRegistry
from .autosave_products import (
    MaskImagePayload,
    encode_blank_mask,
    save_mask_payload,
)

logger = logging.getLogger(__name__)

_AUTOSAVE_RETRY_BASE_DELAY_MS = 100
_AUTOSAVE_RETRY_MAX_DELAY_MS = 2000


class AutosaveManager(QObject):
    """Own mask autosave debounce, retry, cancellation, and publication."""

    saveCompleted = Signal(str, str)
    saveFailed = Signal(str, str, Exception)
    saveThrottled = Signal(str, str, int)

    def __init__(
        self,
        snapshot_provider: Callable[[object], MaskImagePayload | None],
        settings: MaskConfigSlice,
        get_current_image_path: Callable[[], object],
        *,
        execution_scope: ExecutionScope,
        latest_requests: DocumentLatestRequestRegistry,
        diagnostics_dirty: Callable[[str], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        """Bind autosave policy to document execution and freshness ownership."""
        super().__init__(parent)
        self._snapshot_provider = snapshot_provider
        self._settings = settings
        self._get_current_image_path = get_current_image_path
        self._diagnostics_dirty = diagnostics_dirty
        self._execution_scope = execution_scope.open_child(
            f"{execution_scope.owner_id}:mask-autosave"
        )
        self._latest_requests = latest_requests
        self._dirty_masks_for_autosave: dict[str, object] = {}
        self._active_entries: dict[
            str,
            dict[uuid.UUID, ExecutionHandle[Path, object]],
        ] = {}
        self._blank_encode_entries: dict[
            str,
            dict[uuid.UUID, ExecutionHandle[bytes, object]],
        ] = {}
        self._request_ids: dict[str, uuid.UUID] = {}
        self._retry: RetryController[str, object, object, object] = RetryController(
            "editor.mask.autosave",
            RetryPolicy(
                base_ms=_AUTOSAVE_RETRY_BASE_DELAY_MS,
                max_ms=_AUTOSAVE_RETRY_MAX_DELAY_MS,
            ),
            QtDelayScheduler(self),
        )
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self.performSave)
        self._diagnostics_tick_timer = QTimer(self)
        self._diagnostics_tick_timer.setInterval(250)
        self._diagnostics_tick_timer.timeout.connect(self._maybe_mark_diagnostics_dirty)

    def applyConfig(self, settings: MaskConfigSlice) -> None:
        """Use a new mask configuration snapshot for subsequent saves."""
        self._settings = settings

    def retry_snapshot(self):
        """Return bounded retry telemetry for diagnostics."""
        return self._retry.snapshot()

    def saveBlankMask(self, mask_id: str, image_size: object) -> None:
        """Persist a new transparent mask when creation autosave is enabled."""
        if not (
            self._settings.mask_autosave_enabled
            and self._settings.mask_autosave_on_creation
        ):
            return
        image_path = self._get_current_image_path()
        if not image_path or not mask_id:
            return
        save_path = Path(
            self._settings.mask_autosave_path_template.format(
                image_name=Path(image_path).stem,
                mask_id=mask_id,
            )
        )
        if save_path.exists():
            logger.debug("Blank mask autosave already exists at %s", save_path)
            return
        size = self._coerce_image_dimensions(image_size)
        if size[0] <= 0 or size[1] <= 0:
            logger.warning(
                "Skipping blank mask autosave for %s: invalid size %sx%s",
                mask_id,
                size[0],
                size[1],
            )
            return
        key = str(mask_id)
        request_id = self._begin_request(key)
        if request_id is not None:
            self._queue_blank_encode(key, request_id, size, save_path)

    def scheduleSave(self, mask_id: str, dirty_rect: object = None) -> None:
        """Debounce persistence for one modified mask."""
        del dirty_rect
        if not self._settings.mask_autosave_enabled or not mask_id:
            return
        self._dirty_masks_for_autosave[str(mask_id)] = mask_id
        self._autosave_timer.start(self._settings.mask_autosave_debounce_ms)
        self._ensure_diagnostics_ticks()
        self._mark_diagnostics_dirty()

    def performSave(self) -> None:
        """Submit every dirty mask using the configured path template."""
        if not self._settings.mask_autosave_enabled:
            return
        for key, mask_id in tuple(self._dirty_masks_for_autosave.items()):
            default_path = self._resolveDefaultSavePath(key)
            if default_path is None:
                logger.warning("No autosave path resolved for mask %s", key)
                continue
            self.saveMaskToPath(mask_id, default_path)
        self._mark_diagnostics_dirty()

    def saveMaskToPath(self, mask_id: object, path: str | Path) -> None:
        """Snapshot and asynchronously persist one mask."""
        if mask_id is None or not path:
            return
        key = str(mask_id)
        payload = self._snapshot_provider(mask_id)
        if payload is None:
            return
        if isinstance(payload, QImage):
            if payload.isNull():
                return
            payload = payload.copy()
        self._dirty_masks_for_autosave.pop(key, None)
        request_id = self._begin_request(key)
        if request_id is not None:
            self._queue_save(key, request_id, payload, Path(path))

    def pending_mask_count(self) -> int:
        """Return the number of dirty masks waiting for debounce."""
        return len(self._dirty_masks_for_autosave)

    def seconds_until_next_save(self) -> float | None:
        """Return the remaining debounce duration in seconds."""
        if not self._autosave_timer.isActive():
            return None
        remaining_ms = self._autosave_timer.remainingTime()
        return None if remaining_ms < 0 else remaining_ms / 1000.0

    def cancelPendingMask(self, mask_id: str) -> None:
        """Cancel delayed and accepted work for one mask."""
        key = str(mask_id)
        request_id = self._request_ids.get(key)
        if request_id is not None:
            self._latest_requests.cancel_request(
                self._request_key(key),
                request_id,
                reason="mask autosave cancelled",
            )
        else:
            self._cancel_local_request(key, reason="mask autosave cancelled")
        self._dirty_masks_for_autosave.pop(key, None)
        self._mark_diagnostics_dirty()

    def activeSaveCount(self) -> int:
        """Return accepted autosave operations that have not settled."""
        return sum(len(entries) for entries in self._active_entries.values()) + sum(
            len(entries) for entries in self._blank_encode_entries.values()
        )

    def shutdown(self, *, wait: bool = True) -> None:
        """Close autosave ownership and cancel delayed or accepted work."""
        del wait
        self._autosave_timer.stop()
        self._diagnostics_tick_timer.stop()
        for mask_id, request_id in tuple(self._request_ids.items()):
            if not self._latest_requests.cancel_request(
                self._request_key(mask_id),
                request_id,
                reason="mask autosave manager shut down",
            ):
                self._cancel_local_request(
                    mask_id,
                    reason="mask autosave manager shut down",
                )
        self._retry.cancel_all()
        self._execution_scope.close(reason="mask_autosave_shutdown")
        self._active_entries.clear()
        self._blank_encode_entries.clear()
        self._request_ids.clear()

    def _queue_blank_encode(
        self,
        mask_id: str,
        request_id: uuid.UUID,
        size: tuple[int, int],
        path: Path,
    ) -> None:
        """Submit or coalesce transparent-image encoding for one mask."""
        retry_key = self._blank_retry_key(mask_id)

        def _submit(
            payload: object,
            attempt: int,
        ) -> ExecutionHandle[bytes, object]:
            """Submit the retained blank encode payload."""
            retained_mask_id, retained_size, retained_path = payload
            request = ExecutionRequest(
                operation="editor.mask.autosave.encode_blank",
                requirements=ExecutionRequirements(
                    resource=ExecutionResource.NATIVE_CPU,
                    urgency=ExecutionUrgency.BACKGROUND,
                    estimated_retained_bytes=retained_size[0] * retained_size[1] * 4,
                ),
                tags=(("mask_id", retained_mask_id), ("attempt", attempt)),
                work=lambda context: encode_blank_mask(
                    retained_size,
                    context.cancellation,
                ),
            )
            handle = self._execution_scope.submit(request)
            self._blank_encode_entries.setdefault(retained_mask_id, {})[
                request_id
            ] = handle
            handle.add_done_callback(
                lambda outcome: self._finish_blank_encode(
                    retained_mask_id,
                    request_id,
                    retained_path,
                    handle,
                    outcome,
                )
            )
            return handle

        self._retry.submit_or_coalesce(
            retry_key,
            (mask_id, size, path),
            submit=_submit,
            rejected=lambda _key, attempt, rejection: self._report_rejection(
                mask_id,
                path,
                attempt,
                rejection,
            ),
        )

    def _finish_blank_encode(
        self,
        mask_id: str,
        request_id: uuid.UUID,
        path: Path,
        handle: ExecutionHandle[bytes, object],
        outcome: ExecutionOutcome[bytes],
    ) -> None:
        """Settle one blank encode and schedule its atomic file save."""
        self._remove_handle(self._blank_encode_entries, mask_id, request_id)
        if not self._is_current(mask_id, request_id):
            return
        if outcome.state == ExecutionState.CANCELLED:
            self._release_request(mask_id, request_id)
            return
        if outcome.state == ExecutionState.FAILED or outcome.result is None:
            self._release_request(mask_id, request_id)
            self._emit_failure(
                mask_id,
                path,
                outcome.error or RuntimeError("Blank mask encode produced no data"),
            )
            return
        self._queue_save(mask_id, request_id, outcome.result, path)

    def _queue_save(
        self,
        mask_id: str,
        request_id: uuid.UUID,
        payload: MaskImagePayload,
        path: Path,
    ) -> None:
        """Submit or coalesce one atomic mask save."""

        def _submit(
            retained: object,
            attempt: int,
        ) -> ExecutionHandle[Path, object]:
            """Submit the retained image and target path."""
            retained_payload, retained_path = retained
            request = ExecutionRequest(
                operation="editor.mask.autosave.save",
                requirements=ExecutionRequirements(
                    resource=ExecutionResource.BLOCKING_IO,
                    urgency=ExecutionUrgency.BACKGROUND,
                    exclusive_key=f"mask-autosave:{mask_id}",
                    estimated_retained_bytes=self._payload_size(retained_payload),
                ),
                tags=(("mask_id", mask_id), ("attempt", attempt)),
                work=lambda context: save_mask_payload(
                    retained_payload,
                    retained_path,
                    context.cancellation,
                ),
            )
            handle = self._execution_scope.submit(request)
            self._active_entries.setdefault(mask_id, {})[request_id] = handle
            handle.add_done_callback(
                lambda outcome: self._finish_save(
                    mask_id,
                    request_id,
                    retained_path,
                    handle,
                    outcome,
                )
            )
            return handle

        self._retry.submit_or_coalesce(
            mask_id,
            (payload, path),
            submit=_submit,
            merge=lambda _old, new: self._mark_coalesced(mask_id, new),
            rejected=lambda _key, attempt, rejection: self._report_rejection(
                mask_id,
                path,
                attempt,
                rejection,
            ),
        )

    def _finish_save(
        self,
        mask_id: str,
        request_id: uuid.UUID,
        path: Path,
        handle: ExecutionHandle[Path, object],
        outcome: ExecutionOutcome[Path],
    ) -> None:
        """Publish one terminal save and release its bookkeeping."""
        self._remove_handle(self._active_entries, mask_id, request_id)
        if not self._is_current(mask_id, request_id):
            return
        self._release_request(mask_id, request_id)
        if outcome.state == ExecutionState.CANCELLED:
            return
        if outcome.state == ExecutionState.FAILED:
            self._dirty_masks_for_autosave[mask_id] = mask_id
            self._emit_failure(
                mask_id,
                path,
                outcome.error or RuntimeError("Mask autosave failed"),
            )
            return
        self._dirty_masks_for_autosave.pop(mask_id, None)
        self.saveCompleted.emit(mask_id, str(path))
        self._mark_diagnostics_dirty()

    def _begin_request(self, mask_id: str) -> uuid.UUID | None:
        """Claim document-wide autosave freshness for one mask."""
        request_id = uuid.uuid4()
        claimed = self._latest_requests.claim(
            self._request_key(mask_id),
            request_id,
            lambda reason: self._cancel_request(mask_id, request_id, reason),
        )
        if not claimed:
            return None
        self._request_ids[mask_id] = request_id
        return request_id

    def _cancel_request(
        self,
        mask_id: str,
        request_id: uuid.UUID,
        reason: str,
    ) -> None:
        """Cancel one superseded document autosave without touching a sibling."""
        if self._request_ids.get(mask_id) != request_id:
            return
        self._request_ids.pop(mask_id, None)
        self._cancel_local_request(mask_id, reason=reason)

    def _cancel_local_request(self, mask_id: str, *, reason: str) -> None:
        """Cancel only work and retry state owned by this manager."""
        for handle in tuple(self._active_entries.pop(mask_id, {}).values()):
            handle.cancel(reason=reason)
        for handle in tuple(self._blank_encode_entries.pop(mask_id, {}).values()):
            handle.cancel(reason=reason)
        self._retry.cancel(mask_id)
        self._retry.cancel(self._blank_retry_key(mask_id))

    def _is_current(self, mask_id: str, request_id: uuid.UUID) -> bool:
        """Return whether this manager still owns the document autosave."""
        return self._request_ids.get(
            mask_id
        ) == request_id and self._latest_requests.is_current(
            self._request_key(mask_id),
            request_id,
        )

    def _release_request(self, mask_id: str, request_id: uuid.UUID) -> None:
        """Release terminal autosave freshness from both owners."""
        if self._request_ids.get(mask_id) == request_id:
            self._request_ids.pop(mask_id, None)
        self._latest_requests.release(self._request_key(mask_id), request_id)

    def _report_rejection(
        self,
        mask_id: str,
        path: Path,
        attempt: int,
        rejection: ExecutionRejected,
    ) -> None:
        """Retain dirty state and report structured execution saturation."""
        self._dirty_masks_for_autosave[mask_id] = mask_id
        self.saveThrottled.emit(mask_id, str(path), attempt)
        logger.warning(
            "Mask autosave submission rejected for %s (%s): %s",
            mask_id,
            rejection.reason.value,
            rejection,
        )
        self._mark_diagnostics_dirty()

    def _mark_coalesced(
        self,
        mask_id: str,
        payload: object,
    ) -> object:
        """Retain dirty state while replacing a rejected save payload."""
        self._dirty_masks_for_autosave[mask_id] = mask_id
        return payload

    def _emit_failure(
        self,
        mask_id: str,
        path: Path,
        error: BaseException,
    ) -> None:
        """Publish one save failure using the Qt signal's exception contract."""
        exception = error if isinstance(error, Exception) else RuntimeError(str(error))
        logger.error("Mask autosave failed for %s to %s: %s", mask_id, path, error)
        self.saveFailed.emit(mask_id, str(path), exception)
        self._mark_diagnostics_dirty()

    def _ensure_diagnostics_ticks(self) -> None:
        """Refresh diagnostics while a debounce countdown remains active."""
        if not self._diagnostics_tick_timer.isActive():
            self._diagnostics_tick_timer.start()

    def _maybe_mark_diagnostics_dirty(self) -> None:
        """Stop countdown telemetry after all pending debounce state settles."""
        if not self._autosave_timer.isActive() and not self._dirty_masks_for_autosave:
            self._diagnostics_tick_timer.stop()
            return
        self._mark_diagnostics_dirty()

    def _mark_diagnostics_dirty(self) -> None:
        """Notify the diagnostics broker when autosave state changes."""
        if self._diagnostics_dirty is not None:
            self._diagnostics_dirty("mask")

    def _resolveDefaultSavePath(self, mask_id: str) -> Path | None:
        """Resolve the configured path template for one mask."""
        template = self._settings.mask_autosave_path_template
        if not template:
            return None
        image_path = self._get_current_image_path()
        image_name = Path(image_path).stem if image_path else "mask"
        try:
            return Path(template.format(image_name=image_name, mask_id=mask_id))
        except Exception:
            logger.exception(
                "Could not format mask autosave path for mask %s using %r",
                mask_id,
                template,
            )
            return None

    @staticmethod
    def _remove_handle(
        entries: dict[str, dict[uuid.UUID, ExecutionHandle]],
        mask_id: str,
        task_id: uuid.UUID,
    ) -> None:
        """Release one terminal handle from a per-mask task map."""
        mask_entries = entries.get(mask_id)
        if mask_entries is None:
            return
        mask_entries.pop(task_id, None)
        if not mask_entries:
            entries.pop(mask_id, None)

    @staticmethod
    def _coerce_image_dimensions(image_size: object) -> tuple[int, int]:
        """Return integer dimensions for QSize-like or pair-like values."""
        if hasattr(image_size, "width") and hasattr(image_size, "height"):
            try:
                return int(image_size.width()), int(image_size.height())
            except (RuntimeError, TypeError, ValueError, OverflowError):
                return 0, 0
        if isinstance(image_size, (tuple, list)) and len(image_size) >= 2:
            try:
                return int(image_size[0]), int(image_size[1])
            except (TypeError, ValueError, OverflowError):
                return 0, 0
        return 0, 0

    @staticmethod
    def _payload_size(payload: MaskImagePayload) -> int | None:
        """Estimate retained payload bytes for admission diagnostics."""
        if isinstance(payload, bytes):
            return len(payload)
        if isinstance(payload, QImage):
            return max(0, int(payload.sizeInBytes()))
        return None

    @staticmethod
    def _blank_retry_key(mask_id: str) -> str:
        """Return the independent retry key for blank image encoding."""
        return f"blank::{mask_id}"

    @staticmethod
    def _request_key(mask_id: str) -> tuple[str, str]:
        """Return the document-global autosave replacement key."""
        return ("mask-autosave", mask_id)


__all__ = [
    "AutosaveManager",
    "MaskImagePayload",
]
