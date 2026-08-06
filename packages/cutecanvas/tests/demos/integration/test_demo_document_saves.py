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
"""Verify the public demonstration's detached document-save coordinator."""

from __future__ import annotations

from time import monotonic

from cutecanvas import CuteCanvas
from demonstration.document_saves import (
    DocumentSaveCoordinator,
    DocumentSaveResult,
)
from PySide6.QtGui import QColor, QImage
from qpane import create_default_execution_runtime


def test_document_save_coordinator_writes_detached_workspace_off_thread(
    qapp,
    tmp_path,
) -> None:
    """Persist stable authority and reject overlapping writes to one path."""
    runtime = create_default_execution_runtime()
    source = CuteCanvas(features=())
    restored = CuteCanvas(features=())
    coordinator = DocumentSaveCoordinator(runtime, source.editor.persistence)
    results: list[DocumentSaveResult] = []
    try:
        image = QImage(64, 48, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("royalblue"))
        composition_id = source.createCompositionFromImage(image)
        snapshot = source.editor.persistence.capture_document()
        path = tmp_path / "workspace.cutecanvas"

        assert coordinator.submit(snapshot, path, finished=results.append)
        assert not coordinator.submit(snapshot, path, finished=results.append)
        deadline = monotonic() + 5.0
        while not results and monotonic() < deadline:
            qapp.processEvents()

        assert results == [DocumentSaveResult(path)]
        loaded = restored.editor.persistence.load_document(path, open_first=False)
        assert tuple(handle.id for handle in loaded) == (composition_id,)
    finally:
        coordinator.close()
        source.close()
        restored.close()
        runtime.shutdown(wait=True)
