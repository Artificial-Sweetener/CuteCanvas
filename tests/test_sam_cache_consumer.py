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

"""Tests for SAM predictor cache consumer wiring."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from PySide6.QtGui import QColor, QImage

from qpane.cache.consumers import SamPredictorCacheConsumer
from qpane.cache.coordinator import CacheCoordinator
from qpane.sam.manager import SamManager
from tests.helpers.executor_stubs import StubExecutor


class _Signal:
    """Lightweight signal stub to mimic Qt connect/emit semantics."""

    def __init__(self) -> None:
        self._callbacks: list[Callable[..., None]] = []

    def connect(self, callback: Callable[..., None]) -> None:
        self._callbacks.append(callback)

    def emit(self, *args, **kwargs) -> None:
        for callback in list(self._callbacks):
            callback(*args, **kwargs)


class _ManagerStub:
    """Minimal manager facade exposing predictor hooks used by the consumer."""

    def __init__(self) -> None:
        self.request_calls: list[tuple[object, uuid.UUID, object]] = []
        self.cache_bytes = 0
        self.pending_bytes = 0
        self.predictor_id_queries = 0
        self.release_pending_after_queries: int | None = None
        self._sam_predictors: dict[uuid.UUID, object] = {}
        self.predictorReady = _Signal()
        self.predictorCacheCleared = _Signal()
        self.predictorRemoved = _Signal()

    def requestPredictor(self, image, image_id: uuid.UUID, *, source_path=None) -> None:
        self.request_calls.append((image, image_id, source_path))

    def cache_usage_bytes(self) -> int:
        return self.cache_bytes

    def pendingUsageBytes(self) -> int:
        return self.pending_bytes

    def predictorImageIds(self) -> list[uuid.UUID]:
        self.predictor_id_queries += 1
        if (
            self.release_pending_after_queries is not None
            and self.predictor_id_queries >= self.release_pending_after_queries
        ):
            self.pending_bytes = 0
        return list(self._sam_predictors.keys())

    def cancelPendingPredictor(self, image_id: uuid.UUID) -> bool:
        return False

    def removeFromCache(self, image_id: uuid.UUID) -> bool:
        self._sam_predictors.pop(image_id, None)
        self.cache_bytes = 0
        return True


class _ManagerMissingHook(_ManagerStub):
    """Manager stub that omits a required hook to simulate miswiring."""

    def __init__(self) -> None:
        super().__init__()
        self.cancelPendingPredictor = None


def test_predictor_consumer_tracks_only_resident_predictor_usage():
    """Pending work stays separate while ready predictors count as cache usage."""
    manager = _ManagerStub()
    coordinator = CacheCoordinator(512 * 1024 * 1024)
    SamPredictorCacheConsumer(manager, coordinator)
    image_id = uuid.uuid4()
    manager.pending_bytes = 4096
    manager.cache_bytes = 0
    manager.requestPredictor(None, image_id, source_path=None)  # wrapped by consumer
    snapshot = coordinator.snapshot()
    assert snapshot["consumers"]["predictors"]["usage_bytes"] == 0
    manager.pending_bytes = 0
    manager.cache_bytes = 2048
    manager._sam_predictors[image_id] = object()
    manager.predictorReady.emit(object(), image_id)
    snapshot = coordinator.snapshot()
    assert snapshot["consumers"]["predictors"]["usage_bytes"] == 2048
    coordinator.set_active_budget(0)
    snapshot = coordinator.snapshot()
    assert snapshot["consumers"]["predictors"]["usage_bytes"] == 0


def test_pending_predictor_is_not_treated_as_evictable_cache_usage(caplog) -> None:
    """Pending predictor work must not enter resident-cache enforcement."""
    manager = _ManagerStub()
    coordinator = CacheCoordinator(0)
    SamPredictorCacheConsumer(manager, coordinator)
    manager.pending_bytes = 128 * 1024 * 1024
    manager.release_pending_after_queries = 2

    manager.requestPredictor(None, uuid.uuid4(), source_path=None)

    snapshot = coordinator.snapshot()
    assert snapshot["consumers"]["predictors"]["usage_bytes"] == 0
    assert manager.predictor_id_queries == 0
    assert "failed to trim below target" not in caplog.text
    assert "Cache remains over budget" not in caplog.text


def test_real_manager_pending_request_stays_outside_cache_budget(
    qapp, tmp_path, caplog
) -> None:
    """The production manager contract keeps in-flight work out of cache usage."""
    checkpoint = tmp_path / "sam-checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    executor = StubExecutor()
    manager = SamManager(executor=executor, checkpoint_path=checkpoint)
    coordinator = CacheCoordinator(0)
    SamPredictorCacheConsumer(manager, coordinator)
    image = QImage(16, 16, QImage.Format_ARGB32)
    image.fill(QColor("white"))
    image_id = uuid.uuid4()

    try:
        manager.requestPredictor(image, image_id, source_path=tmp_path / "image.png")

        assert manager.pendingUsageBytes() == 128 * 1024 * 1024
        assert list(executor.pending_tasks())
        snapshot = coordinator.snapshot()
        assert snapshot["consumers"]["predictors"]["usage_bytes"] == 0
        assert "failed to trim below target" not in caplog.text
        assert "Cache remains over budget" not in caplog.text
    finally:
        manager.shutdown()


def test_predictor_consumer_errors_when_required_hook_missing(caplog):
    manager = _ManagerMissingHook()
    coordinator = CacheCoordinator(512 * 1024 * 1024)
    with (
        caplog.at_level("ERROR"),
        pytest.raises(RuntimeError, match="cancelPendingPredictor"),
    ):
        SamPredictorCacheConsumer(manager, coordinator)
    assert (
        "Cannot wrap missing manager hook _ManagerMissingHook.cancelPendingPredictor"
        in caplog.text
    )
