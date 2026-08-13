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
"""Mounted adversarial document-presentation and linked-inspection workflows."""

from __future__ import annotations

import uuid

import pytest
from PySide6.QtCore import (
    QCoreApplication,
    QElapsedTimer,
    QEvent,
    QPointF,
    QRectF,
    QSize,
)
from PySide6.QtGui import QColor, QImage, QPainter

from cutecanvas import CuteCanvas
from cutecanvas.document import CanvasDocument, CanvasInspectionGroup
from cutecanvas.presentation import CanvasWorkspace
from cutecanvas_test_support.harness.timing import (
    INTERACTIVE_PERFORMANCE,
    average_interaction_latency_ms,
)
from qpane.scene import ClipCoordinateSpace, RenderStrategy
from qpane.scene.render_plan import (
    SampledLayerRenderItem,
    SceneRenderItem,
    SceneRenderPlan,
)
from qpane.sdk.rendering import ViewportZoomMode
from qpane.sdk.types import ComparisonOrientation

pytestmark = INTERACTIVE_PERFORMANCE

_PRESENTATION_SWITCH_BUDGET_MS = 8.0


def test_workspace_survives_switch_resize_link_and_teardown_storm(qapp) -> None:
    """Presentation storms must stay fast, deterministic, and content-neutral."""
    document = CanvasDocument()
    large_image = QImage(
        QSize(4096, 2160),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    large_image.fill(QColor("steelblue"))
    first_id = document.create_composition_from_image(
        large_image,
        title="Target 0",
    )
    identifiers = (first_id,) + tuple(
        document.create_composition(
            QRectF(0.0, 0.0, width, height),
            title=f"Target {index}",
        )
        for index, (width, height) in enumerate(
            (
                (2048.0, 1080.0),
                (1024.0, 1024.0),
                (1600.0, 2400.0),
                (8192.0, 4096.0),
                (800.0, 1200.0),
            ),
            start=1,
        )
    )
    workspace = CanvasWorkspace(document=document, features=())
    workspace.resize(1280, 800)
    try:
        workspace.setInspectionGroups(
            (CanvasInspectionGroup(uuid.uuid4(), identifiers),)
        )
        workspace.setTabbedPresentation(identifiers)
        workspace.setGridPresentation(identifiers)
        workspace.setComparisonPresentation(identifiers[0], identifiers[1])
        retained = tuple(workspace.canvasFor(value) for value in identifiers)
        before = document.snapshot()
        iteration = 0

        def switch() -> None:
            """Cycle every built-in multi-target arrangement and resize jitter."""
            nonlocal iteration
            mode = iteration % 3
            if mode == 0:
                workspace.setTabbedPresentation(identifiers)
            elif mode == 1:
                workspace.setGridPresentation(identifiers)
            else:
                workspace.setComparisonPresentation(
                    identifiers[0],
                    identifiers[1],
                    split_position=(iteration % 97) / 96.0,
                )
            workspace.resize(1000 + iteration % 31, 650 + iteration % 23)
            iteration += 1

        average_ms = average_interaction_latency_ms(switch, repetitions=150)
        qapp.processEvents()

        assert average_ms < _PRESENTATION_SWITCH_BUDGET_MS
        assert tuple(workspace.canvasFor(value) for value in identifiers) == retained
        assert document.snapshot() == before

        workspace.setTabbedPresentation(identifiers[:2])
        first = workspace.canvasFor(identifiers[0])
        second = workspace.canvasFor(identifiers[1])
        assert first is not None and second is not None
        first.view().viewport.zoom_mode = ViewportZoomMode.CUSTOM
        first.view().viewport.setZoomAndPan(2.0, QPointF(32.0, -16.0))
        qapp.processEvents()
        assert second.view().viewport.zoom == 4.0
    finally:
        workspace.close()
        document.close()
        qapp.processEvents()


def test_comparison_pair_storm_reuses_one_native_scene_and_remains_interactive(
    qapp,
) -> None:
    """Switch reveal pairs without rebuilding a renderer or replaying stale pixels."""

    document = CanvasDocument()
    colors = ("red", "blue", "green", "yellow")
    identifiers = tuple(
        document.create_composition_from_image(_solid_image(color), title=color)
        for color in colors
    )
    workspace = CanvasWorkspace(document=document, features=())
    workspace.resize(960, 640)
    try:
        workspace.setComparisonPresentation(identifiers[0], identifiers[1])
        workspace.show()
        qapp.processEvents()
        pane = workspace.currentCanvas()
        assert pane is not None

        iteration = 0

        def switch_pair() -> None:
            """Advance both reveal sources through the persistent catalog scene."""

            nonlocal iteration
            primary = identifiers[iteration % len(identifiers)]
            secondary = identifiers[(iteration + 1) % len(identifiers)]
            workspace.setComparisonPresentation(
                primary,
                secondary,
                split_position=(iteration % 97) / 96.0,
            )
            iteration += 1

        average_ms = average_interaction_latency_ms(switch_pair, repetitions=120)
        qapp.processEvents()

        assert average_ms < _PRESENTATION_SWITCH_BUDGET_MS
        assert workspace.currentCanvas() is pane
        assert len(pane.catalog().entries) == len(identifiers)
        expected_primary = identifiers[(iteration - 1) % len(identifiers)]
        expected_secondary = identifiers[iteration % len(identifiers)]
        assert pane.catalog().current is not None
        assert pane.catalog().current.entry_id == expected_primary
        assert pane.comparisonState().source_id == expected_secondary
    finally:
        workspace.close()
        document.close()
        qapp.processEvents()


@pytest.mark.interactive_performance
def test_comparison_tile_abuse_preserves_dense_patterned_pixels(qapp) -> None:
    """Keep tiled heterogeneous pairs coherent through mounted navigation churn."""

    document = CanvasDocument()
    fixtures = (
        (
            QSize(2048, 1536),
            (QColor("#f5222d"), QColor("#13c2c2"), QColor("#faad14")),
        ),
        (
            QSize(4096, 3072),
            (QColor("#2f54eb"), QColor("#fadb14"), QColor("#eb2f96")),
        ),
        (
            QSize(3072, 2304),
            (QColor("#52c41a"), QColor("#722ed1"), QColor("#fa8c16")),
        ),
        (
            QSize(2560, 1920),
            (QColor("#08979c"), QColor("#a8071a"), QColor("#7cb305")),
        ),
    )
    images = tuple(
        _normalized_pattern_image(size, palette) for size, palette in fixtures
    )
    identifiers = tuple(
        document.create_composition_from_image(image, title=f"Pattern {index}")
        for index, image in enumerate(images)
    )
    workspace = CanvasWorkspace(document=document, features=())
    workspace.resize(960, 640)
    workspace.show()
    try:
        workspace.setComparisonPresentation(identifiers[0], identifiers[1])
        qapp.processEvents()
        pane = workspace.currentCanvas()
        assert pane is not None
        pane.applySettings(
            cache={"mode": "hard", "budget_mb": 1024},
            smooth_zoom_enabled=False,
        )
        pane.viewport.zoom_mode = ViewportZoomMode.CUSTOM
        pane.viewport.setZoomAndPan(1.75, QPointF(117.0, -83.0))
        pane.setComparisonSplit(1.0, ComparisonOrientation.VERTICAL)
        _wait_for_dense_comparison_pixels(
            qapp,
            pane,
            {
                identifiers[0]: images[0],
                identifiers[1]: images[1],
            },
        )

        for iteration in range(24):
            primary_index = iteration % len(identifiers)
            secondary_index = (iteration * 3 + 1) % len(identifiers)
            if secondary_index == primary_index:
                secondary_index = (secondary_index + 1) % len(identifiers)
            workspace.setComparisonPresentation(
                identifiers[primary_index],
                identifiers[secondary_index],
                split_position=((iteration * 17) % 101) / 100.0,
                orientation=(
                    ComparisonOrientation.VERTICAL
                    if iteration % 2
                    else ComparisonOrientation.HORIZONTAL
                ),
            )
            _wait_for_dense_comparison_pixels(
                qapp,
                pane,
                {
                    identifiers[primary_index]: images[primary_index],
                    identifiers[secondary_index]: images[secondary_index],
                },
                require_tiled=False,
            )
            pane.viewport.zoom_mode = ViewportZoomMode.CUSTOM
            pane.viewport.setZoomAndPan(
                1.1 + (iteration % 5) * 0.37,
                QPointF(
                    float((iteration * 47) % 241 - 120),
                    float((iteration * 31) % 181 - 90),
                ),
            )
            _wait_for_dense_comparison_pixels(
                qapp,
                pane,
                {
                    identifiers[primary_index]: images[primary_index],
                    identifiers[secondary_index]: images[secondary_index],
                },
            )
            workspace.resize(801 + iteration * 7, 577 + (iteration * 11) % 97)
            qapp.processEvents()
            _wait_for_dense_comparison_pixels(
                qapp,
                pane,
                {
                    identifiers[primary_index]: images[primary_index],
                    identifiers[secondary_index]: images[secondary_index],
                },
            )
    finally:
        workspace.close()
        document.close()
        qapp.processEvents()


def test_disjoint_grid_targets_survive_deferred_surface_destruction(qapp) -> None:
    """Retained grid targets must outlive the presentation surface they leave."""

    document = CanvasDocument()
    first_group = tuple(
        document.create_composition_from_image(
            _solid_image(color),
            title=f"First {index}",
        )
        for index, color in enumerate(("red", "green", "blue"))
    )
    second_group = tuple(
        document.create_composition_from_image(
            _solid_image(color),
            title=f"Second {index}",
        )
        for index, color in enumerate(("cyan", "magenta", "yellow"))
    )
    workspace = CanvasWorkspace(document=document, features=())
    workspace.resize(960, 640)
    workspace.show()
    try:
        workspace.setGridPresentation(first_group)
        qapp.processEvents()
        retained = tuple(workspace.canvasFor(target_id) for target_id in first_group)
        assert all(canvas is not None for canvas in retained)

        workspace.setGridPresentation(second_group)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        workspace.setGridPresentation(first_group)
        qapp.processEvents()

        assert tuple(workspace.canvasFor(target_id) for target_id in first_group) == (
            retained
        )
        assert all(canvas is not None and canvas.isVisible() for canvas in retained)
    finally:
        workspace.close()
        document.close()
        qapp.processEvents()


def test_disjoint_grid_switching_survives_retention_pressure(qapp) -> None:
    """Rapid disjoint-grid cycles must safely park, evict, and recreate targets."""

    document = CanvasDocument()
    groups = tuple(
        tuple(
            document.create_composition_from_image(
                _solid_image(color),
                title=f"Group {group_index} target {target_index}",
            )
            for target_index, color in enumerate(colors)
        )
        for group_index, colors in enumerate(
            (
                ("red", "green", "blue"),
                ("cyan", "magenta", "yellow"),
                ("black", "white", "gray"),
            )
        )
    )
    workspace = CanvasWorkspace(
        document=document,
        features=(),
        retained_target_capacity=1,
    )
    workspace.resize(960, 640)
    workspace.show()
    try:
        for group in groups * 5:
            workspace.setGridPresentation(group)
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qapp.processEvents()

            canvases = tuple(workspace.canvasFor(target_id) for target_id in group)
            assert all(canvas is not None and canvas.isVisible() for canvas in canvases)
            assert len(workspace.findChildren(CuteCanvas)) <= len(group) + 1
    finally:
        workspace.close()
        document.close()
        qapp.processEvents()


def _solid_image(color: str) -> QImage:
    """Return one source image suitable for mounted reveal-pair abuse coverage."""

    image = QImage(QSize(640, 480), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(color))
    return image


def _normalized_pattern_image(
    size: QSize,
    palette: tuple[QColor, QColor, QColor],
) -> QImage:
    """Return a high-entropy normalized pattern independent of source resolution."""

    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    columns = 29
    rows = 23
    try:
        for row in range(rows):
            top = round(row * size.height() / rows)
            bottom = round((row + 1) * size.height() / rows)
            for column in range(columns):
                left = round(column * size.width() / columns)
                right = round((column + 1) * size.width() / columns)
                color = palette[(column * 7 + row * 11) % len(palette)]
                painter.fillRect(left, top, right - left, bottom - top, color)
    finally:
        painter.end()
    return image


def _wait_for_dense_comparison_pixels(
    qapp,
    pane,
    sources: dict[uuid.UUID, QImage],
    *,
    require_tiled: bool = True,
) -> None:
    """Require coherent pixels through every hostile tile-arrival frame."""

    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < 5_000:
        qapp.processEvents()
        plan = pane.calculateRenderPlan()
        assert plan is not None
        if require_tiled:
            assert all(
                isinstance(item, SampledLayerRenderItem)
                or item.strategy is RenderStrategy.TILE
                for item in plan.render_items
            )
        frame = pane.grab().toImage()
        mismatch = _first_dense_comparison_mismatch(plan, frame, sources)
        assert mismatch is None, (
            mismatch,
            plan.render_items[1].clip,
            pane.comparisonState(),
        )
        if not require_tiled or all(
            _visible_tiles_complete(item) for item in plan.render_items
        ):
            return
    raise AssertionError("comparison tiles did not settle within 5 seconds")


def _visible_tiles_complete(item: SceneRenderItem) -> bool:
    """Return whether every tile in one visible range has arrived."""

    visible_range = getattr(item, "visible_tile_range", None)
    if visible_range is None:
        return True
    start_row, end_row, start_column, end_column = visible_range
    expected = (end_row - start_row + 1) * (end_column - start_column + 1)
    return len(getattr(item, "tiles_to_draw", ())) == expected


def _first_dense_comparison_mismatch(
    plan,
    frame: QImage,
    sources: dict[uuid.UUID, QImage],
) -> tuple[QPointF, QColor, QColor] | None:
    """Return the first wrong interior pattern sample in one rendered frame."""

    items = plan.render_items
    assert len(items) == 2
    primary, secondary = items
    clip = secondary.clip
    assert clip is not None
    assert clip.coordinate_space is ClipCoordinateSpace.NORMALIZED_SCENE
    divider_x, divider_y = _projected_comparison_divider(plan, secondary)
    primary_source = sources[primary.descriptor.source.resource_id]
    inverse, invertible = primary.transform.inverted()
    assert invertible
    for y in range(19, frame.height() - 19, 37):
        for x in range(19, frame.width() - 19, 41):
            point = QPointF(float(x), float(y))
            use_secondary = x >= divider_x if clip.width < 1.0 else y >= divider_y
            primary_point = inverse.map(point)
            if not isinstance(primary, SampledLayerRenderItem):
                primary_point /= max(primary.pyramid_scale, 1e-9)
            normalized_x = primary_point.x() / primary_source.width()
            normalized_y = primary_point.y() / primary_source.height()
            if not (0.0 <= normalized_x < 1.0 and 0.0 <= normalized_y < 1.0):
                continue
            source = sources[
                (
                    secondary.descriptor.source.resource_id
                    if use_secondary
                    else primary.descriptor.source.resource_id
                )
            ]
            source_x = min(source.width() - 1, int(normalized_x * source.width()))
            source_y = min(source.height() - 1, int(normalized_y * source.height()))
            pattern_x = normalized_x * 29
            pattern_y = normalized_y * 23
            if (
                min(pattern_x % 1.0, 1.0 - pattern_x % 1.0) < 0.12
                or min(pattern_y % 1.0, 1.0 - pattern_y % 1.0) < 0.12
                or abs(x - divider_x) < 3.0
                or abs(y - divider_y) < 3.0
            ):
                continue
            expected = source.pixelColor(source_x, source_y)
            actual = frame.pixelColor(x, y)
            if not _colors_match_reconstruction(expected, actual):
                return point, expected, actual
    return None


def _colors_match_reconstruction(expected: QColor, actual: QColor) -> bool:
    """Allow only the one-code-value rounding bound of RGBA8 reconstruction."""
    return all(
        abs(expected_channel - actual_channel) <= 1
        for expected_channel, actual_channel in zip(
            expected.getRgb(),
            actual.getRgb(),
            strict=True,
        )
    )


def _projected_comparison_divider(
    plan: SceneRenderPlan,
    item: SceneRenderItem,
) -> tuple[float, float]:
    """Project the comparison item's normalized scene seam into widget space."""

    clip = item.clip
    assert clip is not None
    placement = item.placement
    scene_bounds = plan.scene_bounds
    source_size = item.source_size
    scene_x = scene_bounds.x + clip.x * scene_bounds.width
    scene_y = scene_bounds.y + clip.y * scene_bounds.height
    source_x = (scene_x - placement.x) * source_size.width() / placement.width
    source_y = (scene_y - placement.y) * source_size.height() / placement.height
    projected = item.transform.map(QPointF(source_x, source_y))
    return projected.x(), projected.y()
