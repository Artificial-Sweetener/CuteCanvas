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

"""End-to-end smoke coverage for the demonstration image-loading workflow."""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtGui import QColor, QImage

from cutecanvas import Config
from cutecanvas.sam.manager import SamManager
from cutecanvas_demo import ExampleOptions, ExampleWindow
from demonstration.workers import ImageLoadCoordinator
from qpane.sdk.execution import create_default_execution_runtime


def test_image_loader_pool_lifecycle_returns_callbacks_to_gui_thread(
    qapp, tmp_path
) -> None:
    """Thread-pool image loads must deliver and dispose Qt state on the GUI thread."""
    image_path = tmp_path / "threaded-large.png"
    source = QImage(4096, 2048, QImage.Format_RGBA8888)
    source.fill(QColor("#2f80ed"))
    assert source.save(str(image_path))

    callback_threads: list[QThread] = []
    finished_counts: list[int] = []
    runtime = create_default_execution_runtime()
    coordinator = ImageLoadCoordinator(runtime)
    try:
        coordinator.submit(
            [image_path],
            image_loaded=lambda _path, _image: callback_threads.append(
                QThread.currentThread()
            ),
            finished=lambda count: finished_counts.append(count),
        )
        deadline = time.monotonic() + 10.0
        while finished_counts != [1] and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.005)

        assert finished_counts == [1]
        assert callback_threads == [qapp.thread()]
        assert coordinator.active_count == 0
    finally:
        coordinator.close()
        runtime.shutdown(wait=True)


def test_demo_loads_image_with_pending_sam_and_zero_cache_budget(
    qapp, monkeypatch, tmp_path, caplog
) -> None:
    """The real demo path stays responsive while SAM preparation is pending."""
    image_path = tmp_path / "demo-smoke.png"
    source = QImage(48, 32, QImage.Format_ARGB32)
    source.fill(QColor("#2f80ed"))
    assert source.save(str(image_path))

    def leave_predictor_pending(
        manager: SamManager,
        image: QImage,
        image_id: uuid.UUID,
        *,
        source_path: Path | None = None,
    ) -> None:
        """Model a submitted predictor that remains in flight."""
        manager._pending_estimates[image_id] = manager._estimate_predictor_bytes(image)
        manager._predictor_paths[image_id] = source_path

    monkeypatch.setattr(SamManager, "requestPredictor", leave_predictor_pending)
    predictor_id_queries = 0
    original_predictor_image_ids = SamManager.predictorImageIds

    def release_stuck_pending_work(manager: SamManager) -> list[uuid.UUID]:
        """Bound the pre-fix regression so a failure cannot hang pytest."""
        nonlocal predictor_id_queries
        predictor_id_queries += 1
        if predictor_id_queries >= 2:
            manager._pending_estimates.clear()
        return original_predictor_image_ids(manager)

    monkeypatch.setattr(
        SamManager,
        "predictorImageIds",
        release_stuck_pending_work,
    )
    config = Config()
    config.cache.mode = "hard"
    config.cache.budget_mb = 0
    caplog.set_level(logging.WARNING)
    window = ExampleWindow(ExampleOptions(sam_enabled=True), config=config)
    try:
        initial_document_ids = set(window.qpane.compositionIDs())
        window.workspace.load_images([image_path])
        deadline = time.monotonic() + 5.0
        while (
            set(window.qpane.compositionIDs()) == initial_document_ids
            or not window.statusBar().currentMessage().startswith("Finished loading")
        ) and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.005)
        qapp.processEvents()

        loaded_document_ids = set(window.qpane.compositionIDs()) - initial_document_ids
        assert len(loaded_document_ids) == 1
        current_scene = window.qpane.currentScene()
        assert current_scene is not None
        assert current_scene.bounds.width() == source.width()
        assert current_scene.bounds.height() == source.height()
        assert "Finished loading 1 images" in window.statusBar().currentMessage()
        assert predictor_id_queries == 0
        assert "failed to trim below target" not in caplog.text
        assert "Cache remains over budget" not in caplog.text
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()
