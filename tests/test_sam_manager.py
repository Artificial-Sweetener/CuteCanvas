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

"""Verify native SAM session affinity, lifecycle, caching, and inference."""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

import numpy as np
from cutecanvas.sam import service
from cutecanvas.sam.manager import SamManager
from cutecanvas.sam.session import prepare_image_rgb
from PySide6.QtCore import QObject
from PySide6.QtGui import QColor, QImage
from qpane.sdk.execution import (
    ExecutionLeaseRelease,
    ExecutionResource,
    ExecutionRuntime,
    InlineDispatcher,
    QtOwnerDispatcher,
    create_default_execution_runtime,
)

from tests.helpers.execution_backend import (
    ControllableAffinityExecutionBackend,
    ControllableExecutionBackend,
    RejectingAffinityExecutionBackend,
)


class _Tensor:
    """Expose deterministic model storage metrics."""

    def __init__(self, count: int, size: int) -> None:
        """Capture element count and size."""
        self._count = count
        self._size = size

    def numel(self) -> int:
        """Return element count."""
        return self._count

    def element_size(self) -> int:
        """Return bytes per element."""
        return self._size


class _Predictor:
    """Minimal native predictor test double."""

    def __init__(self) -> None:
        """Create measurable model state."""
        self.model = type(
            "Model",
            (),
            {
                "parameters": lambda _self: (_Tensor(10, 4),),
                "buffers": lambda _self: (_Tensor(3, 2),),
            },
        )()
        self.image: np.ndarray | None = None

    def set_image(self, image: np.ndarray) -> None:
        """Retain the prepared RGB input."""
        self.image = image


def _image(width: int = 5, height: int = 3) -> QImage:
    """Return one non-null test image."""
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(QColor("white"))
    return image


def _manager(
    checkpoint: Path,
    *,
    affinity_backend: ControllableAffinityExecutionBackend | None = None,
    cache_limit: int = 2,
) -> tuple[
    SamManager,
    ExecutionRuntime,
    ControllableAffinityExecutionBackend,
]:
    """Build one manager over public deterministic backends."""
    affinity = affinity_backend or ControllableAffinityExecutionBackend()
    runtime = ExecutionRuntime(
        ControllableExecutionBackend(),
        capability_backends=(affinity,),
    )
    scope = runtime.open_scope(
        owner_id="sam-test",
        dispatcher=InlineDispatcher(),
    )
    manager = SamManager(
        execution_scope=scope,
        checkpoint_path=checkpoint,
        cache_limit=cache_limit,
    )
    return manager, runtime, affinity


def _install_predictor_stubs(monkeypatch) -> None:
    """Replace optional native dependencies with deterministic doubles."""
    monkeypatch.setattr(
        service, "load_predictor", lambda *_args, **_kwargs: _Predictor()
    )
    monkeypatch.setattr(
        service,
        "set_predictor_image",
        lambda predictor, image: predictor.set_image(image),
    )
    monkeypatch.setattr(
        service,
        "predict_mask_from_box",
        lambda _predictor, bbox: np.ones(
            (int(bbox[3] - bbox[1]), int(bbox[2] - bbox[0])),
            dtype=bool,
        ),
    )


def test_prepare_image_rgb_handles_padding_and_shared_images() -> None:
    """Image conversion returns exact contiguous RGB pixels."""
    image = QImage(3, 2, QImage.Format_RGB888)
    image.fill(QColor(12, 34, 56))
    shared = QImage(image)
    rgb = prepare_image_rgb(shared)
    assert rgb.shape == (2, 3, 3)
    assert rgb.flags.c_contiguous
    assert tuple(rgb[0, 0]) == (12, 34, 56)


def test_predictor_request_declares_native_affinity_and_adoption_lease(
    monkeypatch,
    tmp_path,
) -> None:
    """Preparation expresses hard native scheduling requirements."""
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"model")
    _install_predictor_stubs(monkeypatch)
    manager, runtime, backend = _manager(checkpoint)
    image_id = uuid.uuid4()
    manager.requestPredictor(_image(), image_id)
    job = backend.pending_jobs()[0]
    requirements = job.requirements
    assert job.operation == "editor.sam.prepare"
    assert requirements.resource == ExecutionResource.THREAD_AFFINE_NATIVE
    assert requirements.affinity_key == "sam:cpu"
    assert requirements.exclusive_key == "sam:cpu"
    assert requirements.lease_release == ExecutionLeaseRelease.ADOPTION_FINISHED
    runtime.shutdown()


