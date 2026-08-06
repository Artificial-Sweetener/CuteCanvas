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

"""Own reusable mounted mask-workflow setup for CuteCanvas tests."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from cutecanvas import CuteCanvas
from cutecanvas.masks import install as mask_install
from cutecanvas.masks.live_preview_store import MaskLivePreviewStore
from cutecanvas.masks.mask import MaskAssetStore
from cutecanvas.masks.mask_controller import MaskController
from cutecanvas.masks.mask_service import MaskService
from cutecanvas.painting import BrushStrokeSegment
from PySide6.QtCore import QCoreApplication, QPointF
from PySide6.QtGui import QImage, Qt
from PySide6.QtWidgets import QApplication

from cutecanvas_test_support.config import fixed_cache_config
from cutecanvas_test_support.execution_backend import TestExecution


def cleanup_canvas(canvas: CuteCanvas, application: QApplication) -> None:
    """Dispose one test canvas and shut down an injected execution runtime."""
    canvas.deleteLater()
    application.processEvents()
    runtime = getattr(canvas, "_test_execution_runtime", None)
    if runtime is not None:
        runtime.shutdown()


def mask_service(canvas: CuteCanvas) -> MaskService:
    """Return the installed mask service or fail with ownership context."""
    controller = canvas._masks_controller
    assert controller is not None
    service = controller.mask_service()
    assert service is not None
    return service


def prepare_canvas_with_mask_feature(
    *,
    executor: TestExecution | None = None,
    features: tuple[str, ...] | None = None,
    image_size_px: int = 64,
) -> tuple[CuteCanvas, QImage]:
    """Build a canvas seeded with an image and ready-to-use mask tooling."""
    active_executor = executor or TestExecution(auto_finish=True)
    active_features = features if features is not None else ("mask",)
    canvas = CuteCanvas(
        execution_runtime=active_executor.runtime,
        features=active_features,
    )
    if not active_executor.auto_finish:
        canvas._test_execution_backend = active_executor
        canvas._test_execution_runtime = active_executor.runtime
    canvas.resize(max(32, image_size_px * 2), max(32, image_size_px * 2))
    canvas.applySettings(mask_autosave_enabled=True)
    image = QImage(image_size_px, image_size_px, QImage.Format_ARGB32)
    image.fill(Qt.white)
    canvas.createCompositionFromImage(image, title="Mask workflow")
    return canvas, image


def queue_pending_stroke(
    canvas: CuteCanvas,
    start: Any,
    end: Any | None = None,
    erase: bool = False,
) -> None:
    """Emit a brush stroke while leaving executor work pending for assertions."""
    tools = canvas._tools_manager
    tools.signals.undo_state_push_requested.emit()
    end_point = start if end is None else end
    tools.signals.stroke_applied.emit(
        BrushStrokeSegment.fixed(
            (start.x(), start.y()),
            (end_point.x(), end_point.y()),
            canvas.interaction.brush_size,
            erase,
        )
    )
    tools.signals.stroke_completed.emit()
    application = QCoreApplication.instance()
    if application is not None:
        application.processEvents()


def provision_canvas_with_mask(
    application: QApplication,
    monkeypatch: Any,
) -> Iterator[tuple[CuteCanvas, MaskAssetStore, object]]:
    """Yield a mounted mask-enabled canvas with deterministic collaborators."""
    manager_box: dict[str, MaskAssetStore] = {}

    def install_mask_feature(canvas: CuteCanvas) -> None:
        """Install deterministic mask collaborators and retain their store."""
        manager = canvas.document().masks
        manager.set_undo_limit(canvas.settings.mask_undo_limit)
        manager_box["manager"] = manager
        controller = MaskController(
            manager,
            source_to_panel_point=lambda point: QPointF(
                float(point.x()),
                float(point.y()),
            ),
            config=canvas.settings,
            live_previews=MaskLivePreviewStore(),
        )
        service = MaskService(
            qpane=canvas,
            mask_assets=manager,
            mask_controller=controller,
            config=canvas.settings,
            view_execution_scope=canvas._execution_binding.scope,
            document_execution_scope=(
                canvas._execution_binding.document_runtime.execution_scope
            ),
            latest_requests=(
                canvas._execution_binding.document_runtime._latest_request_registry
            ),
        )
        canvas.attachMaskService(service)
        canvas.refreshMaskAutosavePolicy()

    monkeypatch.setattr(mask_install, "install_mask_feature", install_mask_feature)
    canvas = CuteCanvas(config=fixed_cache_config(), features=("mask",))
    canvas.resize(32, 32)
    canvas.applySettings(mask_autosave_enabled=True)
    image = QImage(8, 8, QImage.Format_ARGB32)
    image.fill(Qt.white)
    composition_id = canvas.createCompositionFromImage(image)
    try:
        yield canvas, manager_box["manager"], composition_id
    finally:
        cleanup_canvas(canvas, application)
