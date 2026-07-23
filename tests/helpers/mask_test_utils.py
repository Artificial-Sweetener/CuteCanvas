#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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

"""Helper utilities for exercising the asynchronous mask stroke pipeline."""

from __future__ import annotations

import time
from typing import Any

import numpy as np
from PySide6.QtCore import QCoreApplication
from qpane.raster.image_conversion import qimage_to_numpy_view_grayscale8


def drain_mask_jobs(
    qpane,
    *,
    executor=None,
    timeout: float = 2.0,
) -> tuple[dict[Any, tuple[Any, ...]], dict[Any, int]]:
    """Run queued mask worker + finalize jobs until pending state clears."""
    deadline = time.monotonic() + timeout
    exec_obj = executor or getattr(qpane, "executor", None)
    while time.monotonic() < deadline:
        progressed = False
        if exec_obj is not None:
            runner = getattr(exec_obj, "run_category", None)
            if callable(runner):
                for category in ("mask_stroke", "mask_stroke_main"):
                    pending_before = list(getattr(exec_obj, "_pending_order", ()))
                    runner(category)
                    pending_after = getattr(exec_obj, "_pending_order", ())
                    if pending_before != pending_after:
                        progressed = True
        app = QCoreApplication.instance()
        if app is not None:
            app.processEvents()
        service = getattr(qpane, "mask_service", None)
        snapshot = service.strokeDebugSnapshot() if service is not None else None
        still_pending = False
        if snapshot is not None:
            still_pending = any(snapshot.pending_jobs.values()) or bool(
                snapshot.preview_tokens
            )
        if not still_pending:
            break
        if not progressed:
            time.sleep(0.01)
    service = getattr(qpane, "mask_service", None)
    snapshot = service.strokeDebugSnapshot() if service is not None else None
    if snapshot is None:
        return {}, {}
    normalized_jobs = {
        mask_id: tuple(handles)
        for mask_id, handles in snapshot.pending_jobs.items()
        if handles
    }
    normalized_tokens = dict(snapshot.preview_tokens)
    return normalized_jobs, normalized_tokens


def snapshot_mask_layer(layer) -> np.ndarray:
    """Return a detached NumPy copy of the mask_image backing ``layer``."""
    view, _ = qimage_to_numpy_view_grayscale8(layer.mask_image)
    return np.array(view, copy=True)
