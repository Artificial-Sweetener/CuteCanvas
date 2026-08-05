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

"""Teach scoped background image loading through QPane's execution SDK."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtGui import QImage, QImageReader
from qpane import (
    ExecutionOutcome,
    ExecutionRejected,
    ExecutionRequest,
    ExecutionRequirements,
    ExecutionResource,
    ExecutionRuntime,
    ExecutionState,
    ExecutionTaskContext,
    ExecutionUrgency,
    QtOwnerDispatcher,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _DecodedImage:
    """Carry one detached decoder result to the GUI owner."""

    path: Path
    image: QImage


@dataclass(slots=True)
class _LoadBatch:
    """Track callbacks and settlement for one host load request."""

    remaining: int
    loaded: int
    image_loaded: Callable[[Path, QImage], None]
    finished: Callable[[int], None]


class ImageLoadCoordinator(QObject):
    """Own demo image-decode requests over a shared host runtime."""

    def __init__(
        self,
        execution_runtime: ExecutionRuntime,
        parent: QObject | None = None,
    ) -> None:
        """Open a receiver-safe scope for this coordinator's lifetime."""
        super().__init__(parent)
        self._execution_scope = execution_runtime.open_scope(
            owner_id=f"cutecanvas-demo:image-loads:{id(self)}",
            dispatcher=QtOwnerDispatcher(self),
        )
        self._batches: dict[uuid.UUID, _LoadBatch] = {}
        self._closed = False

    def submit(
        self,
        paths: Iterable[Path],
        *,
        image_loaded: Callable[[Path, QImage], None],
        finished: Callable[[int], None],
    ) -> uuid.UUID:
        """Decode paths independently and adopt each image on this Qt thread."""
        path_batch = tuple(Path(path) for path in paths)
        if not path_batch:
            raise ValueError("paths must contain at least one image")
        if self._closed:
            raise RuntimeError("image load coordinator is closed")
        request_id = uuid.uuid4()
        self._batches[request_id] = _LoadBatch(
            remaining=len(path_batch),
            loaded=0,
            image_loaded=image_loaded,
            finished=finished,
        )
        for path in path_batch:
            request = ExecutionRequest[_DecodedImage, object](
                operation="demo.image.decode",
                work=partial(_decode_image, path),
                requirements=ExecutionRequirements(
                    resource=ExecutionResource.BLOCKING_IO,
                    urgency=ExecutionUrgency.FOREGROUND,
                ),
                tags=(("path", str(path)),),
            )
            try:
                handle = self._execution_scope.submit(
                    request,
                    adopt=partial(self._adopt_image, request_id),
                )
            except ExecutionRejected as error:
                logger.warning("Image decode was rejected for %s: %s", path, error)
                self._settle_path(request_id)
                continue
            handle.add_done_callback(partial(self._handle_outcome, request_id))
        return request_id

    @property
    def active_count(self) -> int:
        """Return the number of batches with unsettled decoder work."""
        return len(self._batches)

    def close(self) -> None:
        """Cancel pending loads and suppress callbacks after owner teardown."""
        if self._closed:
            return
        self._closed = True
        self._batches.clear()
        self._execution_scope.close(reason="demo_image_loads_closed")

    def _adopt_image(self, request_id: uuid.UUID, decoded: _DecodedImage) -> None:
        """Deliver one decoded image without letting host callback errors escape."""
        batch = self._batches.get(request_id)
        if batch is None:
            return
        try:
            batch.image_loaded(decoded.path, decoded.image)
        except Exception:
            logger.exception(
                "Image load callback failed",
                extra={"request_id": str(request_id), "path": str(decoded.path)},
            )
        else:
            batch.loaded += 1

    def _handle_outcome(
        self,
        request_id: uuid.UUID,
        outcome: ExecutionOutcome[_DecodedImage],
    ) -> None:
        """Log decoder failures and settle one path in its request batch."""
        if outcome.state == ExecutionState.FAILED:
            logger.warning(
                "Image decode failed",
                exc_info=(
                    (
                        type(outcome.error),
                        outcome.error,
                        outcome.error.__traceback__,
                    )
                    if outcome.error is not None
                    else None
                ),
            )
        self._settle_path(request_id)

    def _settle_path(self, request_id: uuid.UUID) -> None:
        """Publish terminal batch progress after every path settles."""
        batch = self._batches.get(request_id)
        if batch is None:
            return
        batch.remaining -= 1
        if batch.remaining > 0:
            return
        self._batches.pop(request_id, None)
        try:
            batch.finished(batch.loaded)
        except Exception:
            logger.exception(
                "Image load completion callback failed",
                extra={"request_id": str(request_id)},
            )


def _decode_image(
    path: Path,
    context: ExecutionTaskContext[object],
) -> _DecodedImage:
    """Decode one image without touching Qt-owned application state."""
    context.cancellation.raise_if_cancelled()
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    image = reader.read()
    context.cancellation.raise_if_cancelled()
    if image.isNull():
        raise OSError(reader.errorString() or f"Unable to decode {path}")
    return _DecodedImage(path=path, image=image)
