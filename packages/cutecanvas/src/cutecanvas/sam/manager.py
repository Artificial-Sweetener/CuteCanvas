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

"""Coordinate thread-affine predictor preparation, inference, and cache state."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage
from qpane.sdk.execution import (
    ExecutionHandle,
    ExecutionLeaseRelease,
    ExecutionOutcome,
    ExecutionRejected,
    ExecutionRequest,
    ExecutionRequirements,
    ExecutionResource,
    ExecutionScope,
    ExecutionState,
    ExecutionUrgency,
    InlineDispatcher,
    QtDelayScheduler,
    RetryController,
    RetryPolicy,
)

from .products import (
    SamCacheMutationProduct,
    SamMaskProduct,
    SamPredictorReference,
    SamPreparationProduct,
    SamSessionSnapshot,
)
from .session import SamNativeSession

if TYPE_CHECKING:
    from .checkpoint_coordination import CheckpointAcquisition

logger = logging.getLogger(__name__)

_SAM_RETRY_BASE_DELAY_MS = 150
_SAM_RETRY_MAX_DELAY_MS = 2500
_DEFAULT_PREDICTOR_ESTIMATE_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SamPredictorMetrics:
    """Describe predictor cache and asynchronous activity."""

    cache_bytes: int
    cache_count: int
    active_jobs: int
    pending_retries: int
    hits: int
    misses: int
    cache_limit: int = 0
    evictions: int = 0
    evicted_bytes: int = 0
    last_eviction_reason: str | None = None
    last_eviction_timestamp: float | None = None
    prefetch_requested: int = 0
    prefetch_completed: int = 0
    prefetch_failed: int = 0
    last_prefetch_ms: float | None = None


@dataclass(slots=True)
class _PendingPreparation:
    """Retain one current preparation request per image."""

    request_id: uuid.UUID
    estimate_bytes: int
    handle: ExecutionHandle[SamPreparationProduct, object] | None = None


@dataclass(frozen=True, slots=True)
class _PreparationPayload:
    """Retain immutable retry inputs for one predictor request."""

    image: QImage
    image_id: uuid.UUID
    source_path: Path | None


class SamManager(QObject):
    """Expose assisted-selection readiness over a native affinity session."""

    predictorReady = Signal(object, uuid.UUID)
    predictorLoadFailed = Signal(uuid.UUID, str)
    predictorThrottled = Signal(uuid.UUID, int)
    predictorCacheCleared = Signal()
    predictorRemoved = Signal(uuid.UUID)
    maskReady = Signal(object, np.ndarray, bool, object)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        device: str = "cpu",
        execution_scope: ExecutionScope,
        cache_limit: int | None = None,
        checkpoint_path: Path,
        checkpoint_acquisition: CheckpointAcquisition | None = None,
    ) -> None:
        """Bind one manager to a shared runtime and one native device lane."""
        super().__init__(parent)
        self._device = str(device)
        self._checkpoint_path = Path(checkpoint_path)
        self._checkpoint_acquisition = checkpoint_acquisition
        self._cache_limit = self._sanitize_cache_limit(cache_limit)
        self._execution_scope = execution_scope.open_child(
            f"{execution_scope.owner_id}:sam:{self._device}"
        )
        self._cleanup_scope = execution_scope.open_finalization_scope(
            f"{self._execution_scope.owner_id}:cleanup",
            dispatcher=InlineDispatcher(),
        )
        self._session = SamNativeSession(
            checkpoint_path=self._checkpoint_path,
            device=self._device,
            cache_limit=self._cache_limit,
        )
        self._references: dict[uuid.UUID, SamPredictorReference] = {}
        self._predictor_sizes: dict[uuid.UUID, int] = {}
        self._predictor_paths: dict[uuid.UUID, Path | None] = {}
        self._pending: dict[uuid.UUID, _PendingPreparation] = {}
        self._inference_handles: dict[
            uuid.UUID,
            ExecutionHandle[SamMaskProduct, object],
        ] = {}
        self._inference_contexts: dict[uuid.UUID, object | None] = {}
        self._cache_handles: dict[
            uuid.UUID,
            ExecutionHandle[SamCacheMutationProduct, object],
        ] = {}
        self._cache_hits = 0
        self._cache_misses = 0
        self._evictions = 0
        self._evicted_bytes = 0
        self._session_may_own_native_resources = False
        self._closing = False
        self._shutdown_handle: (
            ExecutionHandle[SamCacheMutationProduct, object] | None
        ) = None
        self._retry: RetryController[
            tuple[uuid.UUID, str],
            _PreparationPayload,
            SamPreparationProduct,
            object,
        ] = RetryController(
            "editor.sam.prepare",
            RetryPolicy(
                base_ms=_SAM_RETRY_BASE_DELAY_MS,
                max_ms=_SAM_RETRY_MAX_DELAY_MS,
            ),
            QtDelayScheduler(self),
        )

    def retrySnapshot(self):
        """Return predictor retry telemetry for diagnostics."""
        return self._retry.snapshot()

    def checkpointPath(self) -> Path:
        """Return the configured model checkpoint path."""
        return self._checkpoint_path

    def checkpointReady(self) -> bool:
        """Return whether the configured checkpoint exists."""
        return self._checkpoint_path.exists()

    def getCachedPredictorCount(self) -> int:
        """Return prepared predictor count from adopted session metadata."""
        return len(self._references)

    def predictorImageIds(self) -> list[uuid.UUID]:
        """Return prepared image identities."""
        return list(self._references)

    def cache_usage_bytes(self) -> int:
        """Return measured native predictor storage."""
        return sum(self._predictor_sizes.values())

    def pendingUsageBytes(self) -> int:
        """Return memory estimates retained by current preparation requests."""
        return sum(pending.estimate_bytes for pending in self._pending.values())

    def snapshot_metrics(self) -> SamPredictorMetrics:
        """Return cache, retry, and operation metrics."""
        return SamPredictorMetrics(
            cache_bytes=self.cache_usage_bytes(),
            cache_count=len(self._references),
            active_jobs=self.activePredictorLoads(),
            pending_retries=len(tuple(self._retry.pending_keys())),
            hits=self._cache_hits,
            misses=self._cache_misses,
            cache_limit=self._cache_limit,
            evictions=self._evictions,
            evicted_bytes=self._evicted_bytes,
        )

    def activePredictorLoads(self) -> int:
        """Return all accepted native-session operations."""
        return (
            len(self._pending) + len(self._inference_handles) + len(self._cache_handles)
        )

    def getPredictor(
        self,
        image_id: uuid.UUID,
    ) -> SamPredictorReference | None:
        """Return an opaque prepared-predictor reference."""
        reference = self._references.get(image_id)
        if reference is not None:
            self._cache_hits += 1
        return reference

    def requestPredictor(
        self,
        image: QImage,
        image_id: uuid.UUID,
        *,
        source_path: Path | None = None,
    ) -> None:
        """Prepare one image predictor without blocking the GUI thread."""
        reference = self.getPredictor(image_id)
        if reference is not None:
            self.predictorReady.emit(reference, image_id)
            return
        if self._closing or not self.checkpointReady():
            if not self.checkpointReady():
                logger.warning(
                    "Predictor request skipped because checkpoint is missing at %s",
                    self._checkpoint_path,
                )
            return
        if image_id in self._pending:
            return
        self._cache_misses += 1
        payload = _PreparationPayload(QImage(image), image_id, source_path)
        self._predictor_paths[image_id] = source_path
        self._retry.submit_or_coalesce(
            self._retry_key(image_id),
            payload,
            submit=self._submit_preparation,
            rejected=self._report_preparation_rejection,
            merge=lambda _old, new: new,
        )

    def cancelPendingPredictor(self, image_id: uuid.UUID) -> bool:
        """Cancel delayed or accepted preparation for one image."""
        self._retry.cancel(self._retry_key(image_id))
        pending = self._pending.pop(image_id, None)
        if pending is None or pending.handle is None:
            return False
        return pending.handle.cancel(reason="SAM predictor preparation cancelled")

    def generateMaskFromBox(
        self,
        image_id: uuid.UUID,
        bbox: np.ndarray,
        erase_mode: bool = False,
        *,
        context: object | None = None,
    ) -> bool:
        """Submit box inference while retaining caller context until adoption."""
        normalized_bbox = np.asarray(bbox).copy()
        if normalized_bbox.shape not in {(4,), (1, 4)}:
            logger.warning(
                "SAM inference requires four bounding-box coordinates; got %s",
                normalized_bbox.shape,
            )
            self.maskReady.emit(None, normalized_bbox, erase_mode, context)
            return False
        if image_id not in self._references:
            self.maskReady.emit(None, normalized_bbox, erase_mode, context)
            return False
        request_id = uuid.uuid4()
        request = ExecutionRequest[SamMaskProduct, object](
            operation="editor.sam.infer_box",
            requirements=self._native_requirements(
                urgency=ExecutionUrgency.INTERACTIVE
            ),
            tags=(("image_id", str(image_id)),),
            work=lambda context: self._session.predict(
                image_id,
                normalized_bbox,
                erase_mode,
                context.cancellation,
            ),
        )
        try:
            handle = self._execution_scope.submit(
                request,
                adopt=lambda product: self._adopt_mask(request_id, product),
            )
        except ExecutionRejected as rejection:
            logger.warning("SAM inference rejected: %s", rejection)
            self.maskReady.emit(None, normalized_bbox, erase_mode, context)
            return False
        self._inference_handles[request_id] = handle
        self._inference_contexts[request_id] = context
        handle.add_done_callback(
            lambda outcome: self._settle_mask(
                request_id, normalized_bbox, erase_mode, outcome
            )
        )
        return True

    def clearCache(self) -> None:
        """Cancel preparations and asynchronously destroy all native predictors."""
        for image_id in tuple(self._pending):
            self.cancelPendingPredictor(image_id)
        self._retry.cancel_all()
        self._submit_cache_mutation(
            operation="editor.sam.cache.clear",
            work=lambda _context: self._session.clear(),
            adopt=self._adopt_clear,
        )

    def removeFromCache(self, image_id: uuid.UUID) -> bool:
        """Asynchronously destroy one prepared predictor."""
        self._retry.cancel(self._retry_key(image_id))
        self.cancelPendingPredictor(image_id)
        if image_id not in self._references:
            return False
        return self._submit_cache_mutation(
            operation="editor.sam.cache.remove",
            work=lambda context: self._session.remove(
                image_id,
                context.cancellation,
            ),
            adopt=self._adopt_cache_mutation,
        )

    def cacheLimit(self) -> int:
        """Return maximum prepared predictors retained by the session."""
        return self._cache_limit

    def setCacheLimit(self, limit: int | None) -> None:
        """Apply a new cache limit on the native affinity lane."""
        normalized = self._sanitize_cache_limit(limit)
        if normalized == self._cache_limit:
            return
        self._cache_limit = normalized
        self._submit_cache_mutation(
            operation="editor.sam.cache.limit",
            work=lambda context: self._session.set_cache_limit(
                normalized,
                context.cancellation,
            ),
            adopt=self._adopt_cache_mutation,
        )

    def shutdown(
        self,
    ) -> ExecutionHandle[SamCacheMutationProduct, object] | None:
        """Cancel public work and return accepted native-session finalization."""
        if self._closing:
            return self._shutdown_handle
        self._closing = True
        if self._checkpoint_acquisition is not None:
            self._checkpoint_acquisition.close()
            self._checkpoint_acquisition = None
        self._retry.cancel_all()
        for image_id in tuple(self._pending):
            self.cancelPendingPredictor(image_id)
        for handle in tuple(self._inference_handles.values()):
            handle.cancel(reason="SAM manager shutdown")
        for handle in tuple(self._cache_handles.values()):
            handle.cancel(reason="SAM manager shutdown")
        self._inference_handles.clear()
        self._inference_contexts.clear()
        self._cache_handles.clear()
        if not self._session_may_own_native_resources:
            self._close_execution_scopes(reason="sam_shutdown_empty")
            return None
        request = ExecutionRequest[SamCacheMutationProduct, object](
            operation="editor.sam.session.close",
            requirements=self._native_requirements(
                urgency=ExecutionUrgency.MAINTENANCE
            ),
            work=lambda _context: self._session.clear(),
        )
        try:
            handle = self._cleanup_scope.submit(request)
        except ExecutionRejected as rejection:
            logger.warning("Native SAM session cleanup was rejected: %s", rejection)
            self._close_execution_scopes(reason="sam_shutdown_rejected")
            return None
        self._shutdown_handle = handle
        handle.add_done_callback(
            lambda _outcome: self._close_execution_scopes(
                reason="sam_shutdown_complete"
            )
        )
        return handle

    def _submit_preparation(
        self,
        payload: _PreparationPayload,
        attempt: int,
    ) -> ExecutionHandle[SamPreparationProduct, object]:
        """Submit one retained preparation payload."""
        request_id = uuid.uuid4()
        estimate = self._estimate_predictor_bytes(payload.image)
        pending = _PendingPreparation(request_id, estimate)
        request = ExecutionRequest[SamPreparationProduct, object](
            operation="editor.sam.prepare",
            requirements=self._native_requirements(
                urgency=ExecutionUrgency.FOREGROUND,
                estimated_retained_bytes=estimate,
            ),
            tags=(
                ("image_id", str(payload.image_id)),
                ("attempt", attempt),
            ),
            work=lambda context: self._session.prepare(
                payload.image,
                payload.image_id,
                context.cancellation,
            ),
        )
        handle = self._execution_scope.submit(
            request,
            adopt=lambda product: self._adopt_preparation(
                payload.image_id,
                request_id,
                product,
            ),
        )
        self._session_may_own_native_resources = True
        pending.handle = handle
        self._pending[payload.image_id] = pending
        handle.add_done_callback(
            lambda outcome: self._settle_preparation(
                payload.image_id,
                request_id,
                outcome,
            )
        )
        return handle

    def _adopt_preparation(
        self,
        image_id: uuid.UUID,
        request_id: uuid.UUID,
        product: SamPreparationProduct,
    ) -> None:
        """Publish one current preparation and its derived cache metadata."""
        pending = self._pending.get(image_id)
        if pending is None or pending.request_id != request_id:
            return
        self._pending.pop(image_id, None)
        self._adopt_snapshot(product.snapshot)
        self._record_evictions(product.evicted_ids)
        self.predictorReady.emit(product.reference, image_id)

    def _settle_preparation(
        self,
        image_id: uuid.UUID,
        request_id: uuid.UUID,
        outcome: ExecutionOutcome[SamPreparationProduct],
    ) -> None:
        """Clear failed or cancelled preparation without stale publication."""
        if outcome.state == ExecutionState.SUCCEEDED:
            return
        pending = self._pending.get(image_id)
        if pending is None or pending.request_id != request_id:
            return
        self._pending.pop(image_id, None)
        if outcome.state == ExecutionState.FAILED:
            message = str(outcome.error or "predictor preparation failed")
            self.predictorLoadFailed.emit(image_id, message)

    def _report_preparation_rejection(
        self,
        key: tuple[uuid.UUID, str],
        attempt: int,
        rejection: ExecutionRejected,
    ) -> None:
        """Report saturation while the retry owner retains the latest image."""
        image_id, _device = key
        logger.warning(
            "SAM predictor preparation rejected for %s (%s): %s",
            image_id,
            rejection.reason.value,
            rejection,
        )
        self.predictorThrottled.emit(image_id, attempt)

    def _adopt_mask(self, request_id: uuid.UUID, product: SamMaskProduct) -> None:
        """Emit one current inference product."""
        if request_id not in self._inference_handles:
            return
        self._inference_handles.pop(request_id, None)
        context = self._inference_contexts.pop(request_id, None)
        self.maskReady.emit(product.mask, product.bbox, product.erase_mode, context)

    def _settle_mask(
        self,
        request_id: uuid.UUID,
        bbox: np.ndarray,
        erase_mode: bool,
        outcome: ExecutionOutcome[SamMaskProduct],
    ) -> None:
        """Settle inference failures exactly once."""
        if outcome.state == ExecutionState.SUCCEEDED:
            return
        if self._inference_handles.pop(request_id, None) is None:
            return
        context = self._inference_contexts.pop(request_id, None)
        if outcome.state == ExecutionState.FAILED:
            logger.error("SAM inference failed: %s", outcome.error)
            self.maskReady.emit(None, bbox, erase_mode, context)

    def _submit_cache_mutation(
        self,
        *,
        operation: str,
        work,
        adopt,
    ) -> bool:
        """Submit one serialized native cache mutation."""
        request = ExecutionRequest[SamCacheMutationProduct, object](
            operation=operation,
            requirements=self._native_requirements(urgency=ExecutionUrgency.FOREGROUND),
            work=work,
        )
        try:
            handle = self._execution_scope.submit(request, adopt=adopt)
        except ExecutionRejected as rejection:
            logger.warning("SAM cache mutation rejected: %s", rejection)
            return False
        self._cache_handles[handle.task_id] = handle
        handle.add_done_callback(
            lambda outcome: self._settle_cache_mutation(handle.task_id, outcome)
        )
        return True

    def _settle_cache_mutation(
        self,
        task_id: uuid.UUID,
        outcome: ExecutionOutcome[SamCacheMutationProduct],
    ) -> None:
        """Release cache-operation bookkeeping and log terminal failure."""
        self._cache_handles.pop(task_id, None)
        if outcome.state == ExecutionState.FAILED:
            logger.error("SAM cache mutation failed: %s", outcome.error)

    def _adopt_clear(self, product: SamCacheMutationProduct) -> None:
        """Publish one complete cache clear."""
        self._adopt_cache_mutation(product)
        self.predictorCacheCleared.emit()

    def _adopt_cache_mutation(self, product: SamCacheMutationProduct) -> None:
        """Adopt cache metadata and report every removed predictor."""
        self._record_evictions(product.removed_ids)
        self._adopt_snapshot(product.snapshot)

    def _adopt_snapshot(self, snapshot: SamSessionSnapshot) -> None:
        """Replace derived UI cache metadata from the native authority."""
        current = set(self._references)
        entries = dict(snapshot.entries)
        self._references = {
            image_id: SamPredictorReference(image_id) for image_id in entries
        }
        self._predictor_sizes = entries
        for removed_id in current.difference(entries):
            self._predictor_paths.pop(removed_id, None)

    def _record_evictions(self, image_ids: tuple[uuid.UUID, ...]) -> None:
        """Update eviction counters and notify observers."""
        for image_id in image_ids:
            self._evicted_bytes += self._predictor_sizes.get(image_id, 0)
            self._evictions += 1
            self.predictorRemoved.emit(image_id)

    def _native_requirements(
        self,
        *,
        urgency: ExecutionUrgency,
        estimated_retained_bytes: int | None = None,
    ) -> ExecutionRequirements:
        """Return the hard session-affinity and exclusion contract."""
        lane = f"sam:{self._device}"
        return ExecutionRequirements(
            resource=ExecutionResource.THREAD_AFFINE_NATIVE,
            urgency=urgency,
            resource_id=self._device,
            exclusive_key=lane,
            affinity_key=lane,
            maximum_concurrency=1,
            lease_release=ExecutionLeaseRelease.ADOPTION_FINISHED,
            estimated_retained_bytes=estimated_retained_bytes,
        )

    def _retry_key(self, image_id: uuid.UUID) -> tuple[uuid.UUID, str]:
        """Return the stable retry identity for one image and device."""
        return image_id, self._device

    def _close_execution_scopes(self, *, reason: str) -> None:
        """Close operation and finalization ownership after cleanup settles."""
        self._execution_scope.close(reason=reason)
        self._cleanup_scope.close(reason=reason)

    @staticmethod
    def _sanitize_cache_limit(limit: int | None) -> int:
        """Normalize missing or invalid cache limits to one predictor."""
        if limit is None:
            return 1
        try:
            return max(0, int(limit))
        except (TypeError, ValueError, OverflowError):
            return 1

    @staticmethod
    def _estimate_predictor_bytes(image: QImage) -> int:
        """Estimate preparation memory using image storage and model floor."""
        try:
            return max(int(image.sizeInBytes()), _DEFAULT_PREDICTOR_ESTIMATE_BYTES)
        except (RuntimeError, TypeError, ValueError, OverflowError):
            return _DEFAULT_PREDICTOR_ESTIMATE_BYTES


__all__ = [
    "SamManager",
    "SamPredictorMetrics",
]
