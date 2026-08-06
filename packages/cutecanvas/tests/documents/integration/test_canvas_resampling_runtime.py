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
"""Public execution contracts for whole-canvas resampling."""

from __future__ import annotations

import time

from cutecanvas import (
    CanvasDocument,
    CanvasDocumentRuntime,
    CanvasResamplingMode,
    CanvasResamplingStatus,
    CuteCanvas,
)
from cutecanvas_test_support.execution_backend import (
    InlineExecutionBackend,
)
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from qpane.sdk.execution import ExecutionRuntime


def test_public_resampling_runs_off_thread_and_publishes_terminal_result(qapp) -> None:
    """Expose one request identity and adopt its complete document edit."""
    image = QImage(3, 2, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("cyan"))
    document = CanvasDocument()
    composition_id = document.create_composition_from_image(image)
    execution = ExecutionRuntime(InlineExecutionBackend())
    runtime = CanvasDocumentRuntime(document, execution_runtime=execution)
    canvas = CuteCanvas(document_runtime=runtime, features=())
    results = []
    canvas.canvasResamplingCompleted.connect(results.append)
    try:
        canvas.openComposition(composition_id)
        request_id = canvas.requestCanvasResampling(
            composition_id,
            QSize(9, 8),
            mode=CanvasResamplingMode.FAST,
        )
        _drain_until(qapp, lambda: bool(results))

        result = results[0]
        assert result.request_id == request_id
        assert result.status is CanvasResamplingStatus.COMPLETED
        assert result.succeeded
        assert result.changed
        bounds = canvas.editor.compositions.current.state.scene_bounds
        assert bounds is not None
        assert bounds.size().toSize() == QSize(9, 8)
    finally:
        canvas.close()
        runtime.close()
        execution.shutdown(wait=False)
        document.close()


def test_same_size_resampling_completes_without_scheduling_or_copying(qapp) -> None:
    """Report a successful no-op when dimensions already match."""
    image = QImage(3, 2, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("cyan"))
    document = CanvasDocument()
    composition_id = document.create_composition_from_image(image)
    source = document.resources.compositions.layers.layers_for_composition(
        composition_id
    )[0].source
    execution = ExecutionRuntime(InlineExecutionBackend())
    runtime = CanvasDocumentRuntime(document, execution_runtime=execution)
    canvas = CuteCanvas(document_runtime=runtime, features=())
    results = []
    canvas.canvasResamplingCompleted.connect(results.append)
    try:
        request_id = canvas.requestCanvasResampling(composition_id, QSize(3, 2))
        _drain_until(qapp, lambda: bool(results))

        assert results[0].request_id == request_id
        assert results[0].status is CanvasResamplingStatus.COMPLETED
        assert results[0].succeeded
        assert not results[0].changed
        assert "already" in results[0].message
        after = document.resources.compositions.layers.layers_for_composition(
            composition_id
        )[0]
        assert after.source == source
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
