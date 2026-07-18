#    QPane - High-performance PySide6 image viewer
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

"""Tests for SAM manager predictor handling and retries."""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage

from qpane import Config, sam
from qpane.core.config_features import MaskConfigSlice
from qpane.masks.generated_edits import MaskGeneratedEditService
from qpane.masks.mask import MaskAssetStore, MaskLayer, MaskSurface
from qpane.masks.mask_controller import MaskController
from qpane.masks.projection import MaskCanvasProjectionService
from qpane.sam.manager import SamManager, SamWorker
from tests.helpers.executor_stubs import RejectingStubExecutor, StubExecutor

DEFAULT_CHECKPOINT = Path("sam-checkpoint.pt")


def _touch_checkpoint(path: Path) -> Path:
    """Ensure a checkpoint path exists for readiness checks."""
    path.write_bytes(b"checkpoint")
    return path


@pytest.mark.usefixtures("qapp")
def test_prepare_image_rgb_preserves_channels():
    image = QImage(2, 1, QImage.Format_ARGB32)
    image.fill(QColor(10, 20, 30, 255))
    rgb = SamWorker._prepare_image_rgb(image)
    assert rgb.shape == (1, 2, 3)
    assert rgb[0, 0, :].tolist() == [10, 20, 30]
    assert rgb[0, 1, :].tolist() == [10, 20, 30]


def test_generate_mask_emits_none_when_predictor_missing():
    manager = SamManager(executor=StubExecutor(), checkpoint_path=DEFAULT_CHECKPOINT)
    captured: list[tuple[object, np.ndarray, bool]] = []
    manager.maskReady.connect(
        lambda mask, bbox, erase: captured.append((mask, bbox.copy(), erase))
    )
    bbox = np.array([0, 0, 10, 10])
    manager.generateMaskFromBox(uuid.uuid4(), bbox, erase_mode=False)
    assert captured, "maskReady should fire even when the predictor is absent"
    emitted_mask, emitted_bbox, emitted_erase = captured[-1]
    assert emitted_mask is None
    np.testing.assert_array_equal(emitted_bbox, bbox)
    assert emitted_erase is False


def test_generate_mask_emits_none_when_service_returns_none(monkeypatch):
    manager = SamManager(executor=StubExecutor(), checkpoint_path=DEFAULT_CHECKPOINT)
    image_id = uuid.uuid4()
    manager._sam_predictors[image_id] = object()
    monkeypatch.setattr(
        sam.service,
        "predict_mask_from_box",
        lambda predictor, bbox: None,
    )
    captured: list[tuple[object, np.ndarray, bool]] = []
    manager.maskReady.connect(
        lambda mask, bbox, erase: captured.append((mask, bbox.copy(), erase))
    )
    bbox = np.array([1, 2, 3, 4])
    manager.generateMaskFromBox(image_id, bbox, erase_mode=True)
    assert captured, "maskReady should fire when SAM returns no mask"
    emitted_mask, emitted_bbox, emitted_erase = captured[-1]
    assert emitted_mask is None
    np.testing.assert_array_equal(emitted_bbox, bbox)
    assert emitted_erase is True


def test_worker_error_emits_failure_signal():
    manager = SamManager(executor=StubExecutor(), checkpoint_path=DEFAULT_CHECKPOINT)
    failures: list[tuple[uuid.UUID, str]] = []
    manager.predictorLoadFailed.connect(
        lambda path, message: failures.append((path, message))
    )
    image_id = uuid.uuid4()
    manager._on_worker_error(image_id, "boom")
    assert failures == [(image_id, "boom")]


@pytest.mark.usefixtures("qapp")
def test_mask_controller_handles_none_mask():
    mask_manager = MaskAssetStore()
    controller = MaskController(
        mask_manager,
        lambda point: point,
        Config(),
        mask_config=MaskConfigSlice(),
    )
    mask_image = QImage(4, 4, QImage.Format_Grayscale8)
    mask_image.fill(0)
    mask_id = uuid.uuid4()
    mask_manager._masks[mask_id] = MaskLayer(
        mask_id=mask_id, surface=MaskSurface.from_qimage(mask_image)
    )
    controller._active_mask_id = mask_id
    emissions: list[tuple[uuid.UUID, object]] = []
    controller.mask_updated.connect(lambda mid, rect: emissions.append((mid, rect)))
    generated = MaskGeneratedEditService(
        active_mask_id=lambda: mask_id,
        projection=MaskCanvasProjectionService(
            assets=mask_manager,
            active_scene=lambda: None,
        ),
        edits=controller.edits,
        renders=controller.renders,
    )

    result = generated.apply(None, erase=False)

    assert result == (mask_id, False)
    assert not emissions


