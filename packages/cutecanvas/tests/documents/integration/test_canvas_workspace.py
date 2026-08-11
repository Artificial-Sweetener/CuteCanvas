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
"""Exercise built-in document presentations through the public workspace."""

from __future__ import annotations

import uuid

import pytest
from cutecanvas import (
    CanvasComparisonOverlayState,
    CanvasComparisonZoomGesture,
    CanvasInspectionGroup,
    CanvasInteractionMode,
    CanvasOverlayState,
    CanvasPresentation,
    CuteCanvas,
    EditorCapability,
)
from cutecanvas.document import CanvasDocument
from cutecanvas.presentation import CanvasWorkspace
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QWidget
from qpane.sdk.execution import create_default_execution_runtime
from qpane.sdk.layout import ResponsiveGridPolicy, ResponsiveGridTopology
from qpane.sdk.types import ComparisonOrientation
from shiboken6 import isValid


def _document() -> tuple[CanvasDocument, tuple]:
    """Create three unrelated native coordinate spaces."""
    document = CanvasDocument()
    compositions = document.resources.compositions
    identifiers = tuple(
        compositions.create_composition(
            QRectF(0.0, 0.0, width, height),
            title=title,
        ).composition_id
        for width, height, title in (
            (640.0, 480.0, "First"),
            (1280.0, 960.0, "Second"),
            (900.0, 1600.0, "Third"),
        )
    )
    return document, identifiers


def test_parent_deletion_closes_workspace_owners_before_qt_children(qapp) -> None:
    """A host may delete its container without manually sequencing children."""
    document, identifiers = _document()
    parent = QWidget()
    validity_at_close: list[bool] = []

    class ObservedWorkspace(CanvasWorkspace):
        """Record whether Qt still owns this workspace during owner shutdown."""

        def _close_owners(self) -> None:
            """Capture native validity before running production cleanup."""
            validity_at_close.append(isValid(self))
            super()._close_owners()

    workspace = ObservedWorkspace(document=document, features=(), parent=parent)
    workspace.setSinglePresentation(identifiers[0])
    qapp.processEvents()

    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()

    assert validity_at_close == [True]
    assert not isValid(workspace)
    document.close()


def test_workspace_switches_presentations_without_mutating_document(qapp) -> None:
    """Single, tabs, grid, and comparison reuse one document content graph."""
    document, identifiers = _document()
    workspace = CanvasWorkspace(document=document, features=())
    try:
        before = document.resources.compositions.snapshot()
        workspace.resize(900, 600)
        workspace.setSinglePresentation(identifiers[0])
        workspace.setTabbedPresentation(identifiers)
        workspace.setGridPresentation(identifiers)
        workspace.setComparisonPresentation(identifiers[0], identifiers[1])
        qapp.processEvents()

        assert workspace.currentCanvas() is not None
        assert all(workspace.canvasFor(value) is not None for value in identifiers)
        assert document.resources.compositions.snapshot() == before
    finally:
        workspace.close()
        document.close()


def test_workspace_shares_but_does_not_close_host_execution_runtime(qapp) -> None:
    """Mount every target on one supplied runtime whose lifetime stays host-owned."""
    document, identifiers = _document()
    runtime = create_default_execution_runtime()
    workspace = CanvasWorkspace(
        document=document,
        features=(),
        execution_runtime=runtime,
    )
    try:
        workspace.setGridPresentation(identifiers)
        qapp.processEvents()
        assert all(workspace.canvasFor(value) is not None for value in identifiers)
    finally:
        workspace.close()
        qapp.processEvents()
        document.close()
    assert not runtime.is_closed
    runtime.shutdown(wait=True)


def test_workspace_presentation_storm_reuses_target_canvases(qapp) -> None:
    """Rapid arrangement changes retain renderers and deterministic activation."""
    document, identifiers = _document()
    workspace = CanvasWorkspace(document=document, features=())
    try:
        workspace.setTabbedPresentation(identifiers)
        initial = tuple(workspace.canvasFor(value) for value in identifiers)
        for _index in range(25):
            workspace.setGridPresentation(identifiers)
            workspace.setComparisonPresentation(identifiers[0], identifiers[1])
            workspace.setTabbedPresentation(identifiers)
        qapp.processEvents()

        assert tuple(workspace.canvasFor(value) for value in identifiers) == initial
        assert workspace.session.active_composition_id == identifiers[0]
        assert workspace.session.presentation.target_ids == identifiers
    finally:
        workspace.close()
        document.close()


