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
"""Mounted catalog, comparison, and navigation contracts for QPane."""

from __future__ import annotations

from math import isclose
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

from qpane import (
    ComparisonOrientation,
    InspectionStateStore,
    LinkedGroup,
    QPane,
    RenderLayer,
    RenderScene,
    ViewerCatalogEntry,
)
from tests.harness.timing import INTERACTIVE_PERFORMANCE, interaction_clock


def _image(width: int, height: int, color: QColor) -> QImage:
    """Create one opaque catalog fixture outside timed interaction work."""
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(color)
    return image


def _mounted_catalog(qapp) -> tuple[QPane, tuple[ViewerCatalogEntry, ...]]:
    """Mount a viewer containing three distinct reusable sources."""
    pane = QPane()
    pane.resize(800, 600)
    pane.show()
    entries = (
        pane.addImage(_image(1200, 800, QColor("red")), label="Red"),
        pane.addImage(_image(800, 1200, QColor("green")), label="Green"),
        pane.addImage(_image(1600, 900, QColor("blue")), label="Blue"),
    )
    qapp.processEvents()
    return pane, entries


def test_catalog_navigation_can_use_host_owned_linked_inspection(qapp) -> None:
    """A host can retain one native comparison viewport independently of a widget."""

    inspection = InspectionStateStore()
    primary_id = uuid4()
    secondary_id = uuid4()
    pane = QPane(inspection=inspection)
    pane.resize(800, 600)
    pane.show()
    try:
        pane.addImage(
            _image(1200, 800, QColor("red")),
            label="Primary",
            source_id=primary_id,
        )
        pane.addImage(
            _image(1200, 800, QColor("blue")),
            label="Secondary",
            source_id=secondary_id,
            select=False,
        )
        pane.setLinkedImageGroups((LinkedGroup(uuid4(), (primary_id, secondary_id)),))
        pane.setComparisonImage(secondary_id)
        qapp.processEvents()

        pane.applyZoom(pane.currentZoom() * 1.5)
        assert pane.selectCatalogImage(secondary_id)

        assert inspection.groups() == pane.linkedImageGroups()
        assert inspection.state_for(secondary_id) is not None
    finally:
        pane.close()
        pane.deleteLater()


def test_catalog_navigation_reuses_sources_and_repairs_removal(qapp) -> None:
    """Catalog selection drives SDK scenes and current removal is deterministic."""
    pane, entries = _mounted_catalog(qapp)
    selected: list[ViewerCatalogEntry | None] = []
    invalidated: list[tuple[object, ...]] = []
    pane.catalogSelectionChanged.connect(selected.append)
    pane.catalog().resourcesInvalidated.connect(invalidated.append)

    assert pane.catalog().current == entries[-1]
    assert pane.scene() is not None
    assert pane.scene().layers[0].source is entries[-1].source
    assert pane.selectPreviousImage()
    assert pane.catalog().current == entries[1]
    assert pane.scene() is not None
    assert pane.scene().layers[0].source is entries[1].source

    removed = pane.removeCatalogImage(entries[1].entry_id)

    assert removed is entries[1]
    assert pane.catalog().entries == (entries[0], entries[2])
    assert pane.catalog().current is entries[2]
    assert selected[-1] is entries[2]
    assert pane.scene() is not None
    assert pane.scene().layers[0].source is entries[2].source
    assert invalidated == [(entries[1].source,)]
    pane.close()
    pane.deleteLater()


def test_current_raster_copy_and_path_follow_presented_scene(qapp, tmp_path) -> None:
    """Base-raster helpers follow catalog, SDK, and blank presentation state."""
    pane = QPane()
    path = tmp_path / "current.png"
    image = _image(320, 180, QColor("cyan"))
    entry = pane.addImage(image, label="Current", path=path)

    assert pane.currentImage is not None
    assert pane.currentImage.cacheKey() == image.cacheKey()
    assert pane.currentImagePath == path
    assert pane.copyCurrentImageToClipboard()
    copied = qapp.clipboard().image()
    assert copied.size() == image.size()
    assert copied.pixelColor(0, 0) == image.pixelColor(0, 0)

    pane.setScene(RenderScene.from_size(entry.size, (RenderLayer(entry.source),)))
    assert pane.currentImagePath == path
    pane.clear()
    assert pane.currentImage is None
    assert pane.currentImagePath is None
    assert not pane.copyCurrentImageToClipboard()
    pane.close()
    pane.deleteLater()


def test_reselecting_current_catalog_image_restores_catalog_presentation(qapp) -> None:
    """Activating the current row exits an unrelated explicit SDK scene."""
    pane, entries = _mounted_catalog(qapp)
    current = entries[-1]
    replacement = RenderScene.from_size(
        entries[0].size,
        (RenderLayer(entries[0].source),),
    )
    pane.setScene(replacement)
    assert pane.scene() is replacement

    assert pane.selectCatalogImage(current.entry_id)
    assert pane.scene() is not None
    assert pane.scene().layers[0].source is current.source
    pane.close()
    pane.deleteLater()


