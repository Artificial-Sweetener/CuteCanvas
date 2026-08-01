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
"""Characterize mounted QPane and CuteCanvas projection during resize."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from cutecanvas import CanvasInspectionGroup, CuteCanvas
from cutecanvas.document import CanvasDocument, CanvasViewSession
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
from qpane.sdk.rendering import ViewportZoomMode

from qpane import QPane
from tests.harness.viewport_resize_probe import (
    MountedViewportResizeProbe,
    ViewportResizeObservation,
)

_HIGH_DPI_RESULT_PREFIX = "VIEWPORT_RESIZE_DPI_RESULT="


@pytest.fixture()
def source_image() -> QImage:
    """Create non-square content whose scale drift is easy to distinguish."""
    image = QImage(1600, 1200, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(32, 64, 96, 255))
    return image


@pytest.fixture()
def mounted_qpane(
    qapp: QApplication,
    source_image: QImage,
) -> Iterator[QPane]:
    """Mount a production QPane under Qt's offscreen platform."""
    pane = QPane()
    pane.resize(800, 600)
    pane.setImage(source_image)
    pane.show()
    qapp.processEvents()
    try:
        yield pane
    finally:
        pane.close()
        pane.deleteLater()
        qapp.processEvents()


@pytest.fixture()
def mounted_cutecanvas(
    qapp: QApplication,
    source_image: QImage,
) -> Iterator[CuteCanvas]:
    """Mount a production CuteCanvas under Qt's offscreen platform."""
    canvas = CuteCanvas(features=())
    canvas.resize(800, 600)
    canvas.createCompositionFromImage(source_image, title="Resize probe")
    canvas.show()
    qapp.processEvents()
    try:
        yield canvas
    finally:
        canvas.close()
        canvas.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize(
    "surface_fixture",
    ("mounted_qpane", "mounted_cutecanvas"),
)
def test_custom_projection_is_viewport_size_independent(
    request: pytest.FixtureRequest,
    qapp: QApplication,
    surface_fixture: str,
) -> None:
    """Keep manual scale and scene center fixed through shrink and growth."""
    surface = request.getfixturevalue(surface_fixture)
    if isinstance(surface, CuteCanvas):
        view = surface.view()
    else:
        view = surface._rendering.presenter
    viewport = view.viewport
    viewport.zoom_mode = ViewportZoomMode.CUSTOM
    viewport.setZoomAndPan(1.375, QPointF(143.0, -97.0))
    qapp.processEvents()
    probe = MountedViewportResizeProbe(qapp, surface, view, viewport)

    observations = (
        probe.capture("initial"),
        probe.resize_and_capture("shrink", QSize(503, 311)),
        probe.resize_and_capture("odd", QSize(817, 509)),
        probe.resize_and_capture("tiny", QSize(17, 19)),
        probe.resize_and_capture("repeated-tiny", QSize(17, 19)),
        probe.resize_and_capture("grow", QSize(1201, 907)),
        probe.resize_and_capture("restore", QSize(800, 600)),
    )

    _assert_invariant_projection(observations)


@pytest.mark.parametrize(
    "surface_fixture",
    ("mounted_qpane", "mounted_cutecanvas"),
)
def test_fit_projection_remains_viewport_responsive(
    request: pytest.FixtureRequest,
    qapp: QApplication,
    surface_fixture: str,
) -> None:
    """Continue deriving FIT scale from each delivered viewport size."""
    surface = request.getfixturevalue(surface_fixture)
    if isinstance(surface, CuteCanvas):
        view = surface.view()
    else:
        view = surface._rendering.presenter
    viewport = view.viewport
    viewport.setZoomFit()
    qapp.processEvents()
    probe = MountedViewportResizeProbe(qapp, surface, view, viewport)

    initial = probe.capture("initial")
    shrink = probe.resize_and_capture("shrink", QSize(503, 311))
    grow = probe.resize_and_capture("grow", QSize(1201, 907))

    assert initial.zoom_mode == ViewportZoomMode.FIT.value
    assert shrink.zoom_mode == ViewportZoomMode.FIT.value
    assert grow.zoom_mode == ViewportZoomMode.FIT.value
    assert shrink.zoom < initial.zoom < grow.zoom
    assert shrink.scene_center == initial.scene_center == grow.scene_center


def test_custom_resize_is_retained_when_linked_target_changes(
    qapp: QApplication,
    source_image: QImage,
) -> None:
    """Keep viewport-independent geometry authoritative across target activation."""
    canvas = CuteCanvas(features=())
    canvas.resize(800, 600)
    first_id = canvas.createCompositionFromImage(source_image, title="First")
    second_id = canvas.createCompositionFromImage(source_image, title="Second")
    canvas.viewSession().setInspectionGroups(
        (CanvasInspectionGroup(uuid.uuid4(), (first_id, second_id)),)
    )
    canvas.openComposition(first_id)
    canvas.show()
    qapp.processEvents()
    try:
        view = canvas.view()
        viewport = view.viewport
        viewport.zoom_mode = ViewportZoomMode.CUSTOM
        viewport.setZoomAndPan(1.375, QPointF(143.0, -97.0))
        qapp.processEvents()
        probe = MountedViewportResizeProbe(qapp, canvas, view, viewport)
        expected = probe.capture("initial")

        resized = probe.resize_and_capture("shrink", QSize(503, 311))
        canvas.openComposition(second_id)
        qapp.processEvents()
        second = probe.capture("second")
        canvas.openComposition(first_id)
        qapp.processEvents()
        restored = probe.capture("first-restored")

        _assert_invariant_projection((expected, resized, second, restored))
    finally:
        canvas.close()
        canvas.deleteLater()
        qapp.processEvents()


