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
"""Mounted adversarial document-presentation and linked-inspection workflows."""

from __future__ import annotations

from cutecanvas.document import CanvasDocument
from cutecanvas.presentation import CanvasWorkspace
from PySide6.QtCore import QPointF, QRectF, QSize
from PySide6.QtGui import QColor, QImage
from qpane.sdk.rendering import ViewportZoomMode

from tests.harness.timing import (
    INTERACTIVE_PERFORMANCE,
    average_interaction_latency_ms,
)

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
        workspace.setTabbedPresentation(identifiers, linked=True)
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
                workspace.setTabbedPresentation(identifiers, linked=True)
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

        workspace.setTabbedPresentation(identifiers[:2], linked=True)
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