def test_catalog_restores_independent_and_linked_view_states(qapp) -> None:
    """Catalog swaps preserve per-image views and deliberately linked views."""
    pane, entries = _mounted_catalog(qapp)
    pane.selectCatalogImage(entries[0].entry_id)
    pane.applyZoom(1.75)
    pane.setPan(QPointF(-110.0, 65.0))
    first_zoom = pane.currentZoom()
    first_pan = pane.currentPan()

    pane.selectCatalogImage(entries[1].entry_id)
    pane.applyZoom(0.85)
    pane.setPan(QPointF(25.0, -40.0))
    pane.selectCatalogImage(entries[0].entry_id)

    assert isclose(pane.currentZoom(), first_zoom)
    assert pane.currentPan() == first_pan

    pane.setAllImagesLinked(True)
    pane.applyZoom(1.2)
    pane.setPan(QPointF(-30.0, 20.0))
    linked_zoom = pane.currentZoom()
    linked_pan = pane.currentPan()
    pane.selectCatalogImage(entries[2].entry_id)

    assert len(pane.linkedImageGroups()) == 1
    assert isclose(
        pane.currentZoom(),
        linked_zoom * entries[0].size.width() / entries[2].size.width(),
    )
    assert isclose(
        pane.currentPan().x(),
        linked_pan.x(),
    )
    assert isclose(
        pane.currentPan().y(),
        (
            linked_pan.y()
            * entries[2].size.height()
            * pane.currentZoom()
            / (entries[0].size.height() * linked_zoom)
        ),
    )
    pane.close()
    pane.deleteLater()


def test_catalog_neighbor_prefetch_is_bounded_and_observable(qapp) -> None:
    """Viewer navigation exposes bounded speculative pyramid work."""
    pane, entries = _mounted_catalog(qapp)
    pane.selectCatalogImage(entries[0].entry_id)
    qapp.processEvents()

    state = pane.catalogPrefetchState()

    assert state.scheduled >= state.completed
    assert state.pending <= 2
    assert "swap" in pane.diagnosticsDomains()
    pane.applySettings(cache={"prefetch": {"pyramids": 0}})
    assert pane.catalogPrefetchState().pending == 0
    pane.close()
    pane.deleteLater()


def test_placeholder_policy_yields_to_content_and_explicit_scenes(qapp) -> None:
    """Empty-catalog placeholders lock only their own active presentation."""
    pane = QPane()
    pane.resize(800, 600)
    pane.show()
    placeholder = _image(320, 180, QColor("gray"))
    pane.setPlaceholderImage(placeholder)
    qapp.processEvents()

    assert pane.placeholderState().active
    assert pane.panZoomLocked()
    assert pane.scene() is not None
    assert pane.scene().layers[0].role == "placeholder"

    content = pane.addImage(
        _image(640, 480, QColor("magenta")),
        label="Content",
    )
    qapp.processEvents()
    assert not pane.placeholderState().active
    assert not pane.panZoomLocked()
    assert pane.scene() is not None
    assert pane.scene().layers[0].source is content.source

    pane.clearCatalog()
    qapp.processEvents()
    assert pane.placeholderState().active
    pane.setScene(RenderScene.from_size(content.size, (RenderLayer(content.source),)))
    assert not pane.placeholderState().active
    assert not pane.panZoomLocked()
    pane.close()
    pane.deleteLater()


def test_placeholder_config_decode_rejects_stale_worker_results(
    qapp,
    tmp_path: Path,
) -> None:
    """Rapid placeholder path changes present only the latest async decode."""
    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    assert _image(900, 500, QColor("red")).save(str(first_path))
    assert _image(420, 240, QColor("blue")).save(str(second_path))
    pane = QPane()
    pane.resize(800, 600)
    pane.show()

    pane.applySettings(placeholder={"source": str(first_path)})
    pane.applySettings(
        placeholder={
            "source": str(second_path),
            "panzoom_enabled": True,
        }
    )
    for _attempt in range(100):
        qapp.processEvents()
        if not pane.placeholderState().loading:
            break
        QTest.qWait(5)

    state = pane.placeholderState()
    assert state.source_path == second_path
    assert state.error is None
    assert state.active
    assert not pane.panZoomLocked()
    assert pane.scene() is not None
    assert pane.scene().canvas.size().toSize() == QSize(420, 240)
    pane.close()
    pane.deleteLater()