def test_sequential_linked_surface_resizes_do_not_feed_back(
    qapp: QApplication,
    source_image: QImage,
) -> None:
    """Keep each live transform fixed while Qt resizes linked surfaces in order."""
    document = CanvasDocument()
    inspection_session = CanvasViewSession()
    second_session = CanvasViewSession(inspection=inspection_session.inspection)
    first = CuteCanvas(
        document=document,
        session=inspection_session,
        features=(),
    )
    second = CuteCanvas(
        document=document,
        session=second_session,
        features=(),
    )
    first.resize(800, 600)
    second.resize(800, 600)
    first_id = first.createCompositionFromImage(source_image, title="First")
    second_id = first.createCompositionFromImage(source_image, title="Second")
    group = CanvasInspectionGroup(uuid.uuid4(), (first_id, second_id))
    inspection_session.setInspectionGroups((group,))
    first.openComposition(first_id)
    second.openComposition(second_id)
    first.show()
    second.show()
    qapp.processEvents()
    try:
        first_view = first.view()
        second_view = second.view()
        first_view.viewport.zoom_mode = ViewportZoomMode.CUSTOM
        first_view.viewport.setZoomAndPan(1.375, QPointF(143.0, -97.0))
        qapp.processEvents()
        first_probe = MountedViewportResizeProbe(
            qapp,
            first,
            first_view,
            first_view.viewport,
        )
        second_probe = MountedViewportResizeProbe(
            qapp,
            second,
            second_view,
            second_view.viewport,
        )
        first_before = first_probe.capture("first-before")
        second_before = second_probe.capture("second-before")

        first_after = first_probe.resize_and_capture("first-shrink", QSize(503, 311))
        second_unchanged = second_probe.capture("second-after-first")
        second_after = second_probe.resize_and_capture(
            "second-grow",
            QSize(1201, 907),
        )
        first_unchanged = first_probe.capture("first-after-second")

        _assert_invariant_projection((first_before, first_after, first_unchanged))
        _assert_invariant_projection((second_before, second_unchanged, second_after))
    finally:
        first.close()
        second.close()
        document.close()
        first.deleteLater()
        second.deleteLater()
        qapp.processEvents()


def test_custom_projection_is_stable_at_fractional_device_scale() -> None:
    """Prove the mounted resize contract in an isolated 175%-DPR process."""
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update(
        {
            "QT_QPA_PLATFORM": "offscreen",
            "QT_SCALE_FACTOR": "1.75",
            "PYTHONPATH": os.pathsep.join(
                (
                    str(root / "packages" / "cutecanvas" / "src"),
                    str(root / "packages" / "qpane" / "src"),
                    str(root),
                )
            ),
        }
    )

    completed = subprocess.run(
        (sys.executable, "-m", "tests.harness.high_dpi_viewport_resize"),
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    result_line = next(
        (
            line
            for line in completed.stdout.splitlines()
            if line.startswith(_HIGH_DPI_RESULT_PREFIX)
        ),
        None,
    )
    assert result_line is not None, completed.stdout
    result = json.loads(result_line.removeprefix(_HIGH_DPI_RESULT_PREFIX))
    assert result["device_pixel_ratio"] == pytest.approx(1.75)
    assert result["zooms"] == pytest.approx([1.375] * 5)
    expected_scale = 1.375 / 1.75
    assert [
        scale for pair in result["scene_basis_scales"] for scale in pair
    ] == pytest.approx([expected_scale] * 10)


def _assert_invariant_projection(
    observations: tuple[ViewportResizeObservation, ...],
) -> None:
    """Assert every observation preserves manual semantic and rendered geometry."""
    expected = observations[0]
    for observation in observations[1:]:
        assert observation.zoom_mode == ViewportZoomMode.CUSTOM.value, observations
        assert observation.zoom == pytest.approx(expected.zoom), observations
        assert observation.pan.x() == pytest.approx(expected.pan.x()), observations
        assert observation.pan.y() == pytest.approx(expected.pan.y()), observations
        assert observation.scene_center.x() == pytest.approx(
            expected.scene_center.x()
        ), observations
        assert observation.scene_center.y() == pytest.approx(
            expected.scene_center.y()
        ), observations
        assert observation.scene_basis_scale.x() == pytest.approx(
            expected.scene_basis_scale.x()
        ), observations
        assert observation.scene_basis_scale.y() == pytest.approx(
            expected.scene_basis_scale.y()
        ), observations
