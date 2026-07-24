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

"""Teach background image loading without blocking the editor window."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QImage, QImageReader

logger = logging.getLogger(__name__)


class _ImageLoaderSignals(QObject):
    """Carry one decoder runnable's progress back to its GUI-thread owner."""

    image_loaded = Signal(Path, QImage)
    finished = Signal(int)


class _ImageLoaderWorker(QRunnable):
    """Decode one image batch without owning any GUI-thread callbacks."""

    def __init__(
        self,
        paths: Iterable[Path],
        signals: _ImageLoaderSignals,
    ) -> None:
        """Store paths and the coordinator-owned signal bridge.

        Args:
            paths: Image paths decoded sequentially on the pool thread.
            signals: GUI-owned signal bridge retained by the coordinator.
        """
        super().__init__()
        self._paths = tuple(paths)
        self._signals = signals

    @Slot()
    def run(self) -> None:
        """Execute the loading loop on a background thread."""
        count = 0
        for path in self._paths:
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            image = reader.read()
            if not image.isNull():
                if not self._emit_image(path, image):
                    return
                count += 1
        self._emit_finished(count)

    def _emit_image(self, path: Path, image: QImage) -> bool:
        """Emit one decoded image unless the GUI owner has already closed."""
        try:
            self._signals.image_loaded.emit(path, image)
        except RuntimeError:
            logger.debug("Image loader owner closed during decode", exc_info=True)
            return False
        return True

    def _emit_finished(self, count: int) -> None:
        """Emit terminal progress unless the GUI owner has already closed."""
        try:
            self._signals.finished.emit(count)
        except RuntimeError:
            logger.debug("Image loader owner closed before completion", exc_info=True)


@dataclass(slots=True)
class _ActiveImageLoad:
    """Retain one runnable and its GUI callbacks until terminal delivery."""

    request_id: uuid.UUID
    worker: _ImageLoaderWorker
    signals: _ImageLoaderSignals
    image_loaded: Callable[[Path, QImage], None]
    finished: Callable[[int], None]


class ImageLoadCoordinator(QObject):
    """Own decoder runnable lifetimes and deliver callbacks on the GUI thread."""

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        thread_pool: QThreadPool | None = None,
    ) -> None:
        """Bind a Qt owner and optional thread pool for background decoding."""
        super().__init__(parent)
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._active: dict[_ImageLoaderSignals, _ActiveImageLoad] = {}

    def submit(
        self,
        paths: Iterable[Path],
        *,
        image_loaded: Callable[[Path, QImage], None],
        finished: Callable[[int], None],
    ) -> uuid.UUID:
        """Decode ``paths`` and invoke both callbacks on this object's thread."""
        path_batch = tuple(paths)
        if not path_batch:
            raise ValueError("paths must contain at least one image")
        request_id = uuid.uuid4()
        signals = _ImageLoaderSignals(self)
        worker = _ImageLoaderWorker(path_batch, signals)
        active = _ActiveImageLoad(
            request_id=request_id,
            worker=worker,
            signals=signals,
            image_loaded=image_loaded,
            finished=finished,
        )
        self._active[signals] = active
        signals.image_loaded.connect(
            self._deliver_image,
            Qt.ConnectionType.QueuedConnection,
        )
        signals.finished.connect(
            self._deliver_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._thread_pool.start(worker)
        return request_id

    @property
    def active_count(self) -> int:
        """Return the number of decoder batches awaiting terminal delivery."""
        return len(self._active)

    @Slot(Path, QImage)
    def _deliver_image(self, path: Path, image: QImage) -> None:
        """Forward one decoded image from the coordinator's Qt thread."""
        active = self._active.get(self.sender())
        if active is None:
            return
        try:
            active.image_loaded(path, image)
        except Exception:
            logger.exception(
                "Image load callback failed (request=%s, path=%s)",
                active.request_id,
                path,
            )

    @Slot(int)
    def _deliver_finished(self, count: int) -> None:
        """Forward completion and release the runnable on the GUI thread."""
        signals = self.sender()
        active = self._active.pop(signals, None)
        if active is None:
            return
        try:
            active.finished(count)
        except Exception:
            logger.exception(
                "Image load completion callback failed (request=%s)",
                active.request_id,
            )
        finally:
            active.signals.deleteLater()
