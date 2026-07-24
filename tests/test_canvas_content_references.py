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
"""Verify stable document subjects and host MIME routing."""

from __future__ import annotations

from dataclasses import dataclass

from cutecanvas import CuteCanvas
from cutecanvas.document import CanvasContentKind, CanvasDocument
from cutecanvas.presentation import CanvasWorkspace
from PySide6.QtGui import QColor, QImage


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