def test_preparation_adopts_reference_and_measured_cache_state(
    monkeypatch,
    tmp_path,
) -> None:
    """Native predictors remain private while readiness and metrics publish."""
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"model")
    _install_predictor_stubs(monkeypatch)
    manager, runtime, backend = _manager(checkpoint)
    ready: list[tuple[object, uuid.UUID]] = []
    manager.predictorReady.connect(lambda *args: ready.append(args))
    image_id = uuid.uuid4()
    manager.requestPredictor(_image(), image_id)
    backend.run_all()
    reference = manager.getPredictor(image_id)
    assert reference is not None and reference.image_id == image_id
    assert ready[-1] == (reference, image_id)
    assert manager.cache_usage_bytes() == 46
    assert manager.pendingUsageBytes() == 0
    runtime.shutdown()


def test_inference_uses_same_affinity_session_and_publishes_uint8_mask(
    monkeypatch,
    tmp_path,
) -> None:
    """Box inference is asynchronous and returns normalized mask coverage."""
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"model")
    _install_predictor_stubs(monkeypatch)
    manager, runtime, backend = _manager(checkpoint)
    image_id = uuid.uuid4()
    manager.requestPredictor(_image(), image_id)
    backend.run_all()
    masks: list[tuple[object, np.ndarray, bool]] = []
    manager.maskReady.connect(lambda *args: masks.append(args))
    bbox = np.array([0, 0, 4, 3])
    manager.generateMaskFromBox(image_id, bbox, erase_mode=True)
    assert backend.pending_jobs()[0].operation == "editor.sam.infer_box"
    backend.run_all()
    mask, published_bbox, erase_mode = masks[-1]
    assert mask.shape == (3, 4)
    assert mask.dtype == np.uint8
    assert np.all(mask == 255)
    assert np.array_equal(published_bbox, bbox)
    assert erase_mode is True
    runtime.shutdown()


def test_missing_predictor_fails_without_native_submission(tmp_path) -> None:
    """Inference without prepared state reports no mask immediately."""
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"model")
    manager, runtime, backend = _manager(checkpoint)
    masks: list[object] = []
    manager.maskReady.connect(lambda mask, *_args: masks.append(mask))
    manager.generateMaskFromBox(uuid.uuid4(), np.array([0, 0, 1, 1]))
    assert masks == [None]
    assert backend.pending_count == 0
    runtime.shutdown()


def test_duplicate_preparation_coalesces_and_cancellation_is_handle_owned(
    monkeypatch,
    tmp_path,
) -> None:
    """One image has one current preparation and one cancellation authority."""
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"model")
    _install_predictor_stubs(monkeypatch)
    manager, runtime, backend = _manager(checkpoint)
    image_id = uuid.uuid4()
    manager.requestPredictor(_image(), image_id)
    manager.requestPredictor(_image(7, 7), image_id)
    assert backend.pending_count == 1
    assert manager.cancelPendingPredictor(image_id)
    assert backend.pending_count == 0
    assert len(backend.cancelled) == 1
    assert manager.activePredictorLoads() == 0
    runtime.shutdown()


def test_structured_rejection_retries_latest_preparation(
    monkeypatch,
    tmp_path,
    qapp,
) -> None:
    """Saturation retains a bounded latest request and reports throttling."""
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"model")
    _install_predictor_stubs(monkeypatch)
    backend = RejectingAffinityExecutionBackend({"editor.sam.prepare": 1})
    manager, runtime, _backend = _manager(
        checkpoint,
        affinity_backend=backend,
    )
    throttled: list[tuple[uuid.UUID, int]] = []
    manager.predictorThrottled.connect(lambda *args: throttled.append(args))
    image_id = uuid.uuid4()
    manager.requestPredictor(_image(), image_id)
    deadline = time.monotonic() + 2.0
    while backend.pending_count == 0 and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    assert throttled == [(image_id, 1)]
    backend.run_all()
    assert manager.getPredictor(image_id) is not None
    runtime.shutdown()


