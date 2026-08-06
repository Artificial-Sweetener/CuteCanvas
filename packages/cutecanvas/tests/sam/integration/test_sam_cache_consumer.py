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

"""Tests for SAM predictor cache consumer wiring."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from cutecanvas.sam.manager import SamManager
from cutecanvas_test_support.execution_backend import (
    ControllableAffinityExecutionBackend,
    ControllableExecutionBackend,
)
from PySide6.QtGui import QColor, QImage
from qpane.cache.consumers import KeyedCacheConsumer
from qpane.cache.coordinator import CacheCoordinator, CachePriority
from qpane.sdk.execution import ExecutionRuntime, InlineDispatcher


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


def _attach_consumer(manager, coordinator: CacheCoordinator) -> KeyedCacheConsumer:
    """Adapt a predictor cache through QPane's source-neutral cache contract."""

    def connect_usage_events(changed, cleared) -> None:
        manager.predictorReady.connect(lambda *_args: changed())
        manager.predictorRemoved.connect(lambda *_args: changed())
        manager.predictorCacheCleared.connect(cleared)

    return KeyedCacheConsumer(
        coordinator,
        consumer_id="predictors",
        priority=CachePriority.BACKGROUND_MODELS,
        get_usage=manager.cache_usage_bytes,
        set_admission_guard=lambda _guard: None,
        keys=lambda: tuple(manager.predictorImageIds()),
        remove=manager.removeFromCache,
        connect_usage_events=connect_usage_events,
    )


def test_predictor_consumer_tracks_only_resident_predictor_usage():
    """Pending work stays separate while ready predictors count as cache usage."""
    manager = _ManagerStub()
    coordinator = CacheCoordinator(512 * 1024 * 1024)
    _attach_consumer(manager, coordinator)
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
    _attach_consumer(manager, coordinator)
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
    affinity = ControllableAffinityExecutionBackend()
    runtime = ExecutionRuntime(
        ControllableExecutionBackend(),
        capability_backends=(affinity,),
    )
    scope = runtime.open_scope(
        owner_id="sam-cache-test",
        dispatcher=InlineDispatcher(),
    )
    manager = SamManager(
        execution_scope=scope,
        checkpoint_path=checkpoint,
    )
    coordinator = CacheCoordinator(0)
    _attach_consumer(manager, coordinator)
    image = QImage(16, 16, QImage.Format_ARGB32)
    image.fill(QColor("white"))
    image_id = uuid.uuid4()

    try:
        manager.requestPredictor(image, image_id, source_path=tmp_path / "image.png")

        assert manager.pendingUsageBytes() == 128 * 1024 * 1024
        assert affinity.pending_jobs()
        snapshot = coordinator.snapshot()
        assert snapshot["consumers"]["predictors"]["usage_bytes"] == 0
        assert "failed to trim below target" not in caplog.text
        assert "Cache remains over budget" not in caplog.text
    finally:
        manager.shutdown()
        affinity.run_all()
        runtime.shutdown()


def test_predictor_consumer_surfaces_injected_key_enumeration_failure(caplog):
    manager = _ManagerMissingHook()
    coordinator = CacheCoordinator(512 * 1024 * 1024)
    consumer = KeyedCacheConsumer(
        coordinator,
        consumer_id="predictors",
        priority=CachePriority.BACKGROUND_MODELS,
        get_usage=manager.cache_usage_bytes,
        set_admission_guard=lambda _guard: None,
        keys=lambda: (_ for _ in ()).throw(RuntimeError("key enumeration failed")),
        remove=manager.removeFromCache,
        connect_usage_events=lambda _changed, _cleared: None,
    )
    manager.cache_bytes = 8
    with pytest.raises(RuntimeError, match="key enumeration failed"):
        consumer._trim_to(0)
