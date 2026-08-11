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
"""Cancellable asynchronous projection of stable canvas content references."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QImage, QTransform
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
)
from qpane.sdk.rendering import (
    RegionSampleSource,
    SceneRegionRasterizer,
    rasterize_region,
)
from qpane.sdk.scene import SceneDescriptor

from .document import CanvasContentReference

_MAX_PROJECTION_BYTES = 512 * 1024 * 1024


class CanvasProjectionStatus(str, Enum):
    """Describe one terminal projection outcome."""

    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    STALE = "stale"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CanvasProjectionRequest:
    """Describe source-space bounds and output resolution for one projection."""

    reference: CanvasContentReference
    source_bounds: QRectF
    pixel_size: QSize

    def __post_init__(self) -> None:
        """Detach Qt values and reject invalid or unbounded output."""
        bounds = QRectF(self.source_bounds)
        pixel_size = QSize(self.pixel_size)
        if bounds.isEmpty():
            raise ValueError("projection source bounds must be positive")
        if pixel_size.isEmpty():
            raise ValueError("projection pixel size must be positive")
        if pixel_size.width() * pixel_size.height() * 4 > _MAX_PROJECTION_BYTES:
            raise ValueError("projection exceeds the 512 MiB output limit")
        object.__setattr__(self, "source_bounds", bounds)
        object.__setattr__(self, "pixel_size", pixel_size)


@dataclass(frozen=True, slots=True)
class CanvasProjectionResult:
    """Return a detached image and the exact terminal request status."""

    request_id: uuid.UUID
    request: CanvasProjectionRequest
    status: CanvasProjectionStatus
    image: QImage | None = None
    message: str = ""

    @property
    def succeeded(self) -> bool:
        """Return whether the projection completed with current content."""
        return self.status is CanvasProjectionStatus.COMPLETED


class CanvasProjectionHandle:
    """Cancel one pending projection without retaining its canvas widget."""

    def __init__(
        self,
        request_id: uuid.UUID,
        cancel: Callable[[uuid.UUID], bool],
    ) -> None:
        """Bind one opaque identity to the service cancellation boundary."""
        self._request_id = request_id
        self._cancel = cancel

    @property
    def request_id(self) -> uuid.UUID:
        """Return the stable request identity."""
        return self._request_id

    def cancel(self) -> bool:
        """Cancel pending work and publish one terminal cancellation."""
        return self._cancel(self._request_id)


@dataclass(frozen=True, slots=True)
class SceneProjectionSource:
    """Adapt one immutable scene revision to QPane's region-sampling contract."""

    source_id: uuid.UUID
    revision_key: Hashable
    scene: SceneDescriptor
    rasterizer: SceneRegionRasterizer

    @property
    def source_kind(self) -> str:
        """Return the stable worker category namespace."""
        return "canvas-projection"

    def sample(self, source_rect: QRectF, pixel_size: QSize) -> QImage:
        """Render exactly the requested scene-space window."""
        scale_x = pixel_size.width() / source_rect.width()
        scale_y = pixel_size.height() / source_rect.height()
        scene_to_pixels = QTransform(
            scale_x,
            0.0,
            0.0,
            scale_y,
            -source_rect.x() * scale_x,
            -source_rect.y() * scale_y,
        )
        return self.rasterizer.rasterize(
            self.scene,
            QSize(pixel_size),
            scene_to_pixels,
        )


@dataclass(slots=True)
class _PendingProjection:
    """Retain one request and lifecycle handle until terminal publication."""

    request: CanvasProjectionRequest
    handle: ExecutionHandle[QImage, object] | None = None