def test_generate_mask_emits_none_on_invalid_bbox(caplog):
    manager = SamManager(executor=StubExecutor(), checkpoint_path=DEFAULT_CHECKPOINT)
    image_id = uuid.uuid4()

    class _Predictor:
        def predict(self, *, box, multimask_output):
            raise AssertionError("predict should not run for invalid bbox")

    manager._sam_predictors[image_id] = _Predictor()
    captured: list[tuple[object, np.ndarray, bool]] = []
    manager.maskReady.connect(
        lambda mask, bbox, erase: captured.append((mask, bbox.copy(), erase))
    )
    caplog.set_level(logging.WARNING)
    invalid_bbox = np.array([0, 1, 2])
    manager.generateMaskFromBox(image_id, invalid_bbox, erase_mode=True)
    assert captured, "maskReady should emit when SAM rejects a bbox"
    emitted_mask, emitted_bbox, emitted_erase = captured[-1]
    assert emitted_mask is None
    np.testing.assert_array_equal(emitted_bbox, invalid_bbox)
    assert emitted_erase is True
    assert "Invalid bounding box" in caplog.text


@pytest.mark.usefixtures("qapp")
def test_requestPredictor_queues_executor(monkeypatch, qapp, tmp_path):
    """SamManager should submit predictor loads via the shared executor."""
    executor = StubExecutor()
    checkpoint = _touch_checkpoint(tmp_path / "sam-checkpoint.pt")
    manager = SamManager(executor=executor, checkpoint_path=checkpoint)

    class _FakePredictor:
        def __init__(self) -> None:
            self.image = None

        def set_image(self, image):
            self.image = image

    monkeypatch.setattr(
        sam.service,
        "load_predictor",
        lambda checkpoint_path, device="cpu": _FakePredictor(),
    )
    image = QImage(8, 8, QImage.Format_ARGB32)
    image.fill(QColor("white"))
    image_id = uuid.uuid4()
    source_path = Path("sam-image.png")
    manager.requestPredictor(image, image_id, source_path=source_path)
    pending = list(executor.pending_tasks())
    assert pending and pending[0].handle.category == "sam"
    executor.run_task(pending[0].handle.task_id)
    qapp.processEvents()
    assert executor.finished
    assert manager.getPredictor(image_id) is not None
    manager.shutdown()


def test_cancel_pending_predictor_requests_executor_cancellation(monkeypatch, tmp_path):
    """Cancelling an in-flight predictor should invoke executor.cancel."""
    executor = StubExecutor()
    checkpoint = _touch_checkpoint(tmp_path / "sam-checkpoint.pt")
    manager = SamManager(executor=executor, checkpoint_path=checkpoint)
    monkeypatch.setattr(
        sam.service,
        "load_predictor",
        lambda checkpoint_path, device="cpu": object(),
    )
    image = QImage(4, 4, QImage.Format_ARGB32)
    image.fill(QColor("black"))
    image_id = uuid.uuid4()
    source_path = Path("cancel-me.png")
    manager.requestPredictor(image, image_id, source_path=source_path)
    pending = list(executor.pending_tasks())
    handle = pending[0].handle
    manager.cancelPendingPredictor(image_id)
    assert handle in executor.cancelled
    assert image_id not in manager._inflight
    manager.shutdown()


