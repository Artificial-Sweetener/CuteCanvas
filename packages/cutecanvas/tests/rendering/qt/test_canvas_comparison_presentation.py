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

"""Characterize CuteCanvas comparison runtime and physical-scale projection."""

from __future__ import annotations

from math import hypot

import pytest
from cutecanvas import CanvasComparisonOverlayState
from cutecanvas.document import CanvasDocument
from cutecanvas.presentation import CanvasWorkspace
from cutecanvas_test_support.execution_backend import ControllableExecutionBackend
from PySide6.QtCore import QElapsedTimer, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from qpane.sdk.execution import ExecutionRuntime
from qpane.sdk.types import ComparisonOrientation


def test_native_comparison_submits_render_work_to_document_runtime(qapp) -> None:
    """Route comparison render products through the host-owned physical runtime."""

    document = CanvasDocument()
    primary_id = document.create_composition_from_image(
        _image(QSize(2048, 1536), QColor("red"))
    )
    secondary_id = document.create_composition_from_image(
        _image(QSize(3072, 1728), QColor("blue"))
    )
    backend = ControllableExecutionBackend()
    runtime = ExecutionRuntime(backend)
    workspace = CanvasWorkspace(
        document=document,
        features=(),
        execution_runtime=runtime,
    )
    try:
        workspace.resize(960, 640)
        workspace.setComparisonPresentation(primary_id, secondary_id)
        workspace.show()
        qapp.processEvents()
        pane = workspace.currentCanvas()
        assert pane is not None
        pane.grab()
        qapp.processEvents()

        assert any(job.operation.startswith("render.") for job in backend.submitted)
    finally:
        workspace.close()
        qapp.processEvents()
        runtime.shutdown(wait=False)
        document.close()


def test_comparison_overlay_scales_match_each_rendered_layer(qapp) -> None:
    """Report each source's actual source-to-physical transform."""

    document = CanvasDocument()
    primary_id = document.create_composition_from_image(
        _image(QSize(640, 480), QColor("red"))
    )
    secondary_id = document.create_composition_from_image(
        _image(QSize(1600, 900), QColor("blue"))
    )
    workspace = CanvasWorkspace(document=document, features=())
    observed: list[CanvasComparisonOverlayState] = []
    try:
        workspace.registerComparisonOverlay(
            "scale-probe",
            lambda _painter, state: observed.append(state),
        )
        workspace.resize(1000, 700)
        workspace.setComparisonPresentation(primary_id, secondary_id)
        workspace.show()
        qapp.processEvents()
        pane = workspace.currentCanvas()
        assert pane is not None
        pane.grab()

        assert observed
        state = observed[-1]
        plan = pane.calculateRenderPlan()
        assert plan is not None
        assert len(plan.render_items) == 2
        device_pixel_ratio = max(1.0, pane.devicePixelRatioF())
        expected = tuple(
            (
                hypot(item.transform.m11(), item.transform.m12()) * device_pixel_ratio,
                hypot(item.transform.m21(), item.transform.m22()) * device_pixel_ratio,
            )
            for item in plan.render_items
        )
        assert state.primary_scale.horizontal == pytest.approx(expected[0][0])
        assert state.primary_scale.vertical == pytest.approx(expected[0][1])
        assert state.secondary_scale.horizontal == pytest.approx(expected[1][0])
        assert state.secondary_scale.vertical == pytest.approx(expected[1][1])
        assert state.secondary_scale.horizontal != pytest.approx(
            state.primary_scale.horizontal
        )
        assert state.secondary_scale.vertical != pytest.approx(
            state.primary_scale.vertical
        )
    finally:
        workspace.close()
        document.close()
        qapp.processEvents()


def test_workspace_tiled_comparison_applies_full_source_switch(qapp) -> None:
    """Replace a tiled all-primary reveal with an all-secondary reveal."""

    document = CanvasDocument()
    primary_id = document.create_composition_from_image(
        _image(QSize(2048, 1536), QColor("red"))
    )
    secondary_id = document.create_composition_from_image(
        _image(QSize(4096, 3072), QColor("blue"))
    )
    workspace = CanvasWorkspace(document=document, features=())
    workspace.resize(960, 640)
    workspace.show()
    try:
        workspace.setComparisonPresentation(
            primary_id,
            secondary_id,
            split_position=1.0,
        )
        qapp.processEvents()
        pane = workspace.currentCanvas()
        assert pane is not None
        pane.viewport.setZoomAndPan(1.75, QPointF(117.0, -83.0))
        _wait_for_color(qapp, pane, QColor("red"))

        workspace.setComparisonPresentation(
            primary_id,
            secondary_id,
            split_position=0.0,
            orientation=ComparisonOrientation.HORIZONTAL,
        )
        _wait_for_color(qapp, pane, QColor("blue"))
    finally:
        workspace.close()
        document.close()
        qapp.processEvents()


