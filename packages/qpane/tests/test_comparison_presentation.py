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

"""Characterize coherent, source-normalized QPane comparison presentation."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from PySide6.QtCore import QElapsedTimer, QLineF, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from qpane.scene.render_plan import SceneRenderPlan

from qpane import ComparisonOrientation, QPane, RenderScene


def test_heterogeneous_comparison_sources_share_the_primary_frame(qapp) -> None:
    """Normalize both sources onto one primary-owned comparison rectangle."""

    pane, primary_id, secondary_id = _comparison_pane(
        qapp,
        primary_size=QSize(640, 480),
        secondary_size=QSize(1600, 900),
    )
    try:
        pane.setComparisonPair(primary_id, secondary_id)
        qapp.processEvents()

        scene = pane.scene()
        plan = pane.calculateRenderPlan()

        assert scene is not None
        assert scene.canvas.size().toSize() == QSize(640, 480)
        assert plan is not None
        assert len(plan.render_items) == 2
        primary, secondary = plan.render_items
        assert primary.placement == plan.scene_bounds
        assert secondary.placement == plan.scene_bounds
        assert primary.transform.m11() == primary.transform.m22()
        assert secondary.transform.m11() != primary.transform.m11()
        assert secondary.transform.m22() != primary.transform.m22()
    finally:
        _close(pane, qapp)


def test_atomic_pair_change_submits_only_the_requested_pair(qapp) -> None:
    """Replace both comparison sources without exposing an obsolete mixed pair."""

    pane = QPane()
    pane.resize(960, 640)
    pane.show()
    source_ids = tuple(uuid4() for _index in range(4))
    sizes = (QSize(640, 480), QSize(800, 600), QSize(900, 1200), QSize(2048, 1024))
    try:
        for source_id, size in zip(source_ids, sizes, strict=True):
            pane.addImage(
                _image(size, QColor.fromHsv(source_id.int % 360, 255, 255)),
                source_id=source_id,
                label=str(source_id),
                select=False,
            )
        pane.setComparisonPair(source_ids[0], source_ids[1])
        qapp.processEvents()
        scenes: list[RenderScene | None] = []
        pane.sceneChanged.connect(scenes.append)

        pane.setComparisonPair(source_ids[2], source_ids[3])
        qapp.processEvents()

        assert len(scenes) == 1
        scene = scenes[0]
        assert scene is not None
        assert tuple(layer.source.resource_id for layer in scene.layers) == (
            source_ids[2],
            source_ids[3],
        )
    finally:
        _close(pane, qapp)


def test_split_churn_is_presentation_only(qapp) -> None:
    """Move and rotate the divider without replacing durable scene content."""

    pane, primary_id, secondary_id = _comparison_pane(
        qapp,
        primary_size=QSize(4096, 4096),
        secondary_size=QSize(3072, 2048),
    )
    try:
        pane.setComparisonPair(primary_id, secondary_id)
        qapp.processEvents()
        initial_scene = pane.scene()
        scenes: list[RenderScene | None] = []
        pane.sceneChanged.connect(scenes.append)

        for index in range(102):
            pane.setComparisonSplit(
                index / 100.0,
                (
                    ComparisonOrientation.VERTICAL
                    if index % 2
                    else ComparisonOrientation.HORIZONTAL
                ),
            )
        qapp.processEvents()

        assert scenes == []
        assert pane.scene() is initial_scene
        state = pane.comparisonState()
        assert state.split_position == 1.0
        assert state.orientation is ComparisonOrientation.VERTICAL
        plan = pane.calculateRenderPlan()
        assert plan is not None
        comparison_item = plan.render_items[1]
        assert comparison_item.clip is not None
        assert comparison_item.clip.width == 0.0
    finally:
        _close(pane, qapp)


def test_comparison_pair_validation_is_atomic(qapp) -> None:
    """Reject invalid pairs without changing selection or rendered content."""

    pane, primary_id, secondary_id = _comparison_pane(
        qapp,
        primary_size=QSize(64, 48),
        secondary_size=QSize(80, 45),
    )
    try:
        pane.setComparisonPair(primary_id, secondary_id)
        qapp.processEvents()
        scene = pane.scene()
        state = pane.comparisonState()
        scenes: list[RenderScene | None] = []
        pane.sceneChanged.connect(scenes.append)

        with pytest.raises(ValueError, match="distinct"):
            pane.setComparisonPair(primary_id, primary_id)
        with pytest.raises(KeyError, match="primary"):
            pane.setComparisonPair(uuid4(), secondary_id)
        with pytest.raises(KeyError, match="comparison"):
            pane.setComparisonPair(primary_id, uuid4())

        assert pane.scene() is scene
        assert pane.comparisonState() == state
        assert scenes == []
    finally:
        _close(pane, qapp)


def test_patterned_comparison_frames_follow_every_divider_extreme(qapp) -> None:
    """Render normalized unlike sources correctly after hostile clip changes."""

    pane = QPane()
    pane.resize(640, 480)
    pane.show()
    primary_id = uuid4()
    secondary_id = uuid4()
    primary = _quadrant_image(
        QSize(160, 120),
        (QColor("red"), QColor("green"), QColor("cyan"), QColor("magenta")),
    )
    secondary = _quadrant_image(
        QSize(400, 180),
        (QColor("blue"), QColor("yellow"), QColor("white"), QColor("black")),
    )
    try:
        pane.addImage(primary, source_id=primary_id, label="primary", select=False)
        pane.addImage(
            secondary,
            source_id=secondary_id,
            label="secondary",
            select=False,
        )
        pane.setComparisonPair(primary_id, secondary_id)
        qapp.processEvents()
        plan = pane.calculateRenderPlan()
        assert plan is not None
        primary_item = plan.render_items[0]
        sample_points = tuple(
            primary_item.transform.map(
                QPointF(primary.width() * x, primary.height() * y)
            )
            for x, y in ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75))
        )

        cases = (
            (
                0.0,
                ComparisonOrientation.VERTICAL,
                (QColor("blue"), QColor("yellow"), QColor("white"), QColor("black")),
            ),
            (
                1.0,
                ComparisonOrientation.VERTICAL,
                (QColor("red"), QColor("green"), QColor("cyan"), QColor("magenta")),
            ),
            (
                0.5,
                ComparisonOrientation.VERTICAL,
                (QColor("red"), QColor("yellow"), QColor("cyan"), QColor("black")),
            ),
            (
                0.5,
                ComparisonOrientation.HORIZONTAL,
                (QColor("red"), QColor("green"), QColor("white"), QColor("black")),
            ),
        )
        for split, orientation, expected in cases * 3:
            pane.setComparisonSplit(split, orientation)
            _wait_for_pixels(qapp, pane, sample_points, expected)
    finally:
        _close(pane, qapp)


def test_tiled_comparison_frames_follow_divider_extremes(qapp) -> None:
    """Apply transient reveal clips after zoom forces both sources into tiles."""

    pane, primary_id, secondary_id = _comparison_pane(
        qapp,
        primary_size=QSize(2048, 1536),
        secondary_size=QSize(4096, 3072),
    )
    pane.applySettings(smooth_zoom_enabled=False)
    try:
        pane.setComparisonPair(primary_id, secondary_id)
        pane.viewport.setZoomAndPan(1.75, QPointF(117.0, -83.0))
        pane.setComparisonSplit(1.0, ComparisonOrientation.VERTICAL)
        plan = pane.calculateRenderPlan()
        assert plan is not None
        assert all(item.strategy.value == "tile" for item in plan.render_items)
        sample_points = tuple(
            QPointF(x, y) for x, y in ((80, 80), (320, 180), (640, 360), (880, 560))
        )
        _wait_for_pixels(
            qapp,
            pane,
            sample_points,
            tuple(QColor("red") for _point in sample_points),
        )

        pane.setComparisonSplit(0.0, ComparisonOrientation.HORIZONTAL)
        _wait_for_pixels(
            qapp,
            pane,
            sample_points,
            tuple(QColor("blue") for _point in sample_points),
        )

        pane.setComparisonSplit(0.4, ComparisonOrientation.VERTICAL)
        before_divider = pane.comparisonDividerState().full_segment
        assert before_divider is not None
        pane.viewport.setZoomAndPan(2.25, QPointF(-211.0, 143.0))
        after_divider = pane.comparisonDividerState().full_segment
        assert after_divider != before_divider
    finally:
        _close(pane, qapp)


def test_comparison_divider_tracks_the_transformed_scene_seam(qapp) -> None:
    """Keep divider artwork on the rendered seam through pan and zoom."""

    pane, primary_id, secondary_id = _comparison_pane(
        qapp,
        primary_size=QSize(2048, 1536),
        secondary_size=QSize(4096, 3072),
    )
    pane.applySettings(smooth_zoom_enabled=False)
    try:
        pane.setComparisonSplit(0.31, ComparisonOrientation.VERTICAL)
        pane.setComparisonPair(primary_id, secondary_id)
        pane.viewport.setZoomAndPan(1.75, QPointF(117.0, -83.0))
        before_plan = pane.calculateRenderPlan()
        before_divider = pane.comparisonDividerState().full_segment
        assert before_plan is not None
        assert before_divider is not None
        before_seam = _projected_scene_seam(
            before_plan,
            split_position=0.31,
            orientation=ComparisonOrientation.VERTICAL,
        )
        assert before_divider.p1().x() == pytest.approx(before_seam.p1().x())
        assert before_divider.p2().x() == pytest.approx(before_seam.p2().x())

        pane.viewport.setZoomAndPan(2.25, QPointF(-211.0, 143.0))
        after_plan = pane.calculateRenderPlan()
        after_divider = pane.comparisonDividerState().full_segment
        assert after_plan is not None
        assert after_divider is not None
        after_seam = _projected_scene_seam(
            after_plan,
            split_position=0.31,
            orientation=ComparisonOrientation.VERTICAL,
        )
        assert after_divider.p1().x() == pytest.approx(after_seam.p1().x())
        assert after_divider.p2().x() == pytest.approx(after_seam.p2().x())
        assert after_divider.p1().x() != pytest.approx(before_divider.p1().x())
    finally:
        _close(pane, qapp)


def test_double_click_resolves_one_to_one_for_visible_comparison_source(qapp) -> None:
    """Toggle Fit/native zoom using the clipped source under the pointer."""

    pane, primary_id, secondary_id = _comparison_pane(
        qapp,
        primary_size=QSize(320, 240),
        secondary_size=QSize(640, 480),
    )
    pane.applySettings(smooth_zoom_enabled=False)
    try:
        pane.setComparisonPair(primary_id, secondary_id)
        pane.setZoomFit()
        qapp.processEvents()
        plan = pane.calculateRenderPlan()
        assert plan is not None
        assert len(plan.render_items) == 2
        primary, secondary = plan.render_items
        primary_point = primary.transform.map(QPointF(80.0, 120.0)).toPoint()
        secondary_point = secondary.transform.map(QPointF(480.0, 240.0)).toPoint()
        secondary_source_point = secondary.transform.inverted()[0].map(
            QPointF(secondary_point)
        )

        QTest.mouseDClick(
            pane,
            Qt.MouseButton.LeftButton,
            pos=primary_point,
        )
        qapp.processEvents()
        assert pane.currentZoom() == pytest.approx(1.0)

        QTest.mouseDClick(
            pane,
            Qt.MouseButton.LeftButton,
            pos=primary_point,
        )
        qapp.processEvents()
        assert pane.viewport.get_zoom_mode().value == "fit"

        QTest.mouseDClick(
            pane,
            Qt.MouseButton.LeftButton,
            pos=secondary_point,
        )
        qapp.processEvents()

        assert pane.currentZoom() == pytest.approx(2.0)
        assert pane.viewport.get_zoom_mode().value == "1to1"
        restored_plan = pane.calculateRenderPlan()
        assert restored_plan is not None
        restored_secondary = restored_plan.render_items[1]
        restored_source_point = restored_secondary.transform.inverted()[0].map(
            QPointF(secondary_point)
        )
        assert restored_source_point.x() == pytest.approx(secondary_source_point.x())
        assert restored_source_point.y() == pytest.approx(secondary_source_point.y())
    finally:
        _close(pane, qapp)


@pytest.mark.parametrize(
    ("primary_size", "secondary_size", "expected_zoom", "relative_zooms"),
    (
        (QSize(320, 240), QSize(640, 480), 20.0, (20.0, 10.0)),
        (QSize(640, 480), QSize(320, 240), 10.0, (10.0, 20.0)),
        (QSize(320, 240), QSize(800, 300), 12.5, (12.5, 10.0)),
        (QSize(800, 300), QSize(320, 240), 10.0, (10.0, 25.0)),
        (QSize(320, 240), QSize(320, 240), 10.0, (10.0, 10.0)),
    ),
)
def test_comparison_wheel_zoom_stops_when_slower_side_reaches_ten_times_native(
    qapp,
    primary_size: QSize,
    secondary_size: QSize,
    expected_zoom: float,
    relative_zooms: tuple[float, float],
) -> None:
    """Bound shared zoom when the last comparison source reaches 1000 percent."""

    pane, primary_id, secondary_id = _comparison_pane(
        qapp,
        primary_size=primary_size,
        secondary_size=secondary_size,
    )
    pane.applySettings(smooth_zoom_enabled=False)
    try:
        pane.setComparisonPair(primary_id, secondary_id)
        pane.setZoomFit()
        qapp.processEvents()

        for _step in range(40):
            _wheel_zoom_in(pane)
        qapp.processEvents()

        assert pane.currentZoom() == pytest.approx(expected_zoom)
        primary_native_zoom = 1.0
        secondary_native_zoom = min(
            secondary_size.width() / primary_size.width(),
            secondary_size.height() / primary_size.height(),
        )
        assert (
            pane.currentZoom() / primary_native_zoom,
            pane.currentZoom() / secondary_native_zoom,
        ) == pytest.approx(relative_zooms)
        assert min(relative_zooms) == pytest.approx(10.0)
    finally:
        _close(pane, qapp)


def test_smooth_comparison_wheel_storm_converges_to_zoom_bound(qapp) -> None:
    """Keep interpolated wheel bursts within the source-relative ceiling."""

    pane, primary_id, secondary_id = _comparison_pane(
        qapp,
        primary_size=QSize(320, 240),
        secondary_size=QSize(640, 480),
    )
    pane.applySettings(
        smooth_zoom_enabled=True,
        smooth_zoom_duration_ms=40,
        smooth_zoom_burst_duration_ms=20,
    )
    try:
        pane.setComparisonPair(primary_id, secondary_id)
        pane.setZoomFit()
        qapp.processEvents()

        for _burst in range(8):
            _wheel_zoom_in(pane, steps=40)
        QTest.qWait(120)

        assert pane.currentZoom() == pytest.approx(20.0)
    finally:
        _close(pane, qapp)


def test_comparison_pair_replacement_reconciles_the_existing_zoom_bound(qapp) -> None:
    """Clamp preserved zoom when a replacement pair reaches 1000 percent sooner."""

    pane, primary_id, larger_id = _comparison_pane(
        qapp,
        primary_size=QSize(320, 240),
        secondary_size=QSize(640, 480),
    )
    equal_size_id = uuid4()
    pane.addImage(
        _image(QSize(320, 240), QColor("green")),
        source_id=equal_size_id,
        label="equal-size",
        select=False,
    )
    pane.applySettings(smooth_zoom_enabled=False)
    try:
        pane.setComparisonPair(primary_id, larger_id)
        pane.applyZoom(1000.0)
        assert pane.currentZoom() == pytest.approx(20.0)

        pane.setComparisonImage(equal_size_id)
        qapp.processEvents()

        assert pane.currentZoom() == pytest.approx(10.0)
    finally:
        _close(pane, qapp)


def _comparison_pane(
    qapp,
    *,
    primary_size: QSize,
    secondary_size: QSize,
) -> tuple[QPane, UUID, UUID]:
    """Mount two catalog sources without selecting either during admission."""

    pane = QPane()
    pane.resize(960, 640)
    pane.show()
    primary_id = uuid4()
    secondary_id = uuid4()
    pane.addImage(
        _image(primary_size, QColor("red")),
        source_id=primary_id,
        label="primary",
        select=False,
    )
    pane.addImage(
        _image(secondary_size, QColor("blue")),
        source_id=secondary_id,
        label="secondary",
        select=False,
    )
    qapp.processEvents()
    return pane, primary_id, secondary_id


def _wheel_zoom_in(pane: QPane, *, steps: int = 1) -> None:
    """Deliver one zoom-in step through the mounted top-level Qt window."""

    window = pane.window()
    window_handle = window.windowHandle()
    assert window_handle is not None
    anchor = QPoint(pane.width() // 2, pane.height() // 2)
    QTest.wheelEvent(
        window_handle,
        pane.mapTo(window, anchor),
        QPoint(0, 120 * steps),
        QPoint(),
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
    )


def _image(size: QSize, color: QColor) -> QImage:
    """Return one opaque detached comparison source."""

    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(color)
    return image


def _quadrant_image(
    size: QSize, colors: tuple[QColor, QColor, QColor, QColor]
) -> QImage:
    """Return a four-region normalized correspondence fixture."""

    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    half_width = size.width() // 2
    half_height = size.height() // 2
    rectangles = (
        QRect(0, 0, half_width, half_height),
        QRect(half_width, 0, size.width() - half_width, half_height),
        QRect(0, half_height, half_width, size.height() - half_height),
        QRect(
            half_width,
            half_height,
            size.width() - half_width,
            size.height() - half_height,
        ),
    )
    for rectangle, color in zip(rectangles, colors, strict=True):
        painter.fillRect(rectangle, color)
    painter.end()
    return image


def _projected_scene_seam(
    plan: SceneRenderPlan,
    *,
    split_position: float,
    orientation: ComparisonOrientation,
) -> QLineF:
    """Project one normalized scene seam through the compared render item."""

    item = plan.render_items[-1]
    bounds = plan.scene_bounds
    placement = item.placement
    source_size = item.source_size
    if orientation is ComparisonOrientation.HORIZONTAL:
        scene_position = bounds.y + split_position * bounds.height
        source_position = (
            (scene_position - placement.y) * source_size.height() / placement.height
        )
        return QLineF(
            item.transform.map(QPointF(0.0, source_position)),
            item.transform.map(QPointF(float(source_size.width()), source_position)),
        )
    scene_position = bounds.x + split_position * bounds.width
    source_position = (
        (scene_position - placement.x) * source_size.width() / placement.width
    )
    return QLineF(
        item.transform.map(QPointF(source_position, 0.0)),
        item.transform.map(QPointF(source_position, float(source_size.height()))),
    )


def _wait_for_pixels(
    qapp,
    pane: QPane,
    points: tuple[QPointF, ...],
    expected: tuple[QColor, ...],
) -> None:
    """Wait for one observable settled frame and assert its sampled regions."""

    timer = QElapsedTimer()
    timer.start()
    actual: tuple[QColor, ...] = ()
    while timer.elapsed() < 2_000:
        qapp.processEvents()
        frame = pane.grab().toImage()
        actual = tuple(
            frame.pixelColor(round(point.x()), round(point.y())) for point in points
        )
        if actual == expected:
            return
    assert actual == expected


def _close(pane: QPane, qapp) -> None:
    """Release one mounted viewer and drain deferred Qt teardown."""

    pane.close()
    pane.deleteLater()
    qapp.processEvents()
