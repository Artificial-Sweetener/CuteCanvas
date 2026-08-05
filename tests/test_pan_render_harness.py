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

"""Tests for differential headless pan-render artifact detection."""

from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from qpane import LayerPresentationStyle

from tools.pan_render_harness import (
    FrameArtifactDetector,
    HeadlessPanHarness,
    coordinate_fingerprint_image,
    random_walk_pans,
)


def test_detector_accepts_identical_frames() -> None:
    """Equal frames should not produce a rendering-artifact report."""
    frame = coordinate_fingerprint_image(QSize(32, 24))

    difference = FrameArtifactDetector().compare(frame, QImage(frame))

    assert difference.detected is False
    assert difference.mismatch_pixels == 0
    assert difference.column_spans == ()


def test_detector_finds_injected_vertical_black_lines() -> None:
    """Full-height black corruption should be reported as exact column spans."""
    expected = coordinate_fingerprint_image(QSize(32, 24))
    actual = QImage(expected)
    painter = QPainter(actual)
    try:
        painter.fillRect(QRect(9, 0, 2, actual.height()), QColor(0, 0, 0, 255))
        painter.fillRect(QRect(21, 0, 1, actual.height()), QColor(0, 0, 0, 255))
    finally:
        painter.end()

    detector = FrameArtifactDetector()
    difference = detector.compare(actual, expected)

    assert difference.detected is True
    assert difference.mismatch_pixels == actual.height() * 3
    assert difference.mismatch_bounds == QRect(9, 0, 13, actual.height())
    assert difference.column_spans == ((9, 10), (21, 21))
    assert difference.max_channel_delta > 0
    assert difference.max_column_coverage == 1.0


def test_detector_honors_channel_tolerance() -> None:
    """Small configured channel variation should not trigger a mismatch."""
    expected = QImage(8, 8, QImage.Format.Format_RGBA8888)
    expected.fill(QColor(100, 100, 100, 255))
    actual = QImage(8, 8, QImage.Format.Format_RGBA8888)
    actual.fill(QColor(102, 98, 101, 255))

    difference = FrameArtifactDetector(channel_tolerance=2).compare(actual, expected)

    assert difference.detected is False


def test_headless_pan_harness_matches_clean_full_redraws(
    qapp,
    tmp_path: Path,
) -> None:
    """Normal incremental pans should match synchronized full-redraw frames."""
    harness = HeadlessPanHarness(
        qapp,
        coordinate_fingerprint_image(QSize(256, 256)),
        viewport_size=QSize(96, 96),
        zoom=1.75,
        artifact_root=tmp_path,
    )
    try:
        failures = harness.run(
            (
                QPointF(7.0, 0.0),
                QPointF(7.5, 4.25),
                QPointF(-3.25, 4.75),
                QPointF(18.75, -12.5),
            )
        )
    finally:
        harness.close()

    assert failures == []
    assert list(tmp_path.iterdir()) == []


