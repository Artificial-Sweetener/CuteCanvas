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

"""Coordinate bounded pyramid submission, retry, cancellation, and terminal cleanup."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtGui import QImage

from ..execution import (
    ExecutionHandle,
    ExecutionOutcome,
    ExecutionRejected,
    ExecutionRequest,
    ExecutionRequirements,
    ExecutionResource,
    ExecutionScope,
    ExecutionState,
    ExecutionUrgency,
    RetryController,
    RetryPolicy,
)
from ..execution.qt_delay import QtDelayScheduler
from ..scene.identity import SourceRenderAssetKey
from .pyramid_generation import generate_pyramid
from .pyramid_model import ImagePyramid, PyramidStatus

logger = logging.getLogger(__name__)

_PYRAMID_RETRY_BASE_MS = 75
_PYRAMID_RETRY_MAX_MS = 1500


class PyramidWorkCoordinator:
    """Own all asynchronous work and retry state for one pyramid manager."""

    def __init__(
        self,
        scope: ExecutionScope,
        delay_parent: QObject,
        *,
        generated: Callable[[ImagePyramid], None],
        terminal: Callable[
            [SourceRenderAssetKey, ExecutionOutcome[ImagePyramid]], None
        ],
        throttled: Callable[[SourceRenderAssetKey, int, ExecutionRejected], None],
        started: Callable[[SourceRenderAssetKey], None],
    ) -> None:
        """Bind lifecycle callbacks and create one focused child execution scope."""
        self._scope = scope.open_child(f"{scope.owner_id}:pyramids")
        self._generated = generated
        self._terminal = terminal
        self._throttled = throttled
        self._started = started
        self._active: dict[
            SourceRenderAssetKey,
            ExecutionHandle[ImagePyramid, object],
        ] = {}
        self._retry: RetryController[
            SourceRenderAssetKey,
            ImagePyramid,
            ImagePyramid,
            object,
        ] = RetryController(
            "pyramid",
            RetryPolicy(
                base_ms=_PYRAMID_RETRY_BASE_MS,
                max_ms=_PYRAMID_RETRY_MAX_MS,
            ),
            QtDelayScheduler(delay_parent),
        )

    @property
    def active_count(self) -> int:
        """Return the number of submitted nonterminal jobs."""
        return len(self._active)

    def is_active(self, asset_key: SourceRenderAssetKey) -> bool:
        """Return whether generation is active for one source product."""
        return asset_key in self._active

    def pending_asset_keys(self) -> set[SourceRenderAssetKey]:
        """Return a detached snapshot of active source identities."""
        return set(self._active)

    def pending_retry_asset_keys(self) -> list[SourceRenderAssetKey]:
        """Return source identities currently queued for retry."""
        return list(self._retry.pending_keys())

    def retry_snapshot(self):
        """Return immutable retry diagnostics."""
        return self._retry.snapshot()

    def request(self, pyramid: ImagePyramid, min_view_size_px: int) -> None:
        """Submit or coalesce exact generation for one source product."""

        def submit(
            candidate: ImagePyramid,
            attempt: int,
        ) -> ExecutionHandle[ImagePyramid, object]:
            """Submit the candidate unless it already has active generation."""
            handle = self._active.get(candidate.asset_key)
            if handle is not None:
                return handle
            source_image = QImage(candidate.full_resolution_image)
            request: ExecutionRequest[ImagePyramid, object] = ExecutionRequest(
                operation="render.pyramid",
                requirements=ExecutionRequirements(
                    resource=ExecutionResource.NATIVE_CPU,
                    urgency=ExecutionUrgency.FOREGROUND,
                    estimated_retained_bytes=max(0, int(source_image.sizeInBytes())),
                ),
                tags=(("attempt", attempt),),
                work=lambda context: generate_pyramid(
                    candidate.asset_key,
                    source_image,
                    min_view_size_px,
                    context.cancellation,
                    candidate.reconstruction_space,
                ),
            )
            candidate.status = PyramidStatus.GENERATING
            try:
                handle = self._scope.submit(request, adopt=self._adopt_generated)
            except ExecutionRejected:
                candidate.status = PyramidStatus.PENDING
                raise
            handle.add_done_callback(
                lambda outcome: self._apply_outcome(candidate.asset_key, outcome)
            )
            if not handle.state.is_terminal:
                self._active[candidate.asset_key] = handle
                self._started(candidate.asset_key)
            logger.info("Queued pyramid generation for %s", candidate.asset_key)
            return handle

        def coalesce(old: ImagePyramid, new: ImagePyramid) -> ImagePyramid:
            """Adopt the newest full-resolution source before a retry."""
            old.full_resolution_image = new.full_resolution_image
            return old

        self._retry.submit_or_coalesce(
            pyramid.asset_key,
            pyramid,
            submit=submit,
            rejected=self._throttled,
            merge=coalesce,
        )

    def cancel_active(self, asset_key: SourceRenderAssetKey, *, reason: str) -> bool:
        """Cancel active generation without changing retained product state."""
        handle = self._active.pop(asset_key, None)
        return (
            handle.cancel(reason=f"pyramid_{reason}") if handle is not None else False
        )

    def cancel_retry(self, asset_key: SourceRenderAssetKey) -> None:
        """Cancel a queued retry for one source product."""
        self._retry.cancel(asset_key)

    def close(self) -> None:
        """Cancel all work and release coordinator bookkeeping."""
        self._retry.cancel_all()
        for asset_key, handle in list(self._active.items()):
            cancelled = handle.cancel(reason="pyramid_manager_shutdown")
            logger.info(
                "Requested cancellation for pyramid %s (cancelled=%s)",
                asset_key,
                cancelled,
            )
        self._active.clear()
        self._scope.close(reason="pyramid_manager_shutdown")

    def cancel_all(self, *, reason: str) -> None:
        """Cancel all current generations and retries while retaining the scope."""
        self._retry.cancel_all()
        for asset_key, handle in list(self._active.items()):
            handle.cancel(reason=f"pyramid_{reason}")
            self._active.pop(asset_key, None)

    def _adopt_generated(self, pyramid: ImagePyramid) -> None:
        """Complete work bookkeeping before manager-owned product adoption."""
        self._active.pop(pyramid.asset_key, None)
        self._retry.complete(pyramid.asset_key)
        self._generated(pyramid)

    def _apply_outcome(
        self,
        asset_key: SourceRenderAssetKey,
        outcome: ExecutionOutcome[ImagePyramid],
    ) -> None:
        """Complete failed or cancelled bookkeeping and notify the manager."""
        if outcome.state == ExecutionState.SUCCEEDED:
            return
        self._active.pop(asset_key, None)
        self._retry.complete(asset_key)
        self._terminal(asset_key, outcome)


__all__ = ["PyramidWorkCoordinator"]
