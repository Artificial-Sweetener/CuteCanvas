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
"""Cancellation and freshness abuse contracts for canvas resampling."""

from __future__ import annotations

import time

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from cutecanvas import (
    CanvasDocument,
    CanvasDocumentRuntime,
    CanvasResamplingStatus,
    CuteCanvas,
)
from cutecanvas_test_support.execution_backend import ControllableExecutionBackend
from qpane.sdk.execution import ExecutionRuntime


def test_newer_resampling_cancels_older_work_across_document_views(qapp) -> None:
    """Publish cancellation once and adopt only the latest composition request."""
    document = CanvasDocument()
    composition_id = document.create_composition_from_image(
        _image(QSize(4, 3), QColor("magenta"))
    )
    backend = ControllableExecutionBackend()
    execution = ExecutionRuntime(backend)
    runtime = CanvasDocumentRuntime(document, execution_runtime=execution)
    first = CuteCanvas(document_runtime=runtime, features=())
    second = CuteCanvas(document_runtime=runtime, features=())
    results = []
    first.canvasResamplingCompleted.connect(results.append)
    try:
        first_id = first.requestCanvasResampling(composition_id, QSize(8, 6))
        second_id = second.requestCanvasResampling(composition_id, QSize(12, 9))
        assert first_id != second_id
        assert any(
            result.request_id == first_id
            and result.status is CanvasResamplingStatus.CANCELLED
            for result in results
        )
        jobs = tuple(
            job
            for job in backend.pending_jobs()
            if job.operation == "editor.canvas.resample"
        )
        assert len(jobs) == 1
        backend.run_job(jobs[0])
        _drain_until(
            qapp,
            lambda: any(result.request_id == second_id for result in results),
        )
        second_result = next(
            result for result in results if result.request_id == second_id
        )
        assert second_result.status is CanvasResamplingStatus.COMPLETED
    finally:
        first.close()
        second.close()
        runtime.close()
        execution.shutdown(wait=False)
        document.close()


def test_resampling_reports_stale_after_intervening_document_edit(qapp) -> None:
    """Discard completed worker products when captured geometry is no longer live."""
    document = CanvasDocument()
    composition_id = document.create_composition_from_image(
        _image(QSize(4, 3), QColor("cyan"))
    )
    backend = ControllableExecutionBackend()
    execution = ExecutionRuntime(backend)
    runtime = CanvasDocumentRuntime(document, execution_runtime=execution)
    canvas = CuteCanvas(document_runtime=runtime, features=())
    results = []
    canvas.canvasResamplingCompleted.connect(results.append)
    try:
        request_id = canvas.requestCanvasResampling(composition_id, QSize(8, 6))
        assert document.resize_canvas_bounds(composition_id, QSize(5, 4))
        job = next(
            job
            for job in backend.pending_jobs()
            if job.operation == "editor.canvas.resample"
        )
        backend.run_job(job)
        _drain_until(qapp, lambda: bool(results))
        assert results[0].request_id == request_id
        assert results[0].status is CanvasResamplingStatus.STALE
        bounds = document.snapshot().compositions[composition_id].scene_bounds
        assert bounds is not None
        assert bounds.size().toSize() == QSize(5, 4)
    finally:
        canvas.close()
        runtime.close()
        execution.shutdown(wait=False)
        document.close()


def _drain_until(qapp, predicate, *, timeout: float = 2.0) -> None:
    """Pump Qt delivery until the public result is observed."""
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.001)
    assert predicate()


def _image(size: QSize, color: QColor) -> QImage:
    """Return one detached premultiplied image fixture."""
    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(color)
    return image
