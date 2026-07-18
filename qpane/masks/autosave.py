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

"""Mask autosave workflows that queue disk writes through the shared task executor."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import (
    QBuffer,
    QIODevice,
    QObject,
    QRunnable,
    QTimer,
    Signal,
)
from PySide6.QtGui import QImage, Qt

from ..concurrency import (
    BaseWorker,
    TaskExecutorProtocol,
    TaskHandle,
    TaskRejected,
    makeQtRetryController,
    qt_retry_dispatcher,
)
from ..core.config_features import MaskConfigSlice

logger = logging.getLogger(__name__)

_AUTOSAVE_RETRY_BASE_DELAY_MS = 100
_AUTOSAVE_RETRY_MAX_DELAY_MS = 2000


class AutosaveManager(QObject):
    """Manage debounced autosaves of mask layers using background workers."""

    saveCompleted = Signal(str, str)  # mask_id, path
    saveFailed = Signal(str, str, Exception)  # mask_id, path, exception
    saveThrottled = Signal(str, str, int)  # mask_id, path, attempt

    def __init__(
        self,
        mask_manager,
        settings: MaskConfigSlice,
        get_current_image_path: Callable,
        *,
        executor: TaskExecutorProtocol,
        diagnostics_dirty: Callable[[str], None] | None = None,
        parent=None,
    ):
        """Initialize the autosave manager and optional worker executor.

        Args:
            mask_manager: Mask manager used to query/serialize layers.
            settings: Mask configuration slice containing autosave preferences.
            get_current_image_path: Callable returning the active image path.
            executor: Shared executor instance used for autosave workers.
            diagnostics_dirty: Optional callback to mark diagnostics dirty for the
                mask domain when autosave state changes.
            parent: Optional QObject parent for Qt ownership.
        """
        super().__init__(parent)
        self._mask_manager = mask_manager
        self._settings = settings
        self._executor: TaskExecutorProtocol | None = executor
        self._get_current_image_path = get_current_image_path
        self._diagnostics_dirty = diagnostics_dirty
        self._dirty_masks_for_autosave = set()
        self._active_workers: list[_MaskSaveWorker] = []
        self._active_entries: dict[str, list[tuple[_MaskSaveWorker, TaskHandle]]] = {}
        self._blank_encode_entries: dict[
            str, list[tuple[_BlankMaskEncodeWorker, TaskHandle]]
        ] = {}
        self._retry = makeQtRetryController(
            "autosave",
            _AUTOSAVE_RETRY_BASE_DELAY_MS,
            _AUTOSAVE_RETRY_MAX_DELAY_MS,
            parent=self,
            dispatcher=qt_retry_dispatcher(self._executor, category="autosave_main"),
        )
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self.performSave)
        self._diagnostics_tick_timer = QTimer(self)
        self._diagnostics_tick_timer.setInterval(250)
        self._diagnostics_tick_timer.timeout.connect(self._maybe_mark_diagnostics_dirty)

    def applyConfig(self, settings: MaskConfigSlice) -> None:
        """Swap in a new configuration snapshot for subsequent saves."""
        self._settings = settings

    def retry_snapshot(self):
        """Expose the autosave retry controller snapshot for diagnostics."""
        return self._retry.snapshot()

    def saveBlankMask(self, mask_id: str, image_size) -> None:
        """Immediately saves a blank, transparent version of a new mask."""
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
                image_name=image_path.stem, mask_id=mask_id
            )
        )
        if save_path.exists():
            logger.debug(
                "Skipping blank mask autosave for %s: %s already exists",
                mask_id,
                save_path,
            )
            return
        width, height = self._coerce_image_dimensions(image_size)
        if width <= 0 or height <= 0:
            logger.warning(
                "Skipping blank mask autosave for %s: invalid size %sx%s",
                mask_id,
                width,
                height,
            )
            return
        self._schedule_blank_mask_encode(str(mask_id), (width, height), save_path)

    def _schedule_blank_mask_encode(
        self, mask_id: str, size: tuple[int, int], path: Path, *, attempt: int = 0
    ) -> None:
        """Submit a background encode for a blank mask, retrying when throttled."""
        try:
            self._submit_blank_mask_encode_worker(
                mask_id=mask_id, size=size, path=path, attempt=attempt
            )
        except TaskRejected as rejection:
            self._handle_blank_encode_rejection(
                mask_id=mask_id,
                size=size,
                path=path,
                attempt=attempt,
                rejection=rejection,
            )

    def _submit_blank_mask_encode_worker(
        self, *, mask_id: str, size: tuple[int, int], path: Path, attempt: int
    ) -> TaskHandle:
        """Dispatch a blank-mask encode worker to the executor."""
        worker = _BlankMaskEncodeWorker(mask_id, size, path)
        worker.setAutoDelete(False)
        try:
            BaseWorker.connect_queued(worker.finished, self._on_blank_mask_encoded)
        except TypeError:  # pragma: no cover - PySide signal edge case
            worker.finished.connect(self._on_blank_mask_encoded)
        executor = self._executor
        if executor is None:
            raise RuntimeError("AutosaveManager executor is missing")
        try:
            handle = executor.submit(worker, category="io")
        except TaskRejected:
            try:
                worker.deleteLater()
            except RuntimeError:
                logger.debug("Blank-mask worker was already deleted", exc_info=True)
            raise
        self._blank_encode_entries.setdefault(mask_id, []).append((worker, handle))
        logger.info(
            "Queued blank mask encode for mask %s to %s (task=%s, attempt=%s)",
            mask_id,
            path,
            handle.task_id,
            attempt,
        )
        return handle

    def _handle_blank_encode_rejection(
        self,
        *,
        mask_id: str,
        size: tuple[int, int],
        path: Path,
        attempt: int,
        rejection: TaskRejected,
    ) -> None:
        """Schedule a retry when the blank encode submission is throttled."""
        next_attempt = max(1, attempt + 1)
        logger.warning(
            "Blank mask encode for %s throttled: pending %s limit=%s (total=%s, category=%s)",
            mask_id,
            rejection.limit_type,
            rejection.limit_value,
            rejection.pending_total,
            rejection.pending_category,
        )
        self.saveThrottled.emit(mask_id, str(path), next_attempt)
        key = self._blank_encode_retry_key(mask_id)

        def _submit(
            payload: tuple[str, tuple[int, int], Path], tries: int
        ) -> TaskHandle:
            """Forward encoded-blank submission to the executor via retry controller."""
            mid, dims, target_path = payload
            return self._submit_blank_mask_encode_worker(
                mask_id=mid,
                size=dims,
                path=target_path,
                attempt=tries,
            )

        def _coalesce(_old, new):
            """Replace queued blank encode payloads with the most recent request."""
            return new

        def _throttle(_key: str, nxt_attempt: int, rej: TaskRejected) -> None:
            """Log and surface throttling while preserving retry attempts."""
            self.saveThrottled.emit(mask_id, str(path), nxt_attempt)
            logger.warning(
                "Blank mask encode for %s throttled again: pending %s limit=%s (total=%s, category=%s)",
                mask_id,
                rej.limit_type,
                rej.limit_value,
                rej.pending_total,
                rej.pending_category,
            )

        self._retry.queueOrCoalesce(
            key,
            (mask_id, size, path),
            submit=_submit,
            coalesce=_coalesce,
            throttle=_throttle,
        )

    @staticmethod
    def _blank_encode_retry_key(mask_id: str) -> str:
        """Return the retry-controller key for blank mask encode operations."""
        return f"blank::{mask_id}"

    def _remove_blank_encode_worker(
        self, mask_id: str, worker: _BlankMaskEncodeWorker
    ) -> None:
        """Drop bookkeeping for a completed blank encode worker."""
        entries = self._blank_encode_entries.get(mask_id)
        if not entries:
            return
        for index, (candidate, handle) in enumerate(entries):
            if candidate is worker:
                entries.pop(index)
                break
        if not entries:
            self._blank_encode_entries.pop(mask_id, None)
        try:
            worker.deleteLater()
        except RuntimeError:
            logger.debug("Blank-mask worker was already deleted", exc_info=True)

    @staticmethod
    def _coerce_image_dimensions(image_size) -> tuple[int, int]:
        """Return integer width/height for image_size, defaulting to zeros."""
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

    def _on_blank_mask_encoded(self, worker: _BlankMaskEncodeWorker) -> None:
        """Handle completion of the blank-mask encode worker."""
        mask_id = str(worker.mask_id)
        path = Path(worker.path)
        key = self._blank_encode_retry_key(mask_id)
        self._retry.onFailure(key)
        self._remove_blank_encode_worker(mask_id, worker)
        if getattr(worker, "is_cancelled", False):
            logger.info("Blank mask encode cancelled for %s to %s", mask_id, path)
            return
        error = getattr(worker, "error", None)
        if error is not None:
            logger.error(
                "Blank mask encode failed for %s to %s: %s", mask_id, path, error
            )
            self.saveFailed.emit(mask_id, str(path), error)
            return
        image_bytes = getattr(worker, "image_bytes", None)
        if not image_bytes:
            err = RuntimeError("Blank mask encode produced no data")
            logger.error(
                "Blank mask encode failed for %s to %s: %s", mask_id, path, err
            )
            self.saveFailed.emit(mask_id, str(path), err)
            return
        self._retry.onSuccess(key)
        self._queue_save_worker(mask_id, image_bytes, path)

    def scheduleSave(self, mask_id: str, dirty_rect=None):
        """Schedules a debounced save for a modified mask."""
        if not self._settings.mask_autosave_enabled or not mask_id:
            return
        self._dirty_masks_for_autosave.add(mask_id)
        self._autosave_timer.start(self._settings.mask_autosave_debounce_ms)
        self._ensure_diagnostics_ticks()
        self._mark_diagnostics_dirty()

    def performSave(self):
        """Persist dirty masks using the configured autosave path template."""
        logger.debug("Autosave timer fired.")
        if not self._settings.mask_autosave_enabled:
            return
        dirty_set_copy = self._dirty_masks_for_autosave.copy()
        for mask_id in dirty_set_copy:
            default_path = self._resolveDefaultSavePath(mask_id)
            if not default_path:
                logger.warning("No autosave path resolved for mask %s", mask_id)
                continue
            logger.info("Autosaving mask %s to %s", mask_id, default_path)
            self.saveMaskToPath(mask_id, default_path)
        self._mark_diagnostics_dirty()

    def saveMaskToPath(self, mask_id: str, path: str):
        """Persist ``mask_id`` to ``path`` using a background worker."""
        if not mask_id or not path:
            return
        self._dirty_masks_for_autosave.discard(mask_id)
        mask_layer = self._mask_manager.get_layer(mask_id)
        if not mask_layer or mask_layer.mask_image.isNull():
            return
        image_to_save = mask_layer.mask_image.copy()
        self._queue_save_worker(mask_id, image_to_save, path)

    def pending_mask_count(self) -> int:
        """Return the number of masks waiting to be autosaved."""
        return len(self._dirty_masks_for_autosave)

    def seconds_until_next_save(self) -> float | None:
        """Return seconds remaining until the next autosave fires when scheduled."""
        if not self._autosave_timer.isActive():
            return None
        remaining_ms = self._autosave_timer.remainingTime()
        if remaining_ms < 0:
            return None
        return remaining_ms / 1000.0

    def cancelPendingMask(self, mask_id: str) -> None:
        """Cancel any in-flight autosave tasks for ``mask_id``."""
        entries = self._active_entries.pop(str(mask_id), [])
        if not entries:
            self._retry.cancel(str(mask_id))
            self._dirty_masks_for_autosave.discard(str(mask_id))
            return
        for worker, handle in entries:
            executor = self._executor
            if executor is None:
                raise RuntimeError("AutosaveManager executor is missing")
            cancelled = executor.cancel(handle)
            if not cancelled:
                worker.cancel()
            logger.info(
                "Cancelled autosave worker for mask %s (task=%s, cancelled=%s)",
                mask_id,
                handle.task_id,
                cancelled,
            )
            if worker in self._active_workers:
                self._active_workers.remove(worker)
        self._dirty_masks_for_autosave.discard(str(mask_id))
        self._retry.cancel(str(mask_id))

    def activeSaveCount(self) -> int:
        """Return the number of autosave tasks currently active in the executor."""
        if self._executor is None:
            return sum(len(entries) for entries in self._active_entries.values())
        try:
            return self._executor.active_counts().get("io", 0)
        except Exception:  # noqa: BLE001 - injected executor metrics are optional
            return sum(len(entries) for entries in self._active_entries.values())

    def _ensure_diagnostics_ticks(self) -> None:
        """Start periodic diagnostics updates while autosave countdown is active."""
        if not self._diagnostics_tick_timer.isActive():
            self._diagnostics_tick_timer.start()

    def _maybe_mark_diagnostics_dirty(self) -> None:
        """Refresh diagnostics while the autosave timer counts down."""
        if not self._autosave_timer.isActive() and not self._dirty_masks_for_autosave:
            self._diagnostics_tick_timer.stop()
            return
        self._mark_diagnostics_dirty()

    def _mark_diagnostics_dirty(self) -> None:
        """Notify diagnostics about autosave state changes when callbacks are wired."""
        callback = self._diagnostics_dirty
        if callback is None:
            return
        try:
            callback("mask")
        except Exception:  # pragma: no cover - defensive guard
            logger.debug("Autosave diagnostics dirty callback failed", exc_info=True)

    def _queue_save_worker(
        self, mask_id: str, image_payload: QImage | bytes, path: str | Path
    ) -> None:
        """Queue a background worker to encode and write the mask to disk."""
        key = str(mask_id)
        normalized_path = Path(path)

        def _submit(payload: tuple[QImage | bytes, Path], attempt: int):
            """Submit a mask save worker to the executor."""
            payload_image, path2 = payload
            worker = _MaskSaveWorker(payload_image, path2, key)
            worker.setAutoDelete(False)
            try:
                BaseWorker.connect_queued(worker.finished, self._on_save_finished)
            except TypeError:
                worker.finished.connect(self._on_save_finished)
            executor = self._executor
            if executor is None:
                raise RuntimeError("AutosaveManager executor is missing")
            handle = executor.submit(worker, category="io")
            self._active_workers.append(worker)
            self._active_entries.setdefault(key, []).append((worker, handle))
            logger.info(
                "Queued autosave for mask %s to %s (task=%s)",
                key,
                path2,
                handle.task_id,
            )
            return handle

        def _coalesce(
            old: tuple[QImage | bytes, Path], new: tuple[QImage | bytes, Path]
        ) -> tuple[QImage | bytes, Path]:
            """Prefer the most recent payload while keeping the mask marked dirty."""
            self._dirty_masks_for_autosave.add(key)
            return new

        def _throttle(mid: str, next_attempt: int, rej: TaskRejected):
            """Record throttling and keep the mask scheduled for saving."""
            self._dirty_masks_for_autosave.add(mid)
            self.saveThrottled.emit(mid, str(normalized_path), next_attempt)
            logger.warning(
                "Autosave for mask %s throttled: pending %s limit=%s (total=%s, category=%s)",
                mid,
                rej.limit_type,
                rej.limit_value,
                rej.pending_total,
                rej.pending_category,
            )

        self._retry.queueOrCoalesce(
            key,
            (image_payload, normalized_path),
            submit=_submit,
            coalesce=_coalesce,
            throttle=_throttle,
        )

    def _on_save_finished(self, worker_instance):
        """Handle worker completion by emitting success or failure and cleaning up."""
        mask_id = str(worker_instance.mask_id)
        path = str(worker_instance.path)
        self._retry.onFailure(mask_id)
        if getattr(worker_instance, "is_cancelled", False):
            logger.info("Autosave cancelled for mask %s to %s", mask_id, path)
        elif getattr(worker_instance, "error", None) is not None:
            logger.error(
                "Autosave failed for mask %s to %s: %s",
                mask_id,
                path,
                worker_instance.error,
            )
            self.saveFailed.emit(mask_id, path, worker_instance.error)
        else:
            logger.info("Autosave completed for mask %s to %s", mask_id, path)
            self.saveCompleted.emit(mask_id, path)
            self._retry.onSuccess(mask_id)
        self._dirty_masks_for_autosave.discard(mask_id)
        self._remove_active_worker(mask_id, worker_instance)

    def _remove_active_worker(self, mask_id: str, worker: _MaskSaveWorker) -> None:
        """Prune bookkeeping for a completed or cancelled worker."""
        entries = self._active_entries.get(mask_id)
        if not entries:
            return
        remaining: list[tuple[_MaskSaveWorker, TaskHandle]] = []
        for existing_worker, handle in entries:
            if existing_worker is worker:
                continue
            remaining.append((existing_worker, handle))
        if remaining:
            self._active_entries[mask_id] = remaining
        else:
            self._active_entries.pop(mask_id, None)
        if worker in self._active_workers:
            self._active_workers.remove(worker)

    def shutdown(self, *, wait: bool = True) -> None:
        """Cancel all outstanding autosave tasks and optionally wait for completion."""
        for mask_id in list(self._active_entries.keys()):
            self.cancelPendingMask(mask_id)
        self._retry.cancelAll()
        self._active_workers.clear()

    def _resolveDefaultSavePath(self, mask_id) -> Path | None:
        """Derive a filesystem path for ``mask_id`` using the active template."""
        template = getattr(self._settings, "mask_autosave_path_template", None)
        if not template:
            return None
        image_path = self._get_current_image_path()
        if image_path:
            try:
                image_name = Path(image_path).stem
            except TypeError:
                image_name = Path(str(image_path)).stem
        else:
            image_name = None
        if not image_name:
            image_name = "mask"
        try:
            return Path(template.format(image_name=image_name, mask_id=mask_id))
        except Exception:
            logger.exception(
                "Could not format mask autosave path for mask %s using template %r",
                mask_id,
                template,
            )
            return None


class _MaskSaveWorker(QObject, QRunnable, BaseWorker):
    """Encode and write mask image data to disk on a background thread."""

    finished = Signal(object)  # Emits its own instance upon completion

    def __init__(self, image_payload: QImage | bytes, path: Path, mask_id: str):
        """Capture mask payload metadata for deferred disk writes."""
        QObject.__init__(self)
        QRunnable.__init__(self)
        BaseWorker.__init__(self)
        self.image_payload = image_payload
        self.path: Path = Path(path)
        self.mask_id = mask_id
        self.error: Exception | None = None

    def run(self):
        """Encode the mask to PNG and write it to disk."""
        cancelled = False
        buffer: QBuffer | None = None
        try:
            if self.is_cancelled:
                cancelled = True
                return
            image_bytes: bytes | None
            if isinstance(self.image_payload, bytes):
                image_bytes = self.image_payload
            else:
                buffer = QBuffer()
                if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
                    raise RuntimeError("QBuffer failed to open for writing")
                if not self.image_payload.save(buffer, "PNG"):
                    raise RuntimeError("QImage.save returned False while encoding mask")
                image_bytes = bytes(buffer.data())
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.is_cancelled:
                cancelled = True
                return
            with self.path.open("wb") as f:
                f.write(image_bytes)
            if self.is_cancelled:
                cancelled = True
                return
            self.logger.info(
                "Mask %s saved successfully to %s", self.mask_id, self.path
            )
        except Exception as exc:
            self.error = exc
            self.logger.exception(
                "Could not save mask %s to %s", self.mask_id, self.path
            )
        finally:
            if buffer is not None and buffer.isOpen():
                try:
                    buffer.close()
                except Exception:
                    self.logger.debug(
                        "Failed to close buffer after mask save", exc_info=True
                    )
        if cancelled or self.is_cancelled:
            self.logger.info("Mask %s save cancelled before completion", self.mask_id)
            self.emit_finished(False, payload=self)
            self.finished.emit(self)
            return
        succeeded = self.error is None
        self.emit_finished(succeeded, payload=self, error=self.error)
        if not succeeded:
            self.finished.emit(self)


class _BlankMaskEncodeWorker(QObject, QRunnable, BaseWorker):
    """Build blank mask image bytes off the UI thread so autosave stays responsive."""

    finished = Signal(object)

    def __init__(self, mask_id: str, size: tuple[int, int], path: Path) -> None:
        """Store mask metadata and target path for blank mask encoding."""
        QObject.__init__(self)
        QRunnable.__init__(self)
        BaseWorker.__init__(self)
        self.mask_id = str(mask_id)
        self._size = (max(0, int(size[0])), max(0, int(size[1])))
        self.path = Path(path)
        self.image_bytes: bytes | None = None
        self.error: Exception | None = None

    def run(self) -> None:
        """Encode a transparent PNG that represents a blank mask."""
        cancelled = False
        buffer = QBuffer()
        try:
            if self.is_cancelled:
                cancelled = True
                return
            width, height = self._size
            image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
                raise RuntimeError("QBuffer failed to open for writing")
            if not image.save(buffer, "PNG"):
                raise RuntimeError(
                    "QImage.save returned False while encoding blank mask"
                )
            self.image_bytes = bytes(buffer.data())
        except Exception as exc:
            self.error = exc
            self.logger.exception(
                "Could not encode blank mask %s to %s",
                self.mask_id,
                self.path,
            )
        finally:
            try:
                if buffer.isOpen():
                    buffer.close()
            except Exception:
                self.logger.debug(
                    "Failed to close QBuffer after blank mask encode",
                    exc_info=True,
                )
        if cancelled or self.is_cancelled:
            self.emit_finished(False, payload=self)
            self.finished.emit(self)
            return
        succeeded = self.error is None
        self.emit_finished(succeeded, payload=self, error=self.error)
        if not succeeded:
            self.finished.emit(self)
