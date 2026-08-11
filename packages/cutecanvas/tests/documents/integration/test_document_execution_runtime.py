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
"""Prove public document execution ownership across independent views."""

from __future__ import annotations

import threading
import time

from cutecanvas import CanvasDocument, CanvasDocumentRuntime, CuteCanvas
from cutecanvas_test_support.execution_backend import (
    ControllableExecutionBackend,
    InlineExecutionBackend,
)
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from qpane.sdk.execution import (
    ExecutionLeaseRelease,
    ExecutionRequest,
    ExecutionRequirements,
    ExecutionResource,
    ExecutionRuntime,
    ExecutionState,
)


def _drain_until(qapp, predicate, *, timeout: float = 2.0) -> None:
    """Pump owner delivery until ``predicate`` succeeds or time expires."""
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.001)
    assert predicate()


def test_independent_views_share_document_runtime_without_owning_it(qapp) -> None:
    """Closing one view leaves sibling and document work fully operational."""
    document = CanvasDocument()
    runtime = ExecutionRuntime(InlineExecutionBackend())
    document_runtime = CanvasDocumentRuntime(
        document,
        execution_runtime=runtime,
    )
    first = CuteCanvas(document_runtime=document_runtime, features=())
    second = CuteCanvas(document_runtime=document_runtime, features=())
    adopted: list[int] = []
    try:
        assert first.document() is document
        assert second.document() is document
        assert first.documentRuntime() is document_runtime
        assert second.documentRuntime() is document_runtime

        first.close()
        first.deleteLater()
        qapp.processEvents()

        handle = document_runtime.execution_scope.submit(
            ExecutionRequest(
                operation="test.document.after-view-close",
                work=lambda _context: 7,
            ),
            adopt=adopted.append,
        )
        _drain_until(qapp, lambda: handle.outcome is not None)
        assert handle.outcome is not None
        assert handle.outcome.state is ExecutionState.SUCCEEDED
        assert adopted == [7]
        assert not runtime.is_closed
    finally:
        second.close()
        second.deleteLater()
        document_runtime.close()
        runtime.shutdown(wait=False)
        document.close()


def test_host_runtime_without_affinity_gets_disjoint_native_fallback(qapp) -> None:
    """Native work uses a document-owned lane and bypasses the host backend."""
    document = CanvasDocument()
    host_backend = ControllableExecutionBackend()
    host_runtime = ExecutionRuntime(host_backend)
    document_runtime = CanvasDocumentRuntime(
        document,
        execution_runtime=host_runtime,
    )
    adopted: list[int] = []
    try:
        native_scope = document_runtime.native_execution_scope()
        handle = native_scope.submit(
            ExecutionRequest(
                operation="test.document.native-fallback",
                requirements=ExecutionRequirements(
                    resource=ExecutionResource.THREAD_AFFINE_NATIVE,
                    affinity_key="test-native",
                    exclusive_key="test-native",
                    lease_release=ExecutionLeaseRelease.ADOPTION_FINISHED,
                ),
                work=lambda _context: threading.get_ident(),
            ),
            adopt=adopted.append,
        )
        _drain_until(qapp, lambda: handle.outcome is not None)
        assert handle.outcome is not None
        assert handle.outcome.state is ExecutionState.SUCCEEDED
        assert adopted
        assert host_backend.submitted == []
    finally:
        document_runtime.close()
        assert not host_runtime.is_closed
        host_runtime.shutdown(wait=False)
        document.close()


def test_two_views_share_one_latest_document_mutation_owner(qapp) -> None:
    """A newer layer conversion cancels the older request across view instances."""
    document = CanvasDocument()
    image = QImage(64, 48, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor("cyan"))
    composition_id = document.create_composition_from_image(image)
    layer_id = document.resources.compositions.layers.layers_for_composition(
        composition_id
    )[0].layer_id
    backend = ControllableExecutionBackend()
    runtime = ExecutionRuntime(backend)
    document_runtime = CanvasDocumentRuntime(
        document,
        execution_runtime=runtime,
    )
    first = CuteCanvas(document_runtime=document_runtime, features=())
    second = CuteCanvas(document_runtime=document_runtime, features=())
    first_results: list[tuple] = []
    second_results: list[tuple] = []
    first.placedAssetRequestCompleted.connect(
        lambda *values: first_results.append(tuple(values))
    )
    second.placedAssetRequestCompleted.connect(
        lambda *values: second_results.append(tuple(values))
    )
    try:
        first.openComposition(composition_id)
        second.openComposition(composition_id)
        first_request = first.rasterizeLayer(
            composition_id,
            layer_id,
            QSize(48, 36),
        )
        second_request = second.rasterizeLayer(
            composition_id,
            layer_id,
            QSize(32, 24),
        )
        assert first_request is not None
        assert second_request is not None
        assert first_request != second_request
        assert any(
            job.operation == "editor.placed.rasterize" for job in backend.cancelled
        )
        raster_jobs = tuple(
            job
            for job in backend.pending_jobs()
            if job.operation == "editor.placed.rasterize"
        )
        assert len(raster_jobs) == 1
        backend.run_job(raster_jobs[0])
        _drain_until(
            qapp,
            lambda: any(result[0] == second_request for result in second_results),
        )
        assert any(
            result[0] == first_request and result[3] is False
            for result in first_results
        )
        assert any(
            result[0] == second_request and result[3] is True
            for result in second_results
        )
    finally:
        first.close()
        second.close()
        first.deleteLater()
        second.deleteLater()
        document_runtime.close()
        runtime.shutdown(wait=False)
        document.close()