def test_tiled_base_and_upscale_remain_visually_coherent_in_every_frame(qapp) -> None:
    """Reject transient tile geometry that a render-item-derived oracle conceals."""

    base = _comparison_pattern(QSize(768, 1024))
    upscale = base.scaled(
        QSize(1536, 2048),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
    largest = base.scaled(
        QSize(1024, 1920),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
    document = CanvasDocument()
    identifiers = tuple(
        document.create_composition_from_image(image)
        for image in (base, upscale, largest)
    )
    primary_id, secondary_id, _largest_id = identifiers
    reference = CanvasWorkspace(document=document, features=())
    comparison = CanvasWorkspace(document=document, features=())
    try:
        for workspace in (reference, comparison):
            workspace.resize(704, 936)
            workspace.show()
        reference.setSinglePresentation(primary_id)
        comparison.setComparisonPresentation(
            primary_id,
            secondary_id,
            split_position=0.37,
        )
        qapp.processEvents()
        reference_pane = reference.currentCanvas()
        comparison_pane = comparison.currentCanvas()
        assert reference_pane is not None
        assert comparison_pane is not None
        reference_view = reference_pane.view()

        for iteration, (zoom, pan, size) in enumerate(
            (
                (1.0, QPointF(), QSize(704, 936)),
                (1.75, QPointF(117.0, -83.0), QSize(811, 713)),
                (2.35, QPointF(-149.0, 131.0), QSize(677, 901)),
                (3.1, QPointF(203.0, -177.0), QSize(923, 641)),
                (1.43, QPointF(-211.0, -109.0), QSize(739, 887)),
                (2.73, QPointF(173.0, 197.0), QSize(857, 769)),
            )
        ):
            reference.resize(size)
            qapp.processEvents()
            reference_view.viewport.setZoomAndPan(zoom, pan)
            _wait_for_complete_render_plan(qapp, reference_view)
            comparison.resize(size)
            comparison.setComparisonPresentation(
                identifiers[0],
                identifiers[1 + iteration % (len(identifiers) - 1)],
                split_position=0.37,
            )
            comparison_pane.viewport.setZoomAndPan(zoom, pan)
            for split in (0.12, 0.61, 0.89, 0.43):
                comparison_pane.setComparisonSplit(
                    split,
                    ComparisonOrientation.VERTICAL,
                )
                _assert_frame_matches_reference(
                    reference_pane.grab().toImage(),
                    comparison_pane.grab().toImage(),
                    split_x=_comparison_divider_x(comparison_pane),
                )
                qapp.processEvents()
                _assert_frame_matches_reference(
                    reference_pane.grab().toImage(),
                    comparison_pane.grab().toImage(),
                    split_x=_comparison_divider_x(comparison_pane),
                )
    finally:
        comparison.close()
        reference.close()
        document.close()
        qapp.processEvents()


def test_smooth_secondary_native_zoom_never_exposes_displaced_tiles(qapp) -> None:
    """Keep every animated base/upscale comparison frame spatially coherent."""

    base = _comparison_pattern(QSize(768, 1024))
    upscale = base.scaled(
        QSize(1536, 2048),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
    document = CanvasDocument()
    primary_id = document.create_composition_from_image(base)
    secondary_id = document.create_composition_from_image(upscale)
    workspace = CanvasWorkspace(document=document, features=())
    try:
        workspace.resize(704, 936)
        workspace.setComparisonPresentation(
            primary_id,
            secondary_id,
            split_position=0.37,
        )
        workspace.show()
        qapp.processEvents()
        pane = workspace.currentCanvas()
        assert pane is not None
        pane.applySettings(
            smooth_zoom_enabled=True,
            smooth_zoom_duration_ms=180,
        )
        _wait_for_complete_render_plan(qapp, pane)

        QTest.mouseDClick(
            pane,
            Qt.MouseButton.LeftButton,
            pos=QPoint(round(pane.width() * 0.78), pane.height() // 2),
        )
        for frame_index in range(12):
            QTest.qWait(4)
            pane.setComparisonSplit(
                (0.19, 0.73, 0.41, 0.88)[frame_index % 4],
                ComparisonOrientation.VERTICAL,
            )
            _assert_comparison_matches_primary_pattern(
                pane, pane.grab().toImage(), base
            )
    finally:
        workspace.close()
        document.close()
        qapp.processEvents()


def test_each_partial_tile_arrival_preserves_comparison_geometry(qapp) -> None:
    """Reject any single ready tile that displaces normalized comparison content."""

    base = _comparison_pattern(QSize(768, 1024))
    upscale = _comparison_pattern(
        QSize(1536, 2048),
        colors=(
            QColor("#8e24aa"),
            QColor("#fdd835"),
            QColor("#00acc1"),
        ),
    )
    document = CanvasDocument()
    primary_id = document.create_composition_from_image(base)
    secondary_id = document.create_composition_from_image(upscale)
    backend = ControllableExecutionBackend()
    runtime = ExecutionRuntime(backend)
    workspace = CanvasWorkspace(
        document=document,
        features=(),
        execution_runtime=runtime,
    )
    try:
        workspace.resize(704, 936)
        workspace.setComparisonPresentation(
            primary_id,
            secondary_id,
            split_position=0.37,
        )
        workspace.show()
        qapp.processEvents()
        pane = workspace.currentCanvas()
        assert pane is not None
        pane.viewport.setZoomAndPan(2.35, QPointF(-149.0, 131.0))
        _assert_comparison_sources_match_normalized_scene(
            pane,
            pane.grab().toImage(),
            base,
            upscale,
        )

        completed_tiles = 0
        while tile_jobs := tuple(
            job
            for job in backend.pending_jobs()
            if job.operation == "render.tile.visible"
        ):
            backend.run_job(tile_jobs[-1])
            qapp.processEvents()
            _assert_comparison_sources_match_normalized_scene(
                pane,
                pane.grab().toImage(),
                base,
                upscale,
            )
            completed_tiles += 1
        assert completed_tiles >= 2
    finally:
        workspace.close()
        runtime.shutdown(wait=False)
        document.close()
        qapp.processEvents()


def test_pair_switches_never_present_mixed_compositing_patches(qapp) -> None:
    """Reject stale partial patches while comparison jobs complete out of order."""

    primary = _comparison_pattern(QSize(768, 1024))
    secondary_images = (
        _comparison_pattern(
            QSize(1536, 2048),
            colors=(
                QColor("#8e24aa"),
                QColor("#fdd835"),
                QColor("#00acc1"),
            ),
        ),
        _comparison_pattern(
            QSize(1024, 1920),
            colors=(
                QColor("#fb8c00"),
                QColor("#3949ab"),
                QColor("#7cb342"),
            ),
        ),
    )
    document = CanvasDocument()
    primary_id = document.create_composition_from_image(primary)
    secondary_ids = tuple(
        document.create_composition_from_image(image) for image in secondary_images
    )
    backend = ControllableExecutionBackend()
    runtime = ExecutionRuntime(backend)
    workspace = CanvasWorkspace(
        document=document,
        features=(),
        execution_runtime=runtime,
    )
    try:
        workspace.resize(704, 936)
        workspace.setComparisonPresentation(
            primary_id,
            secondary_ids[0],
            split_position=0.37,
        )
        workspace.show()
        qapp.processEvents()
        pane = workspace.currentCanvas()
        assert pane is not None
        pane.viewport.setZoomAndPan(2.35, QPointF(-149.0, 131.0))
        pane.grab()

        completed_jobs = 0
        for iteration in range(8):
            secondary_index = iteration % len(secondary_ids)
            workspace.setComparisonPresentation(
                primary_id,
                secondary_ids[secondary_index],
                split_position=(0.19, 0.73, 0.41, 0.88)[iteration % 4],
            )
            _assert_comparison_sources_match_normalized_scene(
                pane,
                pane.grab().toImage(),
                primary,
                secondary_images[secondary_index],
            )
            for job in tuple(reversed(backend.pending_jobs()))[:3]:
                backend.run_job(job)
                qapp.processEvents()
                _assert_comparison_sources_match_normalized_scene(
                    pane,
                    pane.grab().toImage(),
                    primary,
                    secondary_images[secondary_index],
                )
                completed_jobs += 1
        assert completed_jobs >= 4
    finally:
        workspace.close()
        runtime.shutdown(wait=False)
        document.close()
        qapp.processEvents()


def test_partial_damage_during_reused_zoom_cannot_mix_comparison_frames(qapp) -> None:
    """Reject an exact-frame patch painted into a transformed retained frame."""

    primary = _comparison_pattern(QSize(960, 1344))
    secondary = _comparison_pattern(
        QSize(1144, 1608),
        colors=(
            QColor("#8e24aa"),
            QColor("#fdd835"),
            QColor("#00acc1"),
        ),
    )
    document = CanvasDocument()
    primary_id = document.create_composition_from_image(primary)
    secondary_id = document.create_composition_from_image(secondary)
    workspace = CanvasWorkspace(document=document, features=())
    try:
        workspace.resize(704, 936)
        workspace.setComparisonPresentation(
            primary_id,
            secondary_id,
            split_position=0.37,
        )
        workspace.show()
        qapp.processEvents()
        pane = workspace.currentCanvas()
        assert pane is not None
        _wait_for_complete_render_plan(qapp, pane)
        pane.grab()

        pane.applyZoom(
            pane.currentZoom() * 1.35,
            QPointF(481.0, 287.0),
        )
        renderer = pane._rendering.presenter.renderer
        assert not renderer._presentation_transform.isIdentity()
        _assert_comparison_sources_match_normalized_scene(
            pane,
            pane.grab().toImage(),
            primary,
            secondary,
        )
        renderer.markDirty(QRect(341, 59, 12, 12))

        _assert_comparison_sources_match_normalized_scene(
            pane,
            pane.grab().toImage(),
            primary,
            secondary,
        )
    finally:
        workspace.close()
        document.close()
        qapp.processEvents()


def test_native_comparison_replaces_active_document_source_pixels(qapp) -> None:
    """Refresh an admitted comparison source without remounting the native pane."""

    document = CanvasDocument()
    primary_id = document.create_composition_from_image(
        _image(QSize(2048, 1536), QColor("red"))
    )
    secondary_id = document.create_composition_from_image(
        _image(QSize(4096, 3072), QColor("blue"))
    )
    workspace = CanvasWorkspace(document=document, features=())
    workspace.resize(960, 640)
    workspace.show()
    try:
        workspace.setComparisonPresentation(
            primary_id,
            secondary_id,
            split_position=0.0,
        )
        qapp.processEvents()
        pane = workspace.currentCanvas()
        assert pane is not None
        pane.viewport.setZoomAndPan(1.75, QPointF(117.0, -83.0))
        _wait_for_color(qapp, pane, QColor("blue"))
        before_zoom = pane.currentZoom()
        before_pan = pane.currentPan()

        assert document.replace_composition_image(
            secondary_id,
            _image(QSize(4096, 3072), QColor("magenta")),
        )

        _wait_for_color(qapp, pane, QColor("magenta"))
        assert workspace.currentCanvas() is pane
        assert pane.currentZoom() == before_zoom
        assert pane.currentPan() == before_pan
    finally:
        workspace.close()
        document.close()
        qapp.processEvents()


def test_native_comparison_repairs_active_source_removal(qapp) -> None:
    """Reveal the surviving primary when the compared composition disappears."""

    document = CanvasDocument()
    primary_id = document.create_composition_from_image(
        _image(QSize(2048, 1536), QColor("red"))
    )
    secondary_id = document.create_composition_from_image(
        _image(QSize(4096, 3072), QColor("blue"))
    )
    workspace = CanvasWorkspace(document=document, features=())
    workspace.resize(960, 640)
    workspace.show()
    try:
        workspace.setComparisonPresentation(
            primary_id,
            secondary_id,
            split_position=0.0,
        )
        qapp.processEvents()
        pane = workspace.currentCanvas()
        assert pane is not None
        pane.viewport.setZoomAndPan(1.75, QPointF(117.0, -83.0))
        _wait_for_color(qapp, pane, QColor("blue"))
        before_zoom = pane.currentZoom()
        before_pan = pane.currentPan()

        assert document.remove_composition(secondary_id)

        _wait_for_color(qapp, pane, QColor("red"))
        assert not pane.comparisonState().enabled
        assert pane.currentZoom() == before_zoom
        assert pane.currentPan() == before_pan
        surviving_canvas = workspace.currentCanvas()
        assert surviving_canvas is not None
        assert surviving_canvas is not pane
        assert surviving_canvas.currentCompositionID() == primary_id
    finally:
        workspace.close()
        document.close()
        qapp.processEvents()


def _image(size: QSize, color: QColor) -> QImage:
    """Return one opaque comparison source."""

    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(color)
    return image


def _comparison_pattern(
    size: QSize,
    *,
    colors: tuple[QColor, QColor, QColor] | None = None,
) -> QImage:
    """Return a normalized landmark pattern with broad exact-color interiors."""

    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    palette = colors or (QColor("#e53935"), QColor("#43a047"), QColor("#1e88e5"))
    for y in range(size.height()):
        row = y * 17 // size.height()
        for x in range(size.width()):
            column = x * 13 // size.width()
            image.setPixelColor(x, y, palette[(column * 5 + row * 7) % len(palette)])
    return image


def _wait_for_complete_render_plan(qapp, pane) -> None:
    """Wait until the independent reference owns every visible tile."""

    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < 2_000:
        qapp.processEvents()
        plan = pane.calculateRenderPlan()
        assert plan is not None
        complete = True
        for item in plan.render_items:
            visible_range = item.visible_tile_range
            if visible_range is None:
                continue
            start_row, end_row, start_column, end_column = visible_range
            expected = (end_row - start_row + 1) * (end_column - start_column + 1)
            if len(item.tiles_to_draw) != expected:
                complete = False
                break
        if complete:
            return
    raise AssertionError("single-image reference tiles did not settle")


def _comparison_divider_x(pane) -> float:
    """Return the actual normalized-scene divider projection."""

    plan = pane.calculateRenderPlan()
    assert plan is not None
    secondary = plan.render_items[1]
    clip = secondary.clip
    assert clip is not None
    scene_x = plan.scene_bounds.x + clip.x * plan.scene_bounds.width
    source_x = (
        (scene_x - secondary.placement.x)
        * secondary.source_size.width()
        / secondary.placement.width
    )
    return secondary.transform.map(QPointF(source_x, 0.0)).x()


def _assert_comparison_matches_primary_pattern(
    pane,
    frame: QImage,
    primary_source: QImage,
) -> None:
    """Validate rendered pixels against the primary's current normalized geometry."""

    plan = pane.calculateRenderPlan()
    assert plan is not None
    primary = plan.render_items[0]
    inverse, invertible = primary.transform.inverted()
    assert invertible
    split_x = _comparison_divider_x(pane)
    mismatches: list[tuple[int, int, str, str]] = []
    for y in range(13, frame.height() - 13, 11):
        for x in range(13, frame.width() - 13, 11):
            if abs(x - split_x) <= 4.0:
                continue
            product_point = inverse.map(QPointF(float(x), float(y)))
            source_x = int(product_point.x() / max(primary.pyramid_scale, 1e-9))
            source_y = int(product_point.y() / max(primary.pyramid_scale, 1e-9))
            if not (
                0 <= source_x < primary_source.width()
                and 0 <= source_y < primary_source.height()
            ):
                continue
            normalized_x = source_x * 13 / primary_source.width()
            normalized_y = source_y * 17 / primary_source.height()
            if (
                min(normalized_x % 1.0, 1.0 - normalized_x % 1.0) < 0.08
                or min(normalized_y % 1.0, 1.0 - normalized_y % 1.0) < 0.08
            ):
                continue
            expected = primary_source.pixelColor(source_x, source_y)
            actual = frame.pixelColor(x, y)
            if (
                max(
                    abs(actual.red() - expected.red()),
                    abs(actual.green() - expected.green()),
                    abs(actual.blue() - expected.blue()),
                )
                > 32
            ):
                mismatches.append((x, y, expected.name(), actual.name()))
    assert not mismatches, {
        "count": len(mismatches),
        "bounds": (
            min(value[0] for value in mismatches),
            min(value[1] for value in mismatches),
            max(value[0] for value in mismatches),
            max(value[1] for value in mismatches),
        ),
        "first": mismatches[:12],
        "zoom": pane.currentZoom(),
        "pan": pane.currentPan(),
    }


def _assert_comparison_sources_match_normalized_scene(
    pane,
    frame: QImage,
    primary_source: QImage,
    secondary_source: QImage,
) -> None:
    """Validate both reveal sides from primary-owned normalized scene geometry."""

    plan = pane.calculateRenderPlan()
    assert plan is not None
    primary = plan.render_items[0]
    inverse, invertible = primary.transform.inverted()
    assert invertible
    split_x = _comparison_divider_x(pane)
    mismatches: list[tuple[int, int, str, str]] = []
    for y in range(13, frame.height() - 13, 11):
        for x in range(13, frame.width() - 13, 11):
            if abs(x - split_x) <= 4.0:
                continue
            product_point = inverse.map(QPointF(float(x), float(y)))
            primary_x = product_point.x() / max(primary.pyramid_scale, 1e-9)
            primary_y = product_point.y() / max(primary.pyramid_scale, 1e-9)
            normalized_x = primary_x / primary_source.width()
            normalized_y = primary_y / primary_source.height()
            if not (0.0 <= normalized_x < 1.0 and 0.0 <= normalized_y < 1.0):
                continue
            pattern_x = normalized_x * 13
            pattern_y = normalized_y * 17
            if (
                min(pattern_x % 1.0, 1.0 - pattern_x % 1.0) < 0.08
                or min(pattern_y % 1.0, 1.0 - pattern_y % 1.0) < 0.08
            ):
                continue
            source = secondary_source if x >= split_x else primary_source
            source_x = min(source.width() - 1, int(normalized_x * source.width()))
            source_y = min(source.height() - 1, int(normalized_y * source.height()))
            expected = source.pixelColor(source_x, source_y)
            actual = frame.pixelColor(x, y)
            if (
                max(
                    abs(actual.red() - expected.red()),
                    abs(actual.green() - expected.green()),
                    abs(actual.blue() - expected.blue()),
                )
                > 32
            ):
                mismatches.append((x, y, expected.name(), actual.name()))
    assert not mismatches, {
        "count": len(mismatches),
        "bounds": (
            min(value[0] for value in mismatches),
            min(value[1] for value in mismatches),
            max(value[0] for value in mismatches),
            max(value[1] for value in mismatches),
        ),
        "first": mismatches[:12],
        "zoom": pane.currentZoom(),
        "pan": pane.currentPan(),
    }


def _assert_frame_matches_reference(
    reference: QImage,
    comparison: QImage,
    *,
    split_x: float,
) -> None:
    """Require identical landmark pixels away from the material divider."""

    assert comparison.size() == reference.size()
    mismatches: list[tuple[int, int, str, str]] = []
    landmarks = {"#e53935", "#43a047", "#1e88e5"}
    for y in range(13, comparison.height() - 13, 11):
        for x in range(13, comparison.width() - 13, 11):
            if abs(x - split_x) <= 4.0:
                continue
            expected = reference.pixelColor(x, y)
            if expected.name() not in landmarks:
                continue
            if any(
                reference.pixelColor(x + offset_x, y + offset_y) != expected
                for offset_x, offset_y in (
                    (-3, 0),
                    (3, 0),
                    (0, -3),
                    (0, 3),
                )
            ):
                continue
            actual = comparison.pixelColor(x, y)
            if (
                max(
                    abs(actual.red() - expected.red()),
                    abs(actual.green() - expected.green()),
                    abs(actual.blue() - expected.blue()),
                )
                > 32
            ):
                mismatches.append((x, y, expected.name(), actual.name()))
    assert not mismatches, {
        "count": len(mismatches),
        "bounds": (
            min(value[0] for value in mismatches),
            min(value[1] for value in mismatches),
            max(value[0] for value in mismatches),
            max(value[1] for value in mismatches),
        ),
        "first": mismatches[:12],
    }


def _wait_for_color(qapp, pane, expected: QColor) -> None:
    """Wait for dense opaque pixels from the requested reveal source."""

    timer = QElapsedTimer()
    timer.start()
    actual: tuple[QColor, ...] = ()
    while timer.elapsed() < 2_000:
        qapp.processEvents()
        frame = pane.grab().toImage()
        actual = tuple(
            frame.pixelColor(x, y)
            for x, y in (
                (19, 56),
                (80, 80),
                (320, 180),
                (640, 360),
                (880, 560),
            )
        )
        if all(color == expected for color in actual):
            return
    plan = pane.calculateRenderPlan()
    diagnostic = (
        f"pixels={tuple(color.name(QColor.NameFormat.HexArgb) for color in actual)!r}; "
        f"zoom={pane.currentZoom()!r}; pan={pane.currentPan()!r}; "
        f"items={None if plan is None else tuple((item.descriptor.source.revision, item.strategy.value, item.placement, item.visible_tile_range, len(item.tiles_to_draw), item.clip) for item in plan.render_items)!r}"
    )
    assert actual == tuple(expected for _color in actual), diagnostic