def test_cache_limit_evicts_on_native_session_and_publishes_removal(
    monkeypatch,
    tmp_path,
) -> None:
    """LRU eviction stays in the native owner and updates derived metadata."""
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"model")
    _install_predictor_stubs(monkeypatch)
    manager, runtime, backend = _manager(checkpoint, cache_limit=1)
    removed: list[uuid.UUID] = []
    manager.predictorRemoved.connect(removed.append)
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    manager.requestPredictor(_image(), first_id)
    backend.run_all()
    manager.requestPredictor(_image(), second_id)
    backend.run_all()
    assert manager.predictorImageIds() == [second_id]
    assert removed == [first_id]
    assert manager.snapshot_metrics().evictions == 1
    runtime.shutdown()


def test_clear_and_remove_are_serialized_cache_operations(
    monkeypatch,
    tmp_path,
) -> None:
    """Public cache mutations do not destroy predictors on the GUI thread."""
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"model")
    _install_predictor_stubs(monkeypatch)
    manager, runtime, backend = _manager(checkpoint)
    image_id = uuid.uuid4()
    manager.requestPredictor(_image(), image_id)
    backend.run_all()
    assert manager.removeFromCache(image_id)
    assert backend.pending_jobs()[0].operation == "editor.sam.cache.remove"
    backend.run_all()
    assert manager.getPredictor(image_id) is None
    manager.clearCache()
    backend.run_all()
    assert manager.getCachedPredictorCount() == 0
    runtime.shutdown()


def test_real_affinity_lane_preserves_thread_identity_through_cleanup(
    monkeypatch,
    tmp_path,
    qapp,
) -> None:
    """Construction, inference, and native destruction use one stable thread."""
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"model")
    events: list[tuple[str, int]] = []

    class _TrackedPredictor(_Predictor):
        """Record native lifetime thread identity."""

        def __init__(self) -> None:
            """Record construction."""
            super().__init__()
            events.append(("construct", threading.get_ident()))

        def __del__(self) -> None:
            """Record destruction."""
            events.append(("destroy", threading.get_ident()))

    monkeypatch.setattr(
        service,
        "load_predictor",
        lambda *_args, **_kwargs: _TrackedPredictor(),
    )
    monkeypatch.setattr(
        service,
        "set_predictor_image",
        lambda predictor, image: predictor.set_image(image),
    )

    def _predict(_predictor, _bbox):
        """Record inference."""
        events.append(("infer", threading.get_ident()))
        return np.ones((1, 1), dtype=bool)

    monkeypatch.setattr(service, "predict_mask_from_box", _predict)
    receiver = QObject()
    runtime = create_default_execution_runtime()
    scope = runtime.open_scope(
        owner_id="real-affinity",
        dispatcher=QtOwnerDispatcher(receiver),
    )
    manager = SamManager(
        parent=receiver,
        execution_scope=scope,
        checkpoint_path=checkpoint,
    )
    image_id = uuid.uuid4()
    manager.requestPredictor(_image(), image_id)
    _wait_until(qapp, lambda: manager.getCachedPredictorCount() == 1)
    manager.generateMaskFromBox(image_id, np.array([0, 0, 1, 1]))
    _wait_until(qapp, lambda: any(name == "infer" for name, _thread in events))
    manager.clearCache()
    _wait_until(qapp, lambda: manager.getCachedPredictorCount() == 0)
    _wait_until(qapp, lambda: any(name == "destroy" for name, _thread in events))
    native_threads = {thread_id for _name, thread_id in events}
    assert len(native_threads) == 1
    assert next(iter(native_threads)) != threading.get_ident()
    manager.shutdown()
    _wait_until(qapp, lambda: manager._execution_scope.is_closed)
    runtime.shutdown(wait=True)


def test_shutdown_schedules_native_cleanup_before_closing_scope(
    monkeypatch,
    tmp_path,
) -> None:
    """Manager teardown retains its scope until session cleanup settles."""
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"model")
    _install_predictor_stubs(monkeypatch)
    manager, runtime, backend = _manager(checkpoint)
    manager.shutdown()
    assert not manager._execution_scope.is_closed
    assert backend.pending_jobs()[0].operation == "editor.sam.session.close"
    backend.run_all()
    assert manager._execution_scope.is_closed
    runtime.shutdown()


def _wait_until(qapp, predicate, *, timeout: float = 2.0) -> None:
    """Process Qt events until one asynchronous condition becomes true."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition did not settle before timeout")