def test_comparison_divider_drag_is_qpane_owned_and_preserves_view(qapp) -> None:
    """The built-in divider updates clips without resetting pan or zoom."""
    pane, _entries = _mounted_catalog(qapp)
    pane.setZoom1To1()
    pane.setPan(QPointF(-130.0, -90.0))
    assert pane.compareWithNextImage()
    qapp.processEvents()
    before_zoom = pane.currentZoom()
    before_pan = pane.currentPan()
    divider = pane.comparisonDividerState()
    assert divider.visible_segment is not None
    midpoint = divider.visible_segment.pointAt(0.5).toPoint()

    QTest.mousePress(pane, Qt.MouseButton.LeftButton, pos=midpoint)
    QTest.mouseMove(pane, midpoint + QPoint(80, 0), delay=0)
    QTest.mouseRelease(
        pane,
        Qt.MouseButton.LeftButton,
        pos=midpoint + QPoint(80, 0),
    )
    qapp.processEvents()

    state = pane.comparisonState()
    assert state.enabled
    assert state.split_position > 0.5
    assert pane.currentZoom() == before_zoom
    assert pane.currentPan() == before_pan
    assert pane.comparisonDividerState().dragging is False
    pane.close()
    pane.deleteLater()


def test_middle_mouse_summons_and_drags_comparison_divider(qapp) -> None:
    """Call either divider orientation to the middle-button pointer and drag it."""

    pane, _entries = _mounted_catalog(qapp)
    assert pane.compareWithNextImage()
    qapp.processEvents()
    before_zoom = pane.currentZoom()
    before_pan = pane.currentPan()
    cases = (
        (
            ComparisonOrientation.VERTICAL,
            QPoint(173, 211),
            QPoint(641, 389),
        ),
        (
            ComparisonOrientation.HORIZONTAL,
            QPoint(229, 137),
            QPoint(577, 481),
        ),
    )
    for orientation, called_position, dragged_position in cases:
        pane.setComparisonSplit(0.5, orientation)

        QTest.mousePress(
            pane,
            Qt.MouseButton.MiddleButton,
            pos=called_position,
        )
        qapp.processEvents()
        called = pane.comparisonDividerState()
        assert called.dragging is True
        assert called.visible_segment is not None
        called_coordinate = (
            called.visible_segment.y1()
            if orientation is ComparisonOrientation.HORIZONTAL
            else called.visible_segment.x1()
        )
        expected_called_coordinate = (
            called_position.y()
            if orientation is ComparisonOrientation.HORIZONTAL
            else called_position.x()
        )
        assert isclose(called_coordinate, expected_called_coordinate, abs_tol=1.0)

        QTest.mouseMove(pane, dragged_position, delay=0)
        qapp.processEvents()
        dragged = pane.comparisonDividerState()
        assert dragged.dragging is True
        assert dragged.visible_segment is not None
        dragged_coordinate = (
            dragged.visible_segment.y1()
            if orientation is ComparisonOrientation.HORIZONTAL
            else dragged.visible_segment.x1()
        )
        expected_dragged_coordinate = (
            dragged_position.y()
            if orientation is ComparisonOrientation.HORIZONTAL
            else dragged_position.x()
        )
        assert isclose(dragged_coordinate, expected_dragged_coordinate, abs_tol=1.0)

        QTest.mouseRelease(
            pane,
            Qt.MouseButton.MiddleButton,
            pos=dragged_position,
        )
        qapp.processEvents()
        assert pane.comparisonDividerState().dragging is False

    pane.setComparisonDividerInteractive(False)
    disabled_state = pane.comparisonState()
    QTest.mousePress(
        pane,
        Qt.MouseButton.MiddleButton,
        pos=QPoint(101, 101),
    )
    QTest.mouseMove(pane, QPoint(701, 501), delay=0)
    QTest.mouseRelease(
        pane,
        Qt.MouseButton.MiddleButton,
        pos=QPoint(701, 501),
    )
    qapp.processEvents()
    assert pane.comparisonState() == disabled_state
    assert pane.comparisonDividerState().dragging is False
    assert pane.currentZoom() == before_zoom
    assert pane.currentPan() == before_pan
    pane.close()
    pane.deleteLater()


@INTERACTIVE_PERFORMANCE
def test_catalog_comparison_abuse_stays_synchronous_and_coherent(qapp) -> None:
    """Rapid selection, split, orientation, and removal never leave stale scenes."""
    pane, entries = _mounted_catalog(qapp)
    started = interaction_clock()
    for index in range(240):
        pane.selectCatalogImage(entries[index % len(entries)].entry_id)
        pane.compareWithNextImage()
        pane.setComparisonSplit(
            (index % 101) / 100.0,
            (
                ComparisonOrientation.VERTICAL
                if index % 2
                else ComparisonOrientation.HORIZONTAL
            ),
        )
        if index % 7 == 0:
            pane.clearComparison()
    elapsed_ms = (interaction_clock() - started) * 1000.0
    qapp.processEvents()

    current = pane.catalog().current
    scene = pane.scene()
    assert current is not None
    assert scene is not None
    assert scene.layers[0].source is current.source
    state = pane.comparisonState()
    assert len(scene.layers) == (2 if state.enabled else 1)
    assert elapsed_ms < 350.0

    pane.clearCatalog()
    qapp.processEvents()
    assert pane.scene() is None
    assert pane.catalog().current is None
    assert not pane.comparisonState().enabled
    pane.close()
    pane.deleteLater()
