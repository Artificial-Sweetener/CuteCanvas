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

"""Tests for SAM feature installation and interactions."""

import time
import types
import uuid
from pathlib import Path

import numpy as np
import pytest
from cutecanvas import Config, CuteCanvas, LayerPolicy
from cutecanvas.coverage import CoverageCombineMode
from cutecanvas.masks import sam_feature
from cutecanvas.masks.sam_feature import (
    _sam_detail_diagnostics_provider,
    _sam_summary_diagnostics_provider,
)
from cutecanvas.sam import service
from cutecanvas.sam.segmentation_request import (
    SmartSegmentationProduct,
    SmartSegmentationRequest,
)
from cutecanvas_test_support.execution_backend import TestExecution
from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
from qpane.types import DiagnosticRecord

from qpane.features import FeatureInstallError


def _stub_sam_service(monkeypatch):
    monkeypatch.setattr(service, "ensure_dependencies", lambda: None)
    monkeypatch.setattr(
        service,
        "ensure_checkpoint",
        lambda *args, **kwargs: Path("checkpoint.pt"),
    )
    monkeypatch.setattr(
        service,
        "resolve_checkpoint_path",
        lambda checkpoint_path=None: Path("checkpoint.pt"),
    )
    monkeypatch.setattr(
        service,
        "load_predictor",
        lambda checkpoint_path, device="cpu": object(),
    )
    monkeypatch.setattr(
        service,
        "predict_mask_from_box",
        lambda predictor, bbox: np.ones((1, 1), dtype=bool),
    )
    monkeypatch.setattr(service, "SamDependencyError", RuntimeError)


def _detachSamManager_keep_delegate(qpane: CuteCanvas) -> None:
    """Detach the active SAM manager while preserving the delegate reference."""
    masks = qpane._masks_controller
    delegate = masks.sam_delegate()
    qpane.detachSamManager()
    if delegate is not None:
        masks._sam_delegate = delegate  # type: ignore[attr-defined]


def _seed_mask_service(qpane: CuteCanvas) -> None:
    """Seed the mask service for SAM feature tests."""
    qpane.mask_service = types.SimpleNamespace(
        adjust_mask_component=lambda mask_id, point, *, grow: True,
        apply_mask_surface=lambda *_args, **_kwargs: True,
        getActiveMaskId=lambda: "mask-1",
        refreshAutosavePolicy=lambda: None,
        get_latest_status_message=lambda *args: None,
        controller=types.SimpleNamespace(
            apply_mask_image=lambda *_args, **_kwargs: True
        ),
    )