class CanvasProjectionService:
    """Schedule scene projections and reject results invalidated by edits."""

    def __init__(
        self,
        *,
        execution_scope: ExecutionScope,
        resolve_source: Callable[
            [CanvasContentReference],
            tuple[RegionSampleSource, QRectF],
        ],
        is_current: Callable[[CanvasContentReference], bool],
        completed: Callable[[CanvasProjectionResult], None],
    ) -> None:
        """Bind the renderer adapter, revision authority, and result callback."""
        self._execution_scope = execution_scope.open_child(
            f"{execution_scope.owner_id}:projection"
        )
        self._resolve_source = resolve_source
        self._is_current = is_current
        self._completed = completed
        self._pending: dict[uuid.UUID, _PendingProjection] = {}
        self._closed = False

    def request(
        self,
        reference: CanvasContentReference,
        *,
        source_bounds: QRectF | None = None,
        pixel_size: QSize | None = None,
    ) -> CanvasProjectionHandle:
        """Begin one bounded projection through the shared scene renderer."""
        if self._closed:
            raise RuntimeError("projection service is closed")
        if not self._is_current(reference):
            return self._terminal(
                reference,
                source_bounds,
                pixel_size,
                CanvasProjectionStatus.STALE,
                "content changed before projection began",
            )
        source, default_bounds = self._resolve_source(reference)
        bounds = QRectF(default_bounds if source_bounds is None else source_bounds)
        size = QSize(_default_pixel_size(bounds) if pixel_size is None else pixel_size)
        request = CanvasProjectionRequest(reference, bounds, size)
        request_id = uuid.uuid4()
        pending = _PendingProjection(request)
        self._pending[request_id] = pending
        execution_request = ExecutionRequest(
            operation="editor.canvas.project",
            requirements=ExecutionRequirements(
                resource=ExecutionResource.NATIVE_CPU,
                urgency=ExecutionUrgency.FOREGROUND,
                estimated_retained_bytes=size.width() * size.height() * 4,
            ),
            work=lambda context: rasterize_region(
                source,
                bounds,
                size,
                context.cancellation,
            ),
        )
        try:
            handle = self._execution_scope.submit(
                execution_request,
                adopt=lambda image: self._finish(request_id, image),
            )
        except ExecutionRejected as exc:
            self._pending.pop(request_id, None)
            self._completed(
                CanvasProjectionResult(
                    request_id,
                    request,
                    CanvasProjectionStatus.REJECTED,
                    message=str(exc),
                )
            )
            return CanvasProjectionHandle(request_id, lambda _request_id: False)
        if self._pending.get(request_id) is pending:
            pending.handle = handle
        handle.add_done_callback(
            lambda outcome: self._settle(request_id, handle, outcome)
        )
        return CanvasProjectionHandle(request_id, self.cancel)

    def cancel(self, request_id: uuid.UUID) -> bool:
        """Cancel one pending request and publish exactly one terminal result."""
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return False
        if pending.handle is not None:
            pending.handle.cancel(reason="projection cancelled")
        self._completed(
            CanvasProjectionResult(
                request_id,
                pending.request,
                CanvasProjectionStatus.CANCELLED,
                message="projection cancelled",
            )
        )
        return True

    def shutdown(self) -> None:
        """Cancel every pending projection and suppress future requests."""
        if self._closed:
            return
        self._closed = True
        for request_id in tuple(self._pending):
            self.cancel(request_id)
        self._execution_scope.close(reason="canvas_projection_shutdown")

    def _finish(self, request_id: uuid.UUID, image: QImage) -> None:
        """Publish a current image or discard a stale render product."""
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        if not self._is_current(pending.request.reference):
            result = CanvasProjectionResult(
                request_id,
                pending.request,
                CanvasProjectionStatus.STALE,
                message="content changed during projection",
            )
        else:
            result = CanvasProjectionResult(
                request_id,
                pending.request,
                CanvasProjectionStatus.COMPLETED,
                QImage(image),
            )
        self._completed(result)

    def _settle(
        self,
        request_id: uuid.UUID,
        handle: ExecutionHandle[QImage, object],
        outcome: ExecutionOutcome[QImage],
    ) -> None:
        """Publish non-successful execution outcomes exactly once."""
        if outcome.state == ExecutionState.SUCCEEDED:
            return
        pending = self._pending.get(request_id)
        if pending is None or (
            pending.handle is not None and pending.handle is not handle
        ):
            return
        self._pending.pop(request_id, None)
        cancelled = outcome.state == ExecutionState.CANCELLED
        message = outcome.cancellation_reason if cancelled else str(outcome.error)
        self._completed(
            CanvasProjectionResult(
                request_id,
                pending.request,
                (
                    CanvasProjectionStatus.CANCELLED
                    if cancelled
                    else CanvasProjectionStatus.FAILED
                ),
                message=message or "projection did not complete",
            )
        )

    def _terminal(
        self,
        reference: CanvasContentReference,
        source_bounds: QRectF | None,
        pixel_size: QSize | None,
        status: CanvasProjectionStatus,
        message: str,
    ) -> CanvasProjectionHandle:
        """Publish a request rejected before a render source is captured."""
        bounds = QRectF(source_bounds or QRectF(0.0, 0.0, 1.0, 1.0))
        size = QSize(pixel_size or QSize(1, 1))
        request_id = uuid.uuid4()
        self._completed(
            CanvasProjectionResult(
                request_id,
                CanvasProjectionRequest(reference, bounds, size),
                status,
                message=message,
            )
        )
        return CanvasProjectionHandle(request_id, lambda _request_id: False)


def _default_pixel_size(bounds: QRectF) -> QSize:
    """Return the nearest containing native-size raster for source bounds."""
    return QSize(
        max(1, math.ceil(bounds.width())),
        max(1, math.ceil(bounds.height())),
    )