def test_headless_pan_harness_checks_only_selected_replay_steps(
    qapp,
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Sparse oracle checkpoints should preserve every incremental pan transition."""
    harness = HeadlessPanHarness(
        qapp,
        coordinate_fingerprint_image(QSize(256, 256)),
        viewport_size=QSize(96, 96),
        zoom=1.75,
        artifact_root=tmp_path,
    )
    oracle_pans: list[QPointF] = []
    original_oracle = harness._capture_full_redraw_reference

    def capture_oracle(buffer_pan: QPointF) -> QImage:
        """Record and delegate one selected clean redraw."""
        oracle_pans.append(QPointF(buffer_pan))
        return original_oracle(buffer_pan)

    monkeypatch.setattr(harness, "_capture_full_redraw_reference", capture_oracle)
    pans = tuple(QPointF(index * 7.25, index * -3.5) for index in range(6))
    try:
        failures = harness.run(
            pans,
            comparison_steps={1, 4},
            direct_navigation=True,
        )
        final_pan = harness._qpane.currentPan()
    finally:
        harness.close()

    assert failures == []
    assert len(oracle_pans) == 2
    assert final_pan == pans[-1]


def test_headless_pan_harness_survives_accumulated_tiled_edge_repairs(
    qapp,
    tmp_path: Path,
) -> None:
    """Repeated high-DPI tile-strip repairs should remain identical to redraws."""
    harness = HeadlessPanHarness(
        qapp,
        coordinate_fingerprint_image(QSize(1024, 1024)),
        viewport_size=QSize(320, 240),
        device_pixel_ratio=1.5,
        artifact_root=tmp_path,
    )
    try:
        failures = harness.run(random_walk_pans(steps=437, seed=819))
    finally:
        harness.close()

    assert failures == []


def test_direct_navigation_survives_accumulated_high_dpi_repairs(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    """Space-style navigation must not retain stale or displaced repair pixels."""
    harness = HeadlessPanHarness(
        qapp,
        coordinate_fingerprint_image(QSize(2048, 2048)),
        viewport_size=QSize(640, 360),
        device_pixel_ratio=1.75,
        zoom=5.0,
        artifact_root=tmp_path,
    )
    pans = random_walk_pans(steps=257, seed=20260726, max_step=180)
    try:
        failures = harness.run(pans, direct_navigation=True)
    finally:
        harness.close()

    assert failures == []


def test_headless_pan_harness_handles_fractionally_aligned_odd_viewport(
    qapp,
    tmp_path: Path,
) -> None:
    """Odd viewport centers and clamp fractions should remain redraw-identical."""
    harness = HeadlessPanHarness(
        qapp,
        coordinate_fingerprint_image(QSize(1024, 1024)),
        viewport_size=QSize(511, 97),
        artifact_root=tmp_path,
    )
    try:
        failures = harness.run(random_walk_pans(steps=150, seed=23, max_step=29))
    finally:
        harness.close()

    assert failures == []


def test_headless_pan_harness_keeps_layer_effect_redraws_exact(
    qapp,
    tmp_path: Path,
) -> None:
    """Effect strip repairs must equal full redraws through abusive viewport motion."""

    def add_effect(canvas) -> None:
        scene = canvas._rendering.presenter.current_scene_descriptor()
        assert scene is not None
        canvas.addLayerPresentationEffect(
            scene.scene_id,
            scene.layers[0].layer_id,
            LayerPresentationStyle.outline(QColor(40, 220, 255), width=2.0),
        )

    harness = HeadlessPanHarness(
        qapp,
        coordinate_fingerprint_image(QSize(1024, 1024)),
        viewport_size=QSize(320, 240),
        zoom=1.0,
        artifact_root=tmp_path,
        configure_qpane=add_effect,
    )
    try:
        failures = harness.run(random_walk_pans(steps=211, seed=991, max_step=37))
    finally:
        harness.close()

    assert failures == []


def test_outer_outline_never_changes_translucent_layer_interior(
    qapp,
    tmp_path: Path,
) -> None:
    """An outer effect must contribute no pixels inside translucent content."""
    image = QImage(96, 96, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    try:
        painter.fillRect(QRect(24, 24, 48, 48), QColor(220, 45, 110, 128))
    finally:
        painter.end()
    harness = HeadlessPanHarness(
        qapp,
        image,
        viewport_size=QSize(96, 96),
        zoom=1.0,
        artifact_root=tmp_path,
    )
    try:
        pane = harness._qpane
        baseline = harness.capture_visible_frame(pane)
        scene = pane._rendering.presenter.current_scene_descriptor()
        assert scene is not None
        effect_id = pane.addLayerPresentationEffect(
            scene.scene_id,
            scene.layers[0].layer_id,
            LayerPresentationStyle.outline(
                QColor(40, 220, 255),
                width=2.0,
                opacity=0.9,
            ),
        )
        harness._settle_widget()
        outlined = harness.capture_visible_frame(pane)

        assert outlined.pixelColor(48, 48) == baseline.pixelColor(48, 48)
        assert outlined.pixelColor(23, 48) != baseline.pixelColor(23, 48)

        assert pane.removeLayerPresentationEffect(effect_id)
        harness._settle_widget()
        assert harness.capture_visible_frame(pane) == baseline
    finally:
        harness.close()