def test_workspace_keeps_received_target_renderer_alive_across_reflow(qapp) -> None:
    """A target mounted alone must remain renderable after grid reflow moves it."""
    document, identifiers = _document()
    workspace = CanvasWorkspace(document=document, features=())
    try:
        workspace.resize(900, 600)
        workspace.show()
        workspace.setSinglePresentation(identifiers[0])
        target = workspace.canvasFor(identifiers[0])
        assert target is not None

        workspace.setGridPresentation(identifiers)
        qapp.processEvents()
        workspace.setSinglePresentation(identifiers[0])
        qapp.processEvents()

        assert workspace.canvasFor(identifiers[0]) is target
        assert target.parent() is not None
        assert target.isVisible()
    finally:
        workspace.close()
        document.close()


def test_workspace_keeps_hidden_grid_targets_alive_for_later_reuse(qapp) -> None:
    """Changing grid membership must not delete mounts retained by the workspace."""
    document, identifiers = _document()
    workspace = CanvasWorkspace(document=document, features=())
    try:
        workspace.resize(900, 600)
        workspace.show()
        workspace.setGridPresentation(identifiers)
        initial = tuple(workspace.canvasFor(identifier) for identifier in identifiers)

        workspace.setGridPresentation(identifiers[:1])
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        workspace.setGridPresentation(identifiers)
        qapp.processEvents()

        assert (
            tuple(workspace.canvasFor(identifier) for identifier in identifiers)
            == initial
        )
        assert all(
            canvas is not None and canvas.parent() is not None for canvas in initial
        )
    finally:
        workspace.close()
        document.close()


def test_workspace_first_image_presentation_initializes_a_positive_fit_zoom(
    qapp,
) -> None:
    """Open a rendered image through the workspace's normal composition owner."""
    document = CanvasDocument()
    image = QImage(320, 240, QImage.Format.Format_RGB32)
    image.fill(QColor(180, 20, 40))
    composition_id = document.create_composition_from_image(image)
    workspace = CanvasWorkspace(document=document, features=())
    try:
        workspace.resize(900, 600)
        workspace.show()
        workspace.setSinglePresentation(composition_id)
        qapp.processEvents()

        canvas = workspace.canvasFor(composition_id)
        assert canvas is not None
        assert canvas.currentScene() is not None
        assert canvas.currentZoom() > 0.0
    finally:
        workspace.close()
        document.close()


def test_workspace_grid_publishes_every_deliberate_target_selection(qapp) -> None:
    """Re-entering a grid must republish a tile already active in the session."""
    document, identifiers = _document()
    workspace = CanvasWorkspace(document=document, features=())
    try:
        policy = ResponsiveGridPolicy(
            topology=ResponsiveGridTopology.MAXIMUM_REFERENCE_AREA,
            topology_hysteresis_ratio=1.02,
        )
        workspace.resize(900, 600)
        workspace.show()
        workspace.setGridPresentation(identifiers, policy=policy)
        qapp.processEvents()

        snapshot = workspace.gridSnapshot()
        assert snapshot is not None
        assert snapshot.topology is ResponsiveGridTopology.MAXIMUM_REFERENCE_AREA
        assert snapshot.frame(identifiers[1]) is not None
        activated = QSignalSpy(workspace.targetActivated)

        target = workspace.canvasFor(identifiers[1])
        assert target is not None
        QTest.mouseClick(target, Qt.MouseButton.LeftButton)
        qapp.processEvents()

        assert activated.count() == 1
        assert activated.at(0)[0] == identifiers[1]
        assert workspace.session.active_composition_id == identifiers[1]

        workspace.setSinglePresentation(identifiers[1])
        workspace.setGridPresentation(identifiers)
        qapp.processEvents()
        returned_activated = QSignalSpy(workspace.targetActivated)
        returned_target = workspace.canvasFor(identifiers[1])
        assert returned_target is not None
        QTest.mouseClick(returned_target, Qt.MouseButton.LeftButton)
        qapp.processEvents()

        assert returned_activated.count() == 1
        assert returned_activated.at(0)[0] == identifiers[1]
    finally:
        workspace.close()
        document.close()


