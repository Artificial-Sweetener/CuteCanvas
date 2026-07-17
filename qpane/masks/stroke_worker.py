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

"""QRunnable responsible for replaying mask stroke segments off the UI thread."""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QCoreApplication, QRunnable, QTimer

from ..concurrency.base_worker import BaseWorker
from .stroke_models import (
    MaskStrokeJobResult,
    MaskStrokeJobSpec,
    MaskStrokePayload,
    MaskStrokeSegmentPayload,
)
from .stroke_render import render_stroke_segments

logger = logging.getLogger(__name__)


class MaskStrokeWorker(QRunnable, BaseWorker):
    """Replay mask stroke segments off the UI thread and deliver the result."""

    def __init__(
        self,
        *,
        spec: MaskStrokeJobSpec,
        finalize: Callable[[MaskStrokeJobResult], None],
        logger_name: str | None = None,
    ) -> None:
        """Capture job spec and finalize callback for off-UI stroke replay."""
        QRunnable.__init__(self)
        worker_logger = (
            logger.getChild("MaskStrokeWorker")
            if logger_name is None
            else logging.getLogger(logger_name)
        )
        BaseWorker.__init__(self, logger=worker_logger)
        self._spec = spec
        self._payload = spec.payload
        self._finalize = finalize

    def run(self) -> None:
        """Replay the stroke payload and dispatch the finalize callback."""
        if self.is_cancelled:
            self.emit_finished(True)
            return
        try:
            result = self._build_result()
        except Exception as exc:  # pragma: no cover - defensive guard
            self.logger.exception(
                "Mask stroke worker failed for mask %s", self._spec.mask_id
            )
            self.emit_finished(False, error=exc)
            return
        if self.is_cancelled:
            self.emit_finished(True, payload=result)
            return
        self._dispatch_finalize(result)
        self.emit_finished(True, payload=result)

    def _build_result(self) -> MaskStrokeJobResult:
        """Render the stroke payload into a mask slice and build the result."""
        payload: MaskStrokePayload | None = self._payload
        spec = self._spec
        segments: tuple[MaskStrokeSegmentPayload, ...]
        if payload is None:
            segments = ()
        else:
            segments = payload.segments
        after_slice, preview_image = render_stroke_segments(
            before=spec.before,
            dirty_rect=spec.dirty_rect,
            segments=segments,
            preview_stride=1 if payload is None else payload.stride,
        )
        return MaskStrokeJobResult(
            mask_id=spec.mask_id,
            generation=spec.generation,
            dirty_rect=spec.dirty_rect,
            before=spec.before,
            after=after_slice,
            preview_image=preview_image,
            payload=payload,
            metadata=dict(spec.metadata),
        )

    def _dispatch_finalize(self, result: MaskStrokeJobResult) -> None:
        """Post the finalize callback to the main thread when possible."""
        finalize = self._finalize
        executor = getattr(self, "_executor", None)
        if executor is not None:
            dispatcher = getattr(executor, "dispatch_to_main_thread", None)
            if callable(dispatcher):
                try:
                    dispatcher(
                        lambda: finalize(result),
                        category="mask_stroke_main",
                    )
                    return
                except AttributeError:
                    pass
                except Exception:  # pragma: no cover - defensive guard
                    self.logger.exception(
                        "dispatch_to_main_thread failed; falling back to Qt scheduler",
                    )
        app = QCoreApplication.instance()
        if app is not None:
            try:
                QTimer.singleShot(0, app, lambda: finalize(result))
                return
            except Exception:  # pragma: no cover - defensive guard
                self.logger.exception(
                    "Failed to schedule mask stroke finalize via QTimer; running inline.",
                )
        try:
            finalize(result)
        except Exception:  # pragma: no cover - defensive guard
            self.logger.exception("Mask stroke finalize callback failed")