@pytest.mark.usefixtures("qapp")
def test_requestPredictor_retries_after_throttle(monkeypatch, qapp, tmp_path) -> None:
    executor = RejectingStubExecutor(reject_counts={"sam": 1})
    checkpoint = _touch_checkpoint(tmp_path / "sam-checkpoint.pt")
    manager = SamManager(executor=executor, checkpoint_path=checkpoint)

    class _FakePredictor:
        def __init__(self) -> None:
            self.image = None

        def set_image(self, image):
            self.image = image

    monkeypatch.setattr(
        sam.service,
        "load_predictor",
        lambda checkpoint_path, device="cpu": _FakePredictor(),
    )
    image = QImage(16, 16, QImage.Format_ARGB32)
    image.fill(QColor("white"))
    image_id = uuid.uuid4()
    source_path = Path("sam-throttle.png")
    throttled: list[tuple[uuid.UUID, int]] = []
    manager.predictorThrottled.connect(
        lambda p, attempt: throttled.append((p, attempt))
    )
    manager.requestPredictor(image, image_id, source_path=source_path)
    assert throttled == [(image_id, 1)]
    assert executor.rejections

    def wait_for(predicate, *, timeout: float = 1.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            qapp.processEvents()
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("condition was not met before timeout")

    wait_for(
        lambda: any(
            record.handle.category == "sam" for record in executor.pending_tasks()
        )
    )
    pending = list(executor.pending_tasks())
    assert pending
    executor.run_task(pending[0].handle.task_id)
    wait_for(lambda: manager.getPredictor(image_id) is not None)
    assert not getattr(
        manager, "_predictor_retry_entries", {}
    ), "sam retries should be cleared"


def test_setCacheLimit_trims_existing_predictors(qapp):
    manager = SamManager(executor=StubExecutor(), checkpoint_path=DEFAULT_CHECKPOINT)
    removed: list[uuid.UUID] = []
    manager.predictorRemoved.connect(lambda path: removed.append(path))
    first = uuid.uuid4()
    second = uuid.uuid4()
    manager._sam_predictors[first] = object()
    manager._sam_predictors[second] = object()
    manager.setCacheLimit(1)
    assert removed == [first]
    assert list(manager._sam_predictors.keys()) == [second]


def test_cache_limit_enforced_on_predictor_ready(qapp):
    manager = SamManager(
        cache_limit=1,
        executor=StubExecutor(),
        checkpoint_path=DEFAULT_CHECKPOINT,
    )
    removed: list[uuid.UUID] = []
    manager.predictorRemoved.connect(lambda path: removed.append(path))
    first = uuid.uuid4()
    second = uuid.uuid4()
    manager._on_worker_finished(object(), first)
    manager._on_worker_finished(object(), second)
    assert removed == [first]
    assert list(manager._sam_predictors.keys()) == [second]


def test_snapshot_metrics_report_cache_bytes():
    manager = SamManager(executor=StubExecutor(), checkpoint_path=DEFAULT_CHECKPOINT)
    image_id = uuid.uuid4()

    class _Tensor:
        def __init__(self, numel, element_size):
            self._numel = numel
            self._element_size = element_size

        def numel(self):
            return self._numel

        def element_size(self):
            return self._element_size

    class _Model:
        def __init__(self):
            self._params = [_Tensor(4, 2)]
            self._buffers = [_Tensor(2, 4)]

        def parameters(self):
            return self._params

        def buffers(self):
            return self._buffers

    class _Predictor:
        def __init__(self):
            self.model = _Model()

    manager._on_worker_finished(_Predictor(), image_id)
    metrics = manager.snapshot_metrics()
    assert metrics.cache_bytes == 16
    assert manager.cache_usage_bytes() == 16
    manager.removeFromCache(image_id)
    assert manager.cache_usage_bytes() == 0


def test_requestPredictor_logs_when_checkpoint_missing(caplog, tmp_path):
    executor = StubExecutor()
    manager = SamManager(
        executor=executor, checkpoint_path=tmp_path / "missing-checkpoint.pt"
    )
    image = QImage(4, 4, QImage.Format_ARGB32)
    image.fill(QColor("black"))
    caplog.set_level(logging.WARNING)
    manager.requestPredictor(image, uuid.uuid4(), source_path=Path("nope.png"))
    assert not list(executor.pending_tasks())
    assert "checkpoint is missing" in caplog.text


def test_requestPredictor_emits_ready_on_cache_hit(tmp_path) -> None:
    """Cached predictors should emit predictorReady without re-queueing."""
    executor = StubExecutor()
    checkpoint = _touch_checkpoint(tmp_path / "sam-checkpoint.pt")
    manager = SamManager(executor=executor, checkpoint_path=checkpoint)
    image_id = uuid.uuid4()
    source_path = Path("cached.png")
    predictor = object()
    manager._sam_predictors[image_id] = predictor
    captured: list[tuple[object, uuid.UUID]] = []
    manager.predictorReady.connect(lambda pred, p: captured.append((pred, p)))
    image = QImage(2, 2, QImage.Format_ARGB32)
    manager.requestPredictor(image, image_id, source_path=source_path)
    assert captured == [(predictor, image_id)]
    assert not list(executor.pending_tasks())


def test_requestPredictor_skips_duplicate_inflight(tmp_path) -> None:
    """Duplicate predictor requests should not queue extra work."""
    executor = StubExecutor()
    checkpoint = _touch_checkpoint(tmp_path / "sam-checkpoint.pt")
    manager = SamManager(executor=executor, checkpoint_path=checkpoint)
    image = QImage(2, 2, QImage.Format_ARGB32)
    image_id = uuid.uuid4()
    source_path = Path("dupe.png")
    manager.requestPredictor(image, image_id, source_path=source_path)
    manager.requestPredictor(image, image_id, source_path=source_path)
    pending = list(executor.pending_tasks())
    assert len(pending) == 1


def test_compute_predictor_retry_delay_bounds(tmp_path) -> None:
    """Retry delays should respect configured min/max bounds."""
    manager = SamManager(
        executor=StubExecutor(),
        checkpoint_path=_touch_checkpoint(tmp_path / "sam-checkpoint.pt"),
    )
    for attempts in (1, 2, 6):
        delay = manager._compute_predictor_retry_delay(attempts)
        assert 150 <= delay <= 2500


def test_estimate_predictor_bytes_falls_back_on_failure(tmp_path) -> None:
    """Estimator should return the default when sizeInBytes fails."""
    manager = SamManager(
        executor=StubExecutor(),
        checkpoint_path=_touch_checkpoint(tmp_path / "sam-checkpoint.pt"),
    )

    class _BrokenImage:
        def sizeInBytes(self) -> int:
            raise RuntimeError("boom")

    estimated = manager._estimate_predictor_bytes(_BrokenImage())
    assert estimated == 128 * 1024 * 1024


def test_sanitize_cache_limit_accepts_valid_values() -> None:
    """Cache limit sanitizer should reject invalid values and accept integers."""
    assert SamManager._sanitize_cache_limit(None) is None
    assert SamManager._sanitize_cache_limit("bad") is None
    assert SamManager._sanitize_cache_limit(-1) is None
    assert SamManager._sanitize_cache_limit(2) == 2
    assert SamManager._sanitize_cache_limit("3") == 3


def test_enforce_cache_limit_trims_oldest_entry(tmp_path) -> None:
    """Cache enforcement should drop the oldest predictor when over limit."""
    manager = SamManager(
        executor=StubExecutor(),
        checkpoint_path=_touch_checkpoint(tmp_path / "sam-checkpoint.pt"),
    )
    first = uuid.uuid4()
    second = uuid.uuid4()
    manager._sam_predictors = {first: object(), second: object()}
    manager._predictor_sizes = {first: 10, second: 10}
    manager._pending_estimates = {first: 10, second: 10}
    removed: list[uuid.UUID] = []
    manager.predictorRemoved.connect(lambda path: removed.append(path))
    manager.setCacheLimit(1)
    assert removed == [first]
    assert list(manager._sam_predictors.keys()) == [second]


def test_model_tensor_bytes_sums_parameters_and_buffers() -> None:
    """Model tensor accounting should sum parameter and buffer sizes."""

    class _FakeTensor:
        def __init__(self, numel, element_size) -> None:
            self._numel = numel
            self._element_size = element_size

        def numel(self):
            return self._numel

        def element_size(self):
            return self._element_size

    class _FakeModel:
        def __init__(self) -> None:
            self._params = [_FakeTensor(4, 2)]
            self._buffers = [_FakeTensor(3, 4)]

        def parameters(self):
            return self._params

        def buffers(self):
            return self._buffers

    bytes_used = SamManager._model_tensor_bytes(_FakeModel())
    assert bytes_used == (4 * 2) + (3 * 4)


def test_drop_predictor_removes_sizes_and_estimates(tmp_path) -> None:
    """Dropping predictors should clear cache metadata and emit signals."""
    manager = SamManager(
        executor=StubExecutor(),
        checkpoint_path=_touch_checkpoint(tmp_path / "sam-checkpoint.pt"),
    )
    image_id = uuid.uuid4()
    manager._sam_predictors[image_id] = object()
    manager._predictor_sizes[image_id] = 12
    manager._pending_estimates[image_id] = 7
    removed: list[uuid.UUID] = []
    manager.predictorRemoved.connect(lambda removed_id: removed.append(removed_id))
    assert manager._drop_predictor(image_id) is True
    assert removed == [image_id]
    assert image_id not in manager._sam_predictors
    assert image_id not in manager._predictor_sizes
    assert image_id not in manager._pending_estimates


def test_remove_from_cache_reports_whether_a_predictor_was_removed(tmp_path) -> None:
    """The public cache hook must truthfully report each eviction result."""
    manager = SamManager(
        executor=StubExecutor(),
        checkpoint_path=_touch_checkpoint(tmp_path / "sam-checkpoint.pt"),
    )
    image_id = uuid.uuid4()
    manager._sam_predictors[image_id] = object()
    manager._predictor_sizes[image_id] = 12

    assert manager.removeFromCache(image_id) is True
    assert manager.removeFromCache(image_id) is False


def test_measure_predictor_bytes_returns_zero_without_model(tmp_path) -> None:
    """Predictors without model metadata should report zero bytes."""
    manager = SamManager(
        executor=StubExecutor(),
        checkpoint_path=_touch_checkpoint(tmp_path / "sam-checkpoint.pt"),
    )

    class _Predictor:
        pass

    assert manager._measure_predictor_bytes(_Predictor()) == 0
