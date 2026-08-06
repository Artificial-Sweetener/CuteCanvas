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
"""Verify stable document subjects and host MIME routing."""

from __future__ import annotations

from dataclasses import dataclass

from cutecanvas import CuteCanvas
from cutecanvas.document import CanvasContentKind, CanvasDocument
from cutecanvas.presentation import CanvasWorkspace
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QContextMenuEvent, QImage, QMouseEvent
from PySide6.QtTest import QSignalSpy


@dataclass
class _Cancellation:
    """Record cancellation of one deferred host payload."""

    cancelled: bool = False

    def cancel(self) -> None:
        """Mark the host operation cancelled."""
        self.cancelled = True


class _Provider:
    """Capture stable subjects without starting a native drag."""

    def __init__(self) -> None:
        """Initialize request and cancellation storage."""
        self.subjects = []
        self.cancellations = []

    def materialize(self, subject, _complete):
        """Retain the subject as if companion-file work were pending."""
        self.subjects.append(subject)
        cancellation = _Cancellation()
        self.cancellations.append(cancellation)
        return cancellation


class _FailingProvider:
    """Complete one outbound MIME request with a host materialization failure."""

    def materialize(self, _subject, complete):
        """Report a deterministic failure without starting a native drag."""
        complete(None, RuntimeError("artifact unavailable"))
        return _Cancellation()


def _image() -> QImage:
    """Return a small opaque seed image."""
    image = QImage(24, 16, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor("steelblue"))
    return image


def test_document_content_reference_detects_layer_revision_change() -> None:
    """A stable identity remains resolvable while observed revisions advance."""
    document = CanvasDocument()
    try:
        composition_id = document.create_composition_from_image(_image())
        layer = document.snapshot().compositions[composition_id].layers[0]
        reference = document.content_reference(
            composition_id,
            layer_id=layer.layer_id,
        )
        assert reference.kind is CanvasContentKind.LAYER

        document.resources.compositions.layers.update_presentation(
            composition_id,
            layer.layer_id,
            opacity=0.5,
        )
        resolved = document.resolve_content(reference)

        assert resolved.stale
        assert resolved.current.layer_id == reference.layer_id
        assert resolved.current.instance_revision > reference.instance_revision
    finally:
        document.close()


def test_canvas_default_drag_subject_is_active_composition(qapp) -> None:
    """Single-view inspection delegates MIME choice to the host provider."""
    document = CanvasDocument()
    composition_id = document.create_composition_from_image(_image(), title="Output")
    canvas = CuteCanvas(document=document, features=())
    provider = _Provider()
    try:
        canvas.openComposition(composition_id)
        canvas.setOutboundMimeProvider(provider)
        canvas.interaction.handle_drag_start_request(None)

        assert provider.subjects[0].target_id == composition_id
        assert provider.subjects[0].subject_id == document.content_reference(
            composition_id
        )
        canvas.clearOutboundMimeProvider()
        assert provider.cancellations[0].cancelled
    finally:
        canvas.close()
        document.close()


def test_workspace_mime_policy_reaches_future_grid_targets(qapp) -> None:
    """One host policy naturally covers single, tabbed, and grid views."""
    document = CanvasDocument()
    identifiers = tuple(
        document.create_composition_from_image(_image(), title=f"Output {index}")
        for index in range(3)
    )
    workspace = CanvasWorkspace(document=document, features=())
    provider = _Provider()
    try:
        workspace.setOutboundMimeProvider(provider)
        workspace.setGridPresentation(identifiers)
        canvas = workspace.canvasFor(identifiers[2])
        assert canvas is not None
        canvas.interaction.handle_drag_start_request(None)

        assert provider.subjects[0].target_id == identifiers[2]
    finally:
        workspace.close()
        document.close()


def test_workspace_grid_pointer_gesture_starts_drag_out(qapp) -> None:
    """A grid drag exports its target without activating it as a click."""
    document = CanvasDocument()
    identifiers = tuple(
        document.create_composition_from_image(_image(), title=f"Output {index}")
        for index in range(2)
    )
    workspace = CanvasWorkspace(document=document, features=())
    provider = _Provider()
    try:
        workspace.resize(900, 600)
        workspace.show()
        workspace.setOutboundMimeProvider(provider)
        workspace.setGridPresentation(identifiers)
        qapp.processEvents()
        canvas = workspace.canvasFor(identifiers[1])
        assert canvas is not None
        activations = QSignalSpy(workspace.targetActivated)
        active_before = workspace.session.active_composition_id
        origin = QPointF(canvas.rect().center())
        destination = origin + QPointF(20.0, 0.0)

        qapp.sendEvent(
            canvas,
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                origin,
                origin,
                origin,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        qapp.sendEvent(
            canvas,
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
            canvas,
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

        assert provider.subjects[0].target_id == identifiers[1]
        assert activations.count() == 0
        assert workspace.session.active_composition_id == active_before
    finally:
        workspace.close()
        document.close()


def test_workspace_forwards_drag_failure_with_captured_content_subject(qapp) -> None:
    """A host receives failure context without inspecting target canvas topology."""
    document = CanvasDocument()
    composition_id = document.create_composition_from_image(_image(), title="Output")
    workspace = CanvasWorkspace(document=document, features=())
    try:
        workspace.setOutboundMimeProvider(_FailingProvider())
        workspace.setGridPresentation((composition_id,))
        canvas = workspace.canvasFor(composition_id)
        assert canvas is not None
        failures = QSignalSpy(workspace.outboundDragFailed)

        canvas.interaction.handle_drag_start_request(None)
        qapp.processEvents()

        assert failures.count() == 1
        subject, message = failures.at(0)
        assert subject.target_id == composition_id
        assert subject.subject_id == document.content_reference(composition_id)
        assert message == "artifact unavailable"
    finally:
        workspace.close()
        document.close()


def test_workspace_forwards_context_subject_without_changing_activation(qapp) -> None:
    """A context request identifies the clicked grid target without activation."""
    document = CanvasDocument()
    identifiers = tuple(
        document.create_composition_from_image(_image(), title=f"Output {index}")
        for index in range(2)
    )
    workspace = CanvasWorkspace(document=document, features=())
    try:
        workspace.setGridPresentation(identifiers)
        target = workspace.canvasFor(identifiers[1])
        assert target is not None
        requests = QSignalSpy(workspace.contentContextRequested)
        before = workspace.session.active_composition_id

        event = QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse,
            QPoint(4, 4),
            QPoint(24, 28),
        )
        qapp.sendEvent(target, event)

        assert requests.count() == 1
        subject, global_position = requests.at(0)
        assert subject.target_id == identifiers[1]
        assert global_position == QPoint(24, 28)
        assert workspace.session.active_composition_id == before
    finally:
        workspace.close()
        document.close()
