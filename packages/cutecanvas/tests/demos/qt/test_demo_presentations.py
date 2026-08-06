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
"""Verify the demo teaches document presentation through public APIs."""

from __future__ import annotations

from cutecanvas_demo import ExampleOptions, ExampleWindow
from PySide6.QtCore import QRectF
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QFileDialog


def test_demo_opens_multi_view_inspection_for_shared_document(qapp) -> None:
    """The focused tutorial window exposes every built-in presentation."""
    window = ExampleWindow(ExampleOptions())
    try:
        window.qpane.document().create_composition(
            QRectF(0.0, 0.0, 640.0, 480.0),
            title="Second target",
        )
        window.presentations.show()
        qapp.processEvents()

        workspace = window.presentations._workspace
        mode = window.presentations._mode
        assert workspace is not None
        assert mode is not None
        for index in range(4):
            mode.setCurrentIndex(index)
            qapp.processEvents()
        assert workspace.document is window.qpane.document()
        assert workspace.session.presentation.target_ids
    finally:
        window.close()
        qapp.processEvents()


def test_demo_exports_the_visible_presentation_through_projection(
    qapp,
    monkeypatch,
    tmp_path,
) -> None:
    """The tutorial export is asynchronous and uses the mounted public canvas."""
    window = ExampleWindow(ExampleOptions())
    destination = tmp_path / "preview.png"
    try:
        window.presentations.show()
        qapp.processEvents()
        workspace = window.presentations._workspace
        assert workspace is not None
        target = workspace.currentCanvas()
        assert target is not None
        completed = QSignalSpy(target.projectionCompleted)
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            lambda *_args, **_kwargs: (str(destination), "PNG images (*.png)"),
        )

        window.presentations._projection.export_active(target)

        assert completed.wait(5000)
        qapp.processEvents()
        assert destination.exists()
    finally:
        window.close()
        qapp.processEvents()
