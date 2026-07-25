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
"""Exercise built-in document presentations through the public workspace."""

from __future__ import annotations

from cutecanvas import CanvasInteractionMode, EditorCapability
from cutecanvas.document import CanvasDocument
from cutecanvas.presentation import CanvasWorkspace
from PySide6.QtCore import QRectF
from qpane.sdk.execution import create_default_execution_runtime
from qpane.sdk.types import ComparisonOrientation


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
        workspace.setTabbedPresentation(identifiers, linked=True)
        initial = tuple(workspace.canvasFor(value) for value in identifiers)
        for _index in range(25):
            workspace.setGridPresentation(identifiers)
            workspace.setComparisonPresentation(identifiers[0], identifiers[1])
            workspace.setTabbedPresentation(identifiers, linked=True)
        qapp.processEvents()

        assert tuple(workspace.canvasFor(value) for value in identifiers) == initial
        assert workspace.session.active_composition_id == identifiers[0]
        assert workspace.session.presentation.target_ids == identifiers
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


def test_comparison_orientation_rebuilds_only_its_narrow_divider_surface(qapp) -> None:
    """Orientation changes preserve canvases and never cover their input surface."""
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
        vertical = workspace._surface
        assert vertical is not None
        assert vertical._overlay.width() == 17
        assert vertical._overlay.height() == vertical.height()
        canvases = (
            workspace.canvasFor(identifiers[0]),
            workspace.canvasFor(identifiers[1]),
        )

        workspace.setComparisonPresentation(
            identifiers[0],
            identifiers[1],
            orientation=ComparisonOrientation.HORIZONTAL,
        )
        qapp.processEvents()
        horizontal = workspace._surface
        assert horizontal is not None
        assert horizontal is not vertical
        assert horizontal._overlay.height() == 17
        assert horizontal._overlay.width() == horizontal.width()
        assert (
            workspace.canvasFor(identifiers[0]),
            workspace.canvasFor(identifiers[1]),
        ) == canvases
    finally:
        workspace.close()
        document.close()
