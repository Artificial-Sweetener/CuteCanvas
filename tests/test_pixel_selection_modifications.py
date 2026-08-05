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
"""Mounted public pixel-selection modification and stale-work contracts."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from threading import Event

import numpy as np
import pytest
from cutecanvas import (
    CuteCanvas,
    LayerEdgeOperation,
    PixelSelectionModificationResult,
)
from cutecanvas.coverage import CoverageEdgeModificationRequest, CoverageSnapshot
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication


def test_public_selection_modifications_are_async_undoable_and_layer_safe(
    qapp: QApplication,
) -> None:
    """Every operation must change only selection coverage through one history edit."""
    canvas = CuteCanvas()
    try:
        composition_id = canvas.createCompositionFromImage(_color_image(32, 32))
        canvas.openComposition(composition_id)
        layer_id = canvas.addEditableRasterLayer(_color_image(32, 32), label="Pixels")
        assert layer_id is not None
        scene = canvas.currentScene()
        assert scene is not None
        before_layer = canvas.editableRasterLayerImage(scene.scene_id, layer_id)
        assert before_layer is not None
        assert canvas.setPixelSelection(_coverage(4, 5), QRect(10, 11, 4, 5))
        initial = canvas.pixelSelectionState()
        assert initial is not None and initial.coverage is not None

        expanded = _await_request(
            qapp, canvas, lambda: canvas.editor.selection.expand(3)
        )
        assert expanded.operation is LayerEdgeOperation.EXPAND
        assert expanded.succeeded
        expanded_state = canvas.pixelSelectionState()
        assert expanded_state is not None
        assert expanded_state.bounds == QRect(7, 8, 10, 11)
        assert canvas.editableRasterLayerImage(scene.scene_id, layer_id) == before_layer

        assert canvas.undoSceneEdit()
        restored = canvas.pixelSelectionState()
        assert restored is not None
        assert restored.bounds == initial.bounds
        assert restored.coverage == initial.coverage
        assert canvas.redoSceneEdit()
        assert canvas.pixelSelectionState().bounds == QRect(7, 8, 10, 11)

        contracted = _await_request(
            qapp,
            canvas,
            lambda: canvas.contractPixelSelection(2),
        )
        assert contracted.succeeded
        assert canvas.pixelSelectionState().bounds == QRect(9, 10, 6, 7)

        feathered = _await_request(
            qapp,
            canvas,
            lambda: canvas.featherPixelSelection(2.5),
        )
        assert feathered.succeeded
        feathered_state = canvas.pixelSelectionState()
        assert feathered_state is not None and feathered_state.coverage is not None
        pixels = _qimage_pixels(feathered_state.coverage)
        assert np.any((pixels > 0) & (pixels < 255))
        assert canvas.editableRasterLayerImage(scene.scene_id, layer_id) == before_layer
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_selection_preview_replaces_from_original_and_settles_once(
    qapp: QApplication,
) -> None:
    """Every preview value must derive from the captured base and add no history."""

    canvas = CuteCanvas()
    try:
        composition_id = canvas.createCompositionFromImage(_color_image(64, 64))
        canvas.openComposition(composition_id)
        assert canvas.setPixelSelection(_coverage(8, 8), QRect(20, 20, 8, 8))
        original = canvas.pixelSelectionState()
        assert original is not None

        session_id = canvas.beginPixelSelectionModificationPreview()
        assert session_id is not None
        assert (
            canvas.updatePixelSelectionModificationPreview(
                session_id,
                LayerEdgeOperation.EXPAND,
                4,
            )
            is not None
        )
        _await_selection_bounds(qapp, canvas, QRect(16, 16, 16, 16))
        assert (
            canvas.updatePixelSelectionModificationPreview(
                session_id,
                LayerEdgeOperation.EXPAND,
                5,
            )
            is not None
        )
        _await_selection_bounds(qapp, canvas, QRect(15, 15, 18, 18))
        assert (
            canvas.updatePixelSelectionModificationPreview(
                session_id,
                LayerEdgeOperation.CONTRACT,
                2,
            )
            is not None
        )
        _await_selection_bounds(qapp, canvas, QRect(22, 22, 4, 4))

        assert canvas.cancelPixelSelectionModificationPreview(session_id)
        _await_selection_bounds(qapp, canvas, original.bounds)
        restored = canvas.pixelSelectionState()
        assert restored is not None
        assert restored.coverage == original.coverage

        applied_session = canvas.beginPixelSelectionModificationPreview()
        assert applied_session is not None
        completed = QSignalSpy(canvas.pixelSelectionModificationCompleted)
        request_id = canvas.updatePixelSelectionModificationPreview(
            applied_session,
            LayerEdgeOperation.EXPAND,
            5,
        )
        assert request_id is not None
        assert canvas.settlePixelSelectionModificationPreview(applied_session)
        assert completed.wait(3000)
        result = completed.at(0)[0]
        assert isinstance(result, PixelSelectionModificationResult)
        assert result.request_id == request_id
        assert result.succeeded
        assert canvas.pixelSelectionState().bounds == QRect(15, 15, 18, 18)
        assert canvas.undoSceneEdit()
        assert canvas.pixelSelectionState().bounds == original.bounds
        assert canvas.pixelSelectionState().coverage == original.coverage
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_selection_modification_rejects_stale_worker_result(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A selection edit during filtering must prevent late result publication."""
    from cutecanvas.runtime import coverage_modification_preview

    canvas = CuteCanvas()
    started = Event()
    release = Event()
    original = coverage_modification_preview.build_coverage_edge_modification

    def delayed(
        request: CoverageEdgeModificationRequest,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> CoverageSnapshot | None:
        """Hold one real product until the test changes authoritative selection."""
        started.set()
        release.wait(3.0)
        return original(request, cancelled=cancelled)

    monkeypatch.setattr(
        coverage_modification_preview,
        "build_coverage_edge_modification",
        delayed,
    )
    try:
        composition_id = canvas.createCompositionFromImage(_color_image(64, 64))
        canvas.openComposition(composition_id)
        assert canvas.setPixelSelection(_coverage(8, 8), QRect(8, 8, 8, 8))
        completed = QSignalSpy(canvas.pixelSelectionModificationCompleted)
        request_id = canvas.expandPixelSelection(10)
        assert request_id is not None
        assert started.wait(2.0)
        assert canvas.setPixelSelection(_coverage(3, 3), QRect(40, 41, 3, 3))
        expected = canvas.pixelSelectionState()
        release.set()
        assert completed.wait(3000)
        result = completed.at(0)[0]
        assert isinstance(result, PixelSelectionModificationResult)
        assert result.request_id == request_id
        assert not result.succeeded
        assert result.message == "pixel selection changed during filtering"
        actual = canvas.pixelSelectionState()
        assert actual is not None and expected is not None
        assert actual.revision == expected.revision
        assert actual.bounds == expected.bounds
        assert actual.coverage == expected.coverage
    finally:
        release.set()
        canvas.deleteLater()
        qapp.processEvents()


def test_newer_selection_modification_replaces_unresolved_work(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A newer request must cancel and terminally report the superseded request."""
    from cutecanvas.runtime import coverage_modification_preview

    first_started = Event()
    release_first = Event()
    original = coverage_modification_preview.build_coverage_edge_modification
    invocation = 0

    def delay_first(
        request: CoverageEdgeModificationRequest,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> CoverageSnapshot | None:
        """Hold only the superseded product while allowing its replacement through."""
        nonlocal invocation
        invocation += 1
        if invocation == 1:
            first_started.set()
            release_first.wait(3.0)
        return original(request, cancelled=cancelled)

    monkeypatch.setattr(
        coverage_modification_preview,
        "build_coverage_edge_modification",
        delay_first,
    )
    canvas = CuteCanvas()
    try:
        composition_id = canvas.createCompositionFromImage(_color_image(64, 64))
        canvas.openComposition(composition_id)
        assert canvas.setPixelSelection(_coverage(8, 8), QRect(20, 20, 8, 8))
        completed = QSignalSpy(canvas.pixelSelectionModificationCompleted)

        replaced_id = canvas.expandPixelSelection(9)
        assert replaced_id is not None
        assert first_started.wait(2.0)
        accepted_id = canvas.contractPixelSelection(2)
        assert accepted_id is not None
        while completed.count() < 2:
            assert completed.wait(3000)

        results = {
            result.request_id: result
            for index in range(completed.count())
            if (emission := completed.at(index))
            if isinstance((result := emission[0]), PixelSelectionModificationResult)
        }
        assert results[replaced_id].message == "replaced by a newer document request"
        assert not results[replaced_id].succeeded
        assert results[accepted_id].succeeded
        state = canvas.pixelSelectionState()
        assert state is not None
        assert state.bounds == QRect(22, 22, 4, 4)

        release_first.set()
        qapp.processEvents()
        assert completed.count() == 2
    finally:
        release_first.set()
        canvas.deleteLater()
        qapp.processEvents()


def test_selection_modification_validates_public_radii(qapp: QApplication) -> None:
    """Public commands must reject ambiguous radii before submitting work."""
    canvas = CuteCanvas()
    try:
        composition_id = canvas.createCompositionFromImage(_color_image(8, 8))
        canvas.openComposition(composition_id)
        assert canvas.setPixelSelection(_coverage(1, 1), QRect(2, 2, 1, 1))
        for invalid in (0, -1):
            try:
                canvas.expandPixelSelection(invalid)
            except ValueError:
                pass
            else:  # pragma: no cover - assertion reports the missing public guard
                raise AssertionError("invalid expansion radius was accepted")
        try:
            canvas.contractPixelSelection(1.5)  # type: ignore[arg-type]
        except TypeError:
            pass
        else:  # pragma: no cover - assertion reports the missing public guard
            raise AssertionError("fractional contraction radius was accepted")
        try:
            canvas.featherPixelSelection(float("nan"))
        except ValueError:
            pass
        else:  # pragma: no cover - assertion reports the missing public guard
            raise AssertionError("non-finite feather radius was accepted")
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def _await_request(
    qapp: QApplication,
    canvas: CuteCanvas,
    submit: Callable[[], uuid.UUID | None],
) -> PixelSelectionModificationResult:
    """Wait for the exact terminal public result of one accepted request."""
    completed = QSignalSpy(canvas.pixelSelectionModificationCompleted)
    request_id = submit()
    assert request_id is not None
    assert completed.wait(3000)
    qapp.processEvents()
    result = completed.at(0)[0]
    assert isinstance(result, PixelSelectionModificationResult)
    assert result.request_id == request_id
    return result


def _await_selection_bounds(
    qapp: QApplication,
    canvas: CuteCanvas,
    expected: QRect | None,
) -> None:
    """Wait for one exact public preview projection with a bounded signal wait."""

    changed = QSignalSpy(canvas.pixelSelectionChanged)
    while canvas.pixelSelectionState().bounds != expected:
        assert changed.wait(3000)
        qapp.processEvents()


def _color_image(width: int, height: int) -> QImage:
    """Return one detached opaque color raster."""
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    return image


def _coverage(width: int, height: int) -> QImage:
    """Return one full grayscale selection rectangle."""
    image = QImage(width, height, QImage.Format_Grayscale8)
    image.fill(255)
    return image


def _qimage_pixels(image: QImage) -> np.ndarray:
    """Return detached grayscale pixels without relying on private adapters."""
    converted = image.convertToFormat(QImage.Format_Grayscale8)
    return (
        np.frombuffer(converted.bits(), dtype=np.uint8)
        .reshape(
            converted.height(),
            converted.bytesPerLine(),
        )[:, : converted.width()]
        .copy()
    )