@pytest.fixture
def qpane_with_sam(monkeypatch, qapp):
    _stub_sam_service(monkeypatch)
    executor = TestExecution()
    qpane = CuteCanvas(features=("mask", "sam"), execution_runtime=executor.runtime)
    qpane.resize(64, 64)
    image = QImage(QSize(64, 64), QImage.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    qpane.createCompositionFromImage(image, title="SAM source")
    qpane.mask_service = types.SimpleNamespace(
        adjust_mask_component=lambda mask_id, point, *, grow: True,
        apply_mask_surface=lambda *_args, **_kwargs: True,
        getActiveMaskId=lambda: "mask-1",
        refreshAutosavePolicy=lambda: None,
        get_latest_status_message=lambda *args: None,
        controller=types.SimpleNamespace(
            apply_mask_image=lambda *_args, **_kwargs: True
        ),
    )
    try:
        assert qpane.activeRasterResolver().resolve() is not None
        yield qpane
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_sam_feature_ignores_unrecognized_request(
    monkeypatch,
    qpane_with_sam,
    caplog,
):
    qpane = qpane_with_sam
    calls = []
    raster = qpane.activeRasterResolver().resolve()
    assert raster is not None

    def record_mask(captured_id, bbox, erase_mode=False, *, context=None):
        calls.append((captured_id, bbox, erase_mode, context))

    manager = qpane.samManager()
    monkeypatch.setattr(manager, "generateMaskFromBox", record_mask)
    caplog.clear()
    tools = qpane._tools_manager
    tools.signals.smart_segmentation_requested.emit(object())
    assert not calls
    valid_bbox = (0.0, 0.0, 4.0, 4.0)
    request = SmartSegmentationRequest(
        scene_id=raster.scene_id,
        layer_id=raster.layer_id,
        resource_id=raster.resource_id,
        bounds=valid_bbox,
        product=SmartSegmentationProduct.PIXEL_SELECTION,
        combine_mode=CoverageCombineMode.SUBTRACT,
    )
    tools.signals.smart_segmentation_requested.emit(request)
    captured_id, captured_bbox, erase, context = calls[-1]
    assert captured_id == raster.resource_id
    assert np.array_equal(captured_bbox, np.asarray(valid_bbox))
    assert erase is True
    assert context is request


def test_sam_feature_does_not_reproject_mask_local_component_point(
    qpane_with_sam: CuteCanvas,
) -> None:
    """Component adjustment must consume the mask-local point emitted by the tool."""
    qpane = qpane_with_sam
    adjustments = []
    qpane.activeMaskLayerCoordinates().scene_to_source = lambda _point: pytest.fail(
        "mask-local component points must not be projected a second time"
    )

    def adjust(mask_id, point, *, grow):
        adjustments.append((mask_id, point, grow))
        return True

    qpane.mask_service.adjust_mask_component = adjust
    qpane._tools_manager.signals.mask_component_adjustment_requested.emit(
        QPoint(1, 3), True
    )
    assert adjustments == [("mask-1", QPoint(1, 3), True)]


def test_sam_component_adjustment_accepts_real_transformed_mask_coordinates(
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
) -> None:
    """The adjustment hook must accept a transformed mask-local point once."""
    _stub_sam_service(monkeypatch)
    execution = TestExecution()
    qpane = CuteCanvas(features=("mask", "sam"), execution_runtime=execution.runtime)
    try:
        image = QImage(QSize(64, 64), QImage.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        qpane.createCompositionFromImage(image, title="Transformed mask")
        mask_id = qpane.createBlankMask(image.size())
        assert mask_id is not None
        assert qpane.setActiveMaskID(mask_id)
        mask = qpane.listMasksForComposition()[0]
        assert mask.scene_id is not None
        assert mask.layer_id is not None
        assert qpane.setLayerInteractionPolicy(
            mask.scene_id,
            mask.layer_id,
            LayerPolicy(selectable=True, movable=True),
        )
        assert qpane.setLayerPlacement(
            mask.scene_id,
            mask.layer_id,
            QRectF(0.25, 0.25, 64.0, 64.0),
        )
        mapped = qpane.activeMaskLayerCoordinates().scene_to_source(QPoint(10, 10))
        assert mapped is not None
        assert not mapped.x().is_integer()
        adjustments = []

        def adjust(mask_id: uuid.UUID, point: QPoint, *, grow: bool) -> None:
            """Capture the coordinate accepted by the component tool."""
            adjustments.append((mask_id, point, grow))

        qpane.mask_service.adjust_mask_component = adjust
        qpane._tools_manager.signals.mask_component_adjustment_requested.emit(
            mapped.toPoint(),
            False,
        )

        assert adjustments == [(mask_id, mapped.toPoint(), False)]
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_detach_sam_manager_cancels_pending_predictor_work(
    qpane_with_sam, monkeypatch, tmp_path
) -> None:
    """Detaching SAM cancels work before its executor can outlive the feature."""
    qpane = qpane_with_sam
    manager = qpane.samManager()
    assert manager is not None
    monkeypatch.setattr(manager, "checkpointReady", lambda: True)
    image = QImage(8, 8, QImage.Format_ARGB32)
    image.fill(QColor("white"))
    image_id = uuid.uuid4()
    manager.requestPredictor(image, image_id, source_path=tmp_path / "image.png")
    pending = manager._pending[image_id]
    predictor_handle = pending.handle
    assert predictor_handle is not None

    qpane.detachSamManager()

    assert predictor_handle.state.is_terminal
    assert manager.activePredictorLoads() == 0


def test_sam_providers_report_additional_metrics():
    thread_pool = types.SimpleNamespace(
        activeThreadCount=lambda: 1, maxThreadCount=lambda: 4
    )
    manager = types.SimpleNamespace(
        getCachedPredictorCount=lambda: 2,
        thread_pool=thread_pool,
    )
    qpane = types.SimpleNamespace(
        samManager=lambda: manager,
        masks=lambda: types.SimpleNamespace(
            sam_delegate=lambda: types.SimpleNamespace(activePredictor=object())
        ),
    )
    summary = _sam_summary_diagnostics_provider(qpane)
    detail = _sam_detail_diagnostics_provider(qpane)
    assert DiagnosticRecord("SAM|Cache", "2") in summary
    assert DiagnosticRecord("SAM|State", "Ready") in summary
    assert DiagnosticRecord("SAM|Active Jobs", "1") in detail
    assert DiagnosticRecord("SAM|Max Threads", "4") in detail


def test_install_sam_feature_respects_config(monkeypatch, qapp):
    _stub_sam_service(monkeypatch)
    executor = TestExecution()
    qpane = CuteCanvas(features=("mask", "sam"), execution_runtime=executor.runtime)
    qpane.resize(64, 64)
    _detachSamManager_keep_delegate(qpane)
    qpane.applySettings(sam_device="cuda", sam_cache_limit=1)
    _seed_mask_service(qpane)
    sam_feature.install_sam_feature(qpane)
    manager = qpane.samManager()
    assert manager is not None
    try:
        import torch

        cuda_available = bool(
            getattr(torch, "cuda", None)
            and callable(getattr(torch.cuda, "is_available", None))
            and torch.cuda.is_available()
        )
    except (AttributeError, ImportError, RuntimeError):
        cuda_available = False
    expected_device = "cuda" if cuda_available else "cpu"
    assert manager._device == expected_device
    assert manager.cacheLimit() == 1


def test_sam_feature_install_defers_predictor_dependency_imports(
    monkeypatch, qapp, tmp_path
):
    checkpoint = tmp_path / "sam-checkpoint.pt"
    checkpoint.write_bytes(b"ready")

    def fail_ensure_dependencies():
        raise AssertionError("SAM dependencies should load in predictor workers")

    monkeypatch.setattr(service, "ensure_dependencies", fail_ensure_dependencies)
    monkeypatch.setattr(
        service,
        "resolve_checkpoint_path",
        lambda checkpoint_path=None: Path(checkpoint_path).resolve(),
    )
    monkeypatch.setattr(
        service,
        "ensure_checkpoint",
        lambda checkpoint_path, **_kwargs: Path(checkpoint_path).resolve(),
    )
    executor = TestExecution()
    config = Config(
        sam_download_mode="disabled",
        sam_model_path=str(checkpoint),
    )
    qpane = CuteCanvas(
        features=("mask", "sam"),
        config=config,
        execution_runtime=executor.runtime,
    )
    qpane.resize(64, 64)
    try:
        assert qpane.samFeatureAvailable()
        assert qpane.samManager() is not None
    finally:
        qpane.deleteLater()
        qapp.processEvents()


def test_install_sam_feature_disabled_missing_checkpoint(monkeypatch, qapp):
    _stub_sam_service(monkeypatch)

    def _raise_missing(*_args, **_kwargs):
        raise service.SamDependencyError("missing checkpoint")

    monkeypatch.setattr(service, "ensure_checkpoint", _raise_missing)
    executor = TestExecution()
    qpane = CuteCanvas(features=("mask", "sam"), execution_runtime=executor.runtime)
    qpane.resize(64, 64)
    _detachSamManager_keep_delegate(qpane)
    qpane.applySettings(sam_download_mode="disabled")
    _seed_mask_service(qpane)
    statuses: list[str] = []
    qpane.samCheckpointStatusChanged.connect(
        lambda status, _path: statuses.append(status)
    )
    with pytest.raises(FeatureInstallError):
        sam_feature.install_sam_feature(qpane)
    assert "missing" in statuses


def test_install_sam_feature_background_download_signals(monkeypatch, qapp, tmp_path):
    _stub_sam_service(monkeypatch)
    checkpoint = tmp_path / "sam-checkpoint.pt"
    if checkpoint.exists():
        checkpoint.unlink()
    initial_checkpoint = tmp_path / "initial-checkpoint.pt"
    initial_checkpoint.write_bytes(b"ready")

    def fake_ensure_checkpoint(
        checkpoint_path,
        *,
        download_mode,
        model_url,
        expected_hash=None,
        progress_callback=None,
    ):
        assert download_mode == "background"
        assert expected_hash is None
        if progress_callback is not None:
            progress_callback(5, 10)
        checkpoint_path.write_bytes(b"checkpoint")
        return checkpoint_path

    monkeypatch.setattr(
        service,
        "resolve_checkpoint_path",
        lambda checkpoint_path=None: Path(checkpoint_path).resolve(),
    )
    monkeypatch.setattr(service, "ensure_checkpoint", fake_ensure_checkpoint)
    executor = TestExecution()
    config = Config(
        sam_download_mode="background",
        sam_model_path=str(initial_checkpoint),
    )
    qpane = CuteCanvas(
        features=("mask", "sam"),
        config=config,
        execution_runtime=executor.runtime,
    )
    qpane.resize(64, 64)
    _detachSamManager_keep_delegate(qpane)
    qpane.applySettings(
        sam_download_mode="background",
        sam_model_path=str(checkpoint),
    )
    _seed_mask_service(qpane)
    statuses: list[str] = []
    progress: list[tuple[int, int | None]] = []
    qpane.samCheckpointStatusChanged.connect(
        lambda status, _path: statuses.append(status)
    )
    qpane.samCheckpointProgress.connect(
        lambda downloaded, total: progress.append((downloaded, total))
    )
    sam_feature.install_sam_feature(qpane)
    assert statuses == ["downloading"]
    deadline = time.monotonic() + 2.0
    while statuses[-1] != "ready" and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    assert statuses[-1] == "ready"
    assert progress == [(5, 10)]


def test_install_sam_feature_background_noop_when_ready(monkeypatch, qapp, tmp_path):
    _stub_sam_service(monkeypatch)
    checkpoint = tmp_path / "sam-checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")

    def fail_ensure_checkpoint(*_args, **_kwargs):
        raise AssertionError("ensure_checkpoint should not be invoked when ready")

    monkeypatch.setattr(
        service,
        "resolve_checkpoint_path",
        lambda checkpoint_path=None: Path(checkpoint_path).resolve(),
    )
    monkeypatch.setattr(service, "ensure_checkpoint", fail_ensure_checkpoint)
    executor = TestExecution()
    config = Config(
        sam_download_mode="background",
        sam_model_path=str(checkpoint),
    )
    qpane = CuteCanvas(
        features=("mask", "sam"),
        config=config,
        execution_runtime=executor.runtime,
    )
    qpane.resize(64, 64)
    _detachSamManager_keep_delegate(qpane)
    qpane.applySettings(
        sam_download_mode="background",
        sam_model_path=str(checkpoint),
    )
    _seed_mask_service(qpane)
    statuses: list[str] = []
    qpane.samCheckpointStatusChanged.connect(
        lambda status, _path: statuses.append(status)
    )
    sam_feature.install_sam_feature(qpane)
    assert statuses == ["ready"]
    assert not executor.pending_jobs()


def test_install_sam_feature_disabled_mode_skips_executor(monkeypatch, qapp, tmp_path):
    _stub_sam_service(monkeypatch)
    checkpoint = tmp_path / "sam-checkpoint.pt"
    initial_checkpoint = tmp_path / "initial-checkpoint.pt"
    initial_checkpoint.write_bytes(b"ready")

    def raise_missing(*_args, **_kwargs):
        raise service.SamDependencyError("missing checkpoint")

    monkeypatch.setattr(
        service,
        "resolve_checkpoint_path",
        lambda checkpoint_path=None: Path(checkpoint_path).resolve(),
    )
    monkeypatch.setattr(service, "ensure_checkpoint", raise_missing)
    executor = TestExecution()
    config = Config(
        sam_download_mode="background",
        sam_model_path=str(initial_checkpoint),
    )
    qpane = CuteCanvas(
        features=("mask", "sam"),
        config=config,
        execution_runtime=executor.runtime,
    )
    qpane.resize(64, 64)
    _detachSamManager_keep_delegate(qpane)
    qpane.applySettings(
        sam_download_mode="disabled",
        sam_model_path=str(checkpoint),
    )
    _seed_mask_service(qpane)
    statuses: list[str] = []
    qpane.samCheckpointStatusChanged.connect(
        lambda status, _path: statuses.append(status)
    )
    with pytest.raises(FeatureInstallError):
        sam_feature.install_sam_feature(qpane)
    assert "missing" in statuses
    assert not executor.pending_jobs()
