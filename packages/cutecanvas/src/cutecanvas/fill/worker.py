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
"""Cancellable worker boundary for paint-bucket coverage generation."""

from __future__ import annotations

import logging
import uuid

from PySide6.QtCore import QObject, QRunnable, Signal
from qpane.sdk.concurrency import BaseWorker

from cutecanvas.coverage import CoverageSnapshot

from .flood import FillCancelledError, FloodFillEngine, FloodFillRequest

logger = logging.getLogger(__name__)


class FloodFillWorker(QObject, QRunnable, BaseWorker):
    """Evaluate one immutable flood-fill request away from the GUI thread."""

    finished = Signal(object)
    error = Signal(object)

    def __init__(self, request_id: uuid.UUID, request: FloodFillRequest) -> None:
        """Capture detached request values before submission."""
        QObject.__init__(self)
        QRunnable.__init__(self)
        BaseWorker.__init__(self, logger=logger)
        self.request_id = request_id
        self.request = request
        self.result: CoverageSnapshot | None = None
        self.error_message: str | None = None

    def run(self) -> None:
        """Evaluate cooperatively and publish exactly one terminal signal."""
        try:
            if not self.is_cancelled:
                self.result = FloodFillEngine().fill(
                    self.request,
                    cancelled=lambda: self.is_cancelled,
                )
        except FillCancelledError:
            pass
        except BaseException as exc:  # pragma: no cover - defensive worker boundary
            self.error_message = str(exc)
            logger.exception("Paint-bucket evaluation failed")
        self.emit_finished(
            self.error_message is None and not self.is_cancelled,
            payload=self,
        )