def test_workspace_grid_targets_do_not_navigate(qapp) -> None:
    """Grid tiles retain click/drag interaction instead of pan or zoom controls."""

    document, identifiers = _document()
    workspace = CanvasWorkspace(document=document, features=())
    try:
        workspace.resize(900, 600)
        workspace.show()
        workspace.setGridPresentation(identifiers)
        qapp.processEvents()
        target = workspace.canvasFor(identifiers[1])
        assert target is not None
        viewport = target.view().viewport
        zoom_before = viewport.zoom
        pan_before = QPointF(viewport.pan)
        center = QPointF(target.rect().center())

        qapp.sendEvent(
            target,
            QWheelEvent(
                center,
                center,
                QPoint(),
                QPoint(0, 120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.ScrollUpdate,
                False,
            ),
        )
        qapp.sendEvent(
            target,
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                center,
                center,
                center,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        destination = center + QPointF(20.0, 0.0)
        qapp.sendEvent(
            target,
            QMouseEvent(
                QEvent.Type.MouseMove,
                destination,
                destination,
                destination,
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        qapp.sendEvent(
            target,
            QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                destination,
                destination,
                destination,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )

        assert target.getControlMode() == target.CONTROL_MODE_CURSOR
        assert viewport.is_locked() is True
        assert viewport.zoom == zoom_before
        assert viewport.pan == pan_before
    finally:
        workspace.close()
        document.close()


def test_workspace_grid_targets_fit_after_grid_geometry_is_known(qapp) -> None:
    """Grid targets fit their cells before navigation is disabled."""

    document = CanvasDocument()
    image = QImage(640, 480, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("steelblue"))
    identifiers = tuple(
        document.create_composition_from_image(image, title=f"Output {index}")
        for index in range(3)
    )
    workspace = CanvasWorkspace(document=document, features=())
    try:
        workspace.resize(900, 600)
        workspace.show()
        workspace.setGridPresentation(identifiers)
        qapp.processEvents()

        target = workspace.canvasFor(identifiers[0])
        assert target is not None
        viewport_size = target.physicalViewportRect().size()
        assert target.currentZoom() == pytest.approx(
            min(
                viewport_size.width() / image.width(),
                viewport_size.height() / image.height(),
            )
        )
        assert target.view().viewport.is_locked() is True
    finally:
        workspace.close()
        document.close()


def test_workspace_uses_independent_viewports_for_detail_grid_and_comparison(
    qapp,
) -> None:
    """A presentation change must not transfer one target's viewport state."""

    document = CanvasDocument()
    image = QImage(640, 480, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("steelblue"))
    identifiers = tuple(
        document.create_composition_from_image(image, title=f"Output {index}")
        for index in range(3)
    )
    workspace = CanvasWorkspace(document=document, features=())
    try:
        workspace.resize(900, 600)
        workspace.show()
        workspace.setGridPresentation(identifiers)
        qapp.processEvents()
        grid_canvas = workspace.canvasFor(identifiers[0])
        assert grid_canvas is not None
        grid_zoom = grid_canvas.currentZoom()

        workspace.setSinglePresentation(identifiers[0])
        qapp.processEvents()
        detail_canvas = workspace.canvasFor(identifiers[0])
        assert detail_canvas is not None
        assert detail_canvas is not grid_canvas
        detail_canvas.applyZoom(detail_canvas.currentZoom() * 1.5)
        detail_zoom = detail_canvas.currentZoom()
        assert detail_zoom != grid_zoom

        workspace.setGridPresentation(identifiers)
        qapp.processEvents()
        assert workspace.canvasFor(identifiers[0]) is grid_canvas
        assert grid_canvas.currentZoom() == grid_zoom

        workspace.setComparisonPresentation(identifiers[0], identifiers[1])
        qapp.processEvents()
        comparison_pane = workspace.currentCanvas()
        assert comparison_pane is not None
        assert comparison_pane is not detail_canvas
        assert comparison_pane is not grid_canvas
        assert detail_canvas.currentZoom() == detail_zoom
    finally:
        workspace.close()
        document.close()


def test_workspace_links_only_the_active_comparison_viewports(qapp) -> None:
    """Comparison inspection synchronizes its pair without affecting detail state."""

    document = CanvasDocument()
    image = QImage(640, 480, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("steelblue"))
    identifiers = tuple(
        document.create_composition_from_image(image, title=f"Output {index}")
        for index in range(2)
    )
    workspace = CanvasWorkspace(document=document, features=())
    try:
        workspace.resize(900, 600)
        workspace.show()
        workspace.setSinglePresentation(identifiers[0])
        qapp.processEvents()
        detail_canvas = workspace.canvasFor(identifiers[0])
        assert detail_canvas is not None
        detail_canvas.applyZoom(detail_canvas.currentZoom() * 1.5)
        detail_zoom = detail_canvas.currentZoom()

        workspace.setComparisonInspectionGroups(
            (CanvasInspectionGroup(uuid.uuid4(), identifiers),)
        )
        workspace.setComparisonPresentation(identifiers[0], identifiers[1])
        qapp.processEvents()
        pane = workspace.currentCanvas()
        assert pane is not None
        assert pane is not detail_canvas
        assert tuple(group.members for group in pane.linkedImageGroups()) == (
            identifiers,
        )
        pane.applyZoom(pane.currentZoom() * 1.5)
        qapp.processEvents()

        assert detail_canvas.currentZoom() == detail_zoom
    finally:
        workspace.close()
        document.close()


def test_workspace_ignores_identical_comparison_inspection_groups(
    qapp,
    monkeypatch,
) -> None:
    """Avoid capturing live inspection when the comparison groups are unchanged."""

    document = CanvasDocument()
    image = QImage(640, 480, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("steelblue"))
    identifiers = tuple(
        document.create_composition_from_image(image, title=f"Output {index}")
        for index in range(2)
    )
    workspace = CanvasWorkspace(document=document, features=())
    group = CanvasInspectionGroup(uuid.uuid4(), identifiers)
    try:
        workspace.resize(900, 600)
        workspace.setComparisonInspectionGroups((group,))
        workspace.setComparisonPresentation(identifiers[0], identifiers[1])
        workspace.show()
        qapp.processEvents()
        pane = workspace.currentCanvas()
        assert pane is not None
        captures: list[bool] = []

        def capture_catalog_inspection(_pane) -> bool:
            """Record one comparison-surface inspection capture."""

            captures.append(True)
            return True

        monkeypatch.setattr(
            type(pane),
            "captureCatalogInspection",
            capture_catalog_inspection,
        )

        workspace.setComparisonInspectionGroups((group,))
        assert captures == []

        workspace.setComparisonInspectionGroups(
            (CanvasInspectionGroup(uuid.uuid4(), identifiers),)
        )
        assert captures == [True]
    finally:
        workspace.close()
        document.close()


def test_workspace_publishes_only_requested_initial_comparison_state(qapp) -> None:
    """Hide native setup transitions from the host presentation signal."""

    document = CanvasDocument()
    image = QImage(640, 480, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("steelblue"))
    identifiers = tuple(
        document.create_composition_from_image(image, title=f"Output {index}")
        for index in range(2)
    )
    workspace = CanvasWorkspace(document=document, features=())
    observed: list[CanvasPresentation] = []
    workspace.presentationChanged.connect(observed.append)
    try:
        workspace.resize(900, 600)
        workspace.setComparisonPresentation(
            identifiers[0],
            identifiers[1],
            split_position=0.25,
        )
        workspace.show()
        qapp.processEvents()

        assert len(observed) == 1
        assert observed[0].comparison is not None
        assert observed[0].comparison.split_position == 0.25
    finally:
        workspace.close()
        document.close()


def test_workspace_restores_linked_inspection_for_a_first_time_detail_target(
    qapp,
) -> None:
    """A newly mounted linked tab must adopt the established shared viewport."""

    document = CanvasDocument()
    first_image = QImage(640, 480, QImage.Format.Format_ARGB32_Premultiplied)
    second_image = QImage(1280, 960, QImage.Format.Format_ARGB32_Premultiplied)
    first_image.fill(QColor("red"))
    second_image.fill(QColor("blue"))
    first_id = document.create_composition_from_image(first_image, title="First")
    second_id = document.create_composition_from_image(second_image, title="Second")
    workspace = CanvasWorkspace(document=document, features=())
    try:
        workspace.resize(900, 600)
        workspace.show()
        workspace.setInspectionGroups(
            (CanvasInspectionGroup(uuid.uuid4(), (first_id, second_id)),)
        )
        workspace.setSinglePresentation(first_id)
        qapp.processEvents()
        first = workspace.canvasFor(first_id)
        assert first is not None
        first.applyZoom(first.currentZoom() * 1.5)
        qapp.processEvents()

        workspace.setSinglePresentation(second_id)
        qapp.processEvents()
        second = workspace.canvasFor(second_id)
        assert second is not None
        assert second.currentZoom() == pytest.approx(first.currentZoom() / 2.0)
    finally:
        workspace.close()
        document.close()


def test_workspace_preserves_host_owned_inspection_groups_across_presentations(
    qapp,
) -> None:
    """Presentation changes never replace a host-selected linked inspection group."""
    document, identifiers = _document()
    workspace = CanvasWorkspace(document=document, features=())
    group = CanvasInspectionGroup(uuid.uuid4(), identifiers)
    try:
        workspace.setInspectionGroups((group,))
        workspace.setTabbedPresentation(identifiers)
        workspace.setGridPresentation(identifiers)
        workspace.setComparisonPresentation(identifiers[0], identifiers[1])
        qapp.processEvents()

        groups = workspace.session.inspection.groups()
        assert len(groups) == 1
        assert groups[0].group_id == group.group_id
        assert groups[0].members == group.members
    finally:
        workspace.close()
        document.close()


def test_workspace_retires_target_renderer_after_composition_removal(qapp) -> None:
    """Removing a document composition releases its retained workspace renderer."""
    document, identifiers = _document()
    workspace = CanvasWorkspace(document=document, features=())
    retired_id = identifiers[1]
    try:
        workspace.setGridPresentation(identifiers)
        retired_canvas = workspace.canvasFor(retired_id)
        assert retired_canvas is not None

        assert document.remove_composition(retired_id)
        qapp.processEvents()

        assert workspace.canvasFor(retired_id) is None
        assert workspace.session.inspection.group_id_for(retired_id) is None
    finally:
        workspace.close()
        document.close()


def test_workspace_interaction_profiles_cover_current_and_future_views(qapp) -> None:
    """Inspection is read-only until the host enables an authoring profile."""
    document, identifiers = _document()
    workspace = CanvasWorkspace(document=document, features=("mask",))
    try:
        workspace.setSinglePresentation(identifiers[0])
        first = workspace.canvasFor(identifiers[0])
        assert first is not None
        assert first.interactionMode() is CanvasInteractionMode.READ_ONLY
        assert EditorCapability.EDIT_PIXELS not in first.editorPolicy().capabilities

        workspace.setInteractionMode(CanvasInteractionMode.MASK_AUTHORING)
        workspace.setGridPresentation(identifiers)
        assert all(
            workspace.canvasFor(identifier).interactionMode()
            is CanvasInteractionMode.MASK_AUTHORING
            for identifier in identifiers
        )
        assert all(
            EditorCapability.PAINT
            in workspace.canvasFor(identifier).editorPolicy().capabilities
            for identifier in identifiers
        )

        workspace.setInteractionMode(CanvasInteractionMode.FULL_EDITOR)
        assert all(
            EditorCapability.MANAGE_LAYERS
            in workspace.canvasFor(identifier).editorPolicy().capabilities
            for identifier in identifiers
        )
    finally:
        workspace.close()
        document.close()


def test_comparison_orientation_updates_one_native_scene_without_widget_masks(
    qapp,
) -> None:
    """Orientation changes retain QPane's scene and avoid widget clipping surfaces."""
    document, identifiers = _document()
    workspace = CanvasWorkspace(document=document, features=())
    workspace.resize(900, 600)
    try:
        workspace.setComparisonPresentation(
            identifiers[0],
            identifiers[1],
            orientation=ComparisonOrientation.VERTICAL,
        )
        workspace.show()
        qapp.processEvents()
        pane = workspace.currentCanvas()
        assert pane is not None
        assert pane.mask().isEmpty()
        assert pane.comparisonState().orientation is ComparisonOrientation.VERTICAL

        workspace.setComparisonPresentation(
            identifiers[0],
            identifiers[1],
            orientation=ComparisonOrientation.HORIZONTAL,
        )
        qapp.processEvents()
        assert workspace.currentCanvas() is pane
        assert pane.mask().isEmpty()
        assert pane.comparisonState().orientation is ComparisonOrientation.HORIZONTAL
    finally:
        workspace.close()
        document.close()


def test_canvas_overlay_state_hides_native_viewport_names(qapp) -> None:
    """Detail overlay hosts receive CuteCanvas state rather than QPane state."""

    document = CanvasDocument()
    image = QImage(64, 48, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("red"))
    composition_id = document.create_composition_from_image(image)
    canvas = CuteCanvas(document=document, features=())
    observed: list[CanvasOverlayState] = []
    try:
        canvas.resize(900, 600)
        canvas.openComposition(composition_id)
        canvas.show()
        qapp.processEvents()
        canvas.registerCanvasOverlay(
            "test-canvas-overlay",
            lambda _painter, state: observed.append(state),
        )
        canvas.repaint()
        qapp.processEvents()
        canvas.grab()

        assert observed
        state = observed[-1]
        assert state.viewport == canvas.rect()
        assert state.physical_viewport.width() > 0.0
        assert state.physical_viewport.height() > 0.0
        assert not hasattr(state, "qpane_rect")

        canvas.unregisterCanvasOverlay("test-canvas-overlay")
        observed.clear()
        canvas.repaint()
        qapp.processEvents()
        canvas.grab()
        assert observed == []
    finally:
        canvas.close()
        document.close()


def test_workspace_comparison_overlay_never_exposes_its_native_renderer(qapp) -> None:
    """Host comparison chrome should receive CuteCanvas state and paint in place."""

    document, identifiers = _document()
    workspace = CanvasWorkspace(document=document, features=())
    observed: list[CanvasComparisonOverlayState] = []
    try:
        workspace.registerComparisonOverlay(
            "test-comparison-overlay",
            lambda _painter, state: observed.append(state),
        )
        workspace.resize(900, 600)
        workspace.setComparisonPresentation(identifiers[0], identifiers[1])
        workspace.show()
        qapp.processEvents()
        surface = workspace.currentCanvas()
        assert surface is not None
        surface.grab()

        assert observed
        state = observed[-1]
        assert state.comparison.primary_id == identifiers[0]
        assert state.comparison.secondary_id == identifiers[1]
        assert state.divider.enabled is True
        assert state.divider.visible_segment is not None
        assert state.primary_scale.horizontal > 0.0
        assert state.primary_scale.vertical > 0.0
        assert state.secondary_scale.horizontal > 0.0
        assert state.secondary_scale.vertical > 0.0

        gestures = QSignalSpy(workspace.comparisonZoomGesture)
        pointer = QPointF(surface.rect().center())
        qapp.sendEvent(
            surface,
            QWheelEvent(
                pointer,
                pointer,
                QPoint(),
                QPoint(0, 120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.ScrollUpdate,
                False,
            ),
        )
        surface.applyZoom(surface.currentZoom() * 1.1)
        qapp.processEvents()
        assert gestures.count() == 1
        gesture = gestures.at(0)[0]
        assert isinstance(gesture, CanvasComparisonZoomGesture)
        assert gesture.position == pointer
        assert gesture.zoom > 0.0

        workspace.unregisterComparisonOverlay("test-comparison-overlay")
        observed.clear()
        surface.grab()
        assert observed == []
    finally:
        workspace.close()
        document.close()
