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

"""Teach scoped image decoding through QPane's public execution SDK."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject, Qt
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
class ViewerImageProduct:
    """Carry decoded pixels and their catalog preview to the GUI owner."""

    path: Path
    image: QImage
    thumbnail: QImage


@dataclass(slots=True)
class _ViewerLoadBatch:
    """Track callbacks until every path in one load request settles."""

    remaining: int
    loaded: Callable[[ViewerImageProduct], None]
    failed: Callable[[Path, str], None]
    finished: Callable[[], None]


class ViewerImageLoadCoordinator(QObject):
    """Own viewer-demo decoding over the runtime shared with QPane."""

    def __init__(
        self,
        execution_runtime: ExecutionRuntime,
        parent: QObject | None = None,
    ) -> None:
        """Open a receiver-safe scope for host-owned load requests."""
        super().__init__(parent)
        self._execution_scope = execution_runtime.open_scope(
            owner_id=f"qpane-demo:image-loads:{id(self)}",
            dispatcher=QtOwnerDispatcher(self),
        )
        self._batches: dict[uuid.UUID, _ViewerLoadBatch] = {}
        self._closed = False

    def submit(
        self,
        paths: Iterable[Path],
        *,
        loaded: Callable[[ViewerImageProduct], None],
        failed: Callable[[Path, str], None],
        finished: Callable[[], None],
    ) -> uuid.UUID:
        """Decode each path independently and deliver on this object's thread."""
        path_batch = tuple(Path(path) for path in paths)
        if not path_batch:
            raise ValueError("paths must contain at least one image")
        if self._closed:
            raise RuntimeError("viewer image load coordinator is closed")
        request_id = uuid.uuid4()
        self._batches[request_id] = _ViewerLoadBatch(
            remaining=len(path_batch),
            loaded=loaded,
            failed=failed,
            finished=finished,
        )
        for path in path_batch:
            request = ExecutionRequest[ViewerImageProduct, object](
                operation="demo.viewer.image.decode",
                work=partial(_decode_viewer_image, path),
                requirements=ExecutionRequirements(
                    resource=ExecutionResource.BLOCKING_IO,
                    urgency=ExecutionUrgency.FOREGROUND,
                ),
                tags=(("path", str(path)),),
            )
            try:
                handle = self._execution_scope.submit(
                    request,
                    adopt=partial(self._adopt_product, request_id),
                )
            except ExecutionRejected as error:
                failed(path, str(error))
                self._settle_path(request_id)
                continue
            handle.add_done_callback(partial(self._handle_outcome, request_id, path))
        return request_id

    def close(self) -> None:
        """Cancel pending host loads and suppress teardown callbacks."""
        if self._closed:
            return
        self._closed = True
        self._batches.clear()
        self._execution_scope.close(reason="viewer_demo_image_loads_closed")

    def _adopt_product(
        self,
        request_id: uuid.UUID,
        product: ViewerImageProduct,
    ) -> None:
        """Deliver one successful product while containing host callback errors."""
        batch = self._batches.get(request_id)
        if batch is None:
            return
        try:
            batch.loaded(product)
        except Exception:
            logger.exception(
                "Viewer image callback failed",
                extra={"request_id": str(request_id), "path": str(product.path)},
            )

    def _handle_outcome(
        self,
        request_id: uuid.UUID,
        path: Path,
        outcome: ExecutionOutcome[ViewerImageProduct],
    ) -> None:
        """Report worker failures and settle one path."""
        batch = self._batches.get(request_id)
        if (
            batch is not None
            and outcome.state == ExecutionState.FAILED
            and outcome.error is not None
        ):
            batch.failed(path, str(outcome.error))
        self._settle_path(request_id)

    def _settle_path(self, request_id: uuid.UUID) -> None:
        """Release one batch and publish its terminal callback exactly once."""
        batch = self._batches.get(request_id)
        if batch is None:
            return
        batch.remaining -= 1
        if batch.remaining > 0:
            return
        self._batches.pop(request_id, None)
        try:
            batch.finished()
        except Exception:
            logger.exception(
                "Viewer image completion callback failed",
                extra={"request_id": str(request_id)},
            )


def _decode_viewer_image(
    path: Path,
    context: ExecutionTaskContext[object],
) -> ViewerImageProduct:
    """Decode full pixels and a catalog preview away from the GUI thread."""
    context.cancellation.raise_if_cancelled()
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    image = reader.read()
    context.cancellation.raise_if_cancelled()
    if image.isNull():
        raise OSError(reader.errorString() or f"Unable to decode {path}")
    thumbnail = image.scaled(
        144,
        96,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    context.cancellation.raise_if_cancelled()
    return ViewerImageProduct(path=path, image=image, thumbnail=thumbnail)
