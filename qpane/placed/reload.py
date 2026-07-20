#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Typed off-thread image decoding for linked placed assets."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImage, QImageReader

from ..concurrency import BaseWorker
from .model import FileFingerprint

logger = logging.getLogger(__name__)


class PlacedAssetDecodeWorker(QObject, QRunnable, BaseWorker):
    """Decode and fingerprint one linked image away from the GUI thread."""

    finished = Signal(object)
    error = Signal(object)

    def __init__(self, request_id: uuid.UUID, path: Path) -> None:
        """Capture immutable request identity and normalized source path."""
        QObject.__init__(self)
        QRunnable.__init__(self)
        BaseWorker.__init__(self, logger=logger)
        self.request_id = request_id
        self.path = Path(path)
        self.image: QImage | None = None
        self.fingerprint: FileFingerprint | None = None
        self.error_message: str | None = None
        self.missing = False

    def run(self) -> None:
        """Read metadata and pixels, publishing one terminal worker result."""
        try:
            if self.is_cancelled:
                self.emit_finished(False, payload=self)
                return
            try:
                stat = self.path.stat()
            except FileNotFoundError:
                self.missing = True
                self.error_message = f"linked image does not exist: {self.path}"
                self.emit_finished(False, payload=self)
                return
            fingerprint = FileFingerprint(stat.st_size, stat.st_mtime_ns)
            reader = QImageReader(str(self.path))
            reader.setAutoTransform(True)
            image = reader.read()
            if image.isNull():
                self.error_message = (
                    reader.errorString() or "linked image could not be decoded"
                )
            elif not self.is_cancelled:
                self.image = QImage(image)
                self.fingerprint = fingerprint
        except BaseException as exc:  # pragma: no cover - defensive worker boundary
            self.error_message = str(exc)
            logger.exception("Placed image decode failed")
        self.emit_finished(
            self.error_message is None
            and self.image is not None
            and not self.is_cancelled,
            payload=self,
        )
