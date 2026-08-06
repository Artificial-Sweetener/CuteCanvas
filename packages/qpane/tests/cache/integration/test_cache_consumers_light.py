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

"""Lightweight tests for cache consumer trimming and sanitization helpers."""

from __future__ import annotations

import uuid

import pytest
from qpane.cache.consumers import (
    EvictableCacheConsumer,
    KeyedCacheConsumer,
    _run_cache_batch_trim,
    _safe_int,
)
from qpane.cache.coordinator import CacheCoordinator, CachePriority


class _CoordinatorStub(CacheCoordinator):
    """Coordinator subclass exposing update usage for testing."""


def test_run_cache_batch_trim_raises_when_hook_missing() -> None:
    """Missing batch hooks should surface a deterministic error."""
    with pytest.raises(RuntimeError, match="Missing cache trim hook"):
        _run_cache_batch_trim(
            consumer_id="tiles",
            get_usage=lambda: 10,
            batch=None,
            target=0,
            marker=None,
            missing_hook_label="tiles batch",
            warn_message="warn %s",
        )


def test_run_cache_batch_trim_caps_attempts(caplog) -> None:
    """Trims that never reduce usage should log after max attempts."""
    attempts: list[int] = []

    def _batch() -> None:
        attempts.append(1)

    caplog.set_level("WARNING")
    usage = _run_cache_batch_trim(
        consumer_id="tiles",
        get_usage=lambda: 10,
        batch=_batch,
        target=0,
        marker=None,
        missing_hook_label="tiles batch",
        warn_message="Trim failed %s %s %s %s",
        max_attempts=3,
    )
    assert attempts == [1, 1, 1]
    assert usage == 10
    assert "Trim failed" in caplog.text


def test_safe_int_logs_once_for_invalid_values(caplog, monkeypatch) -> None:
    """Invalid cache values should clamp to zero and log only once per label."""
    monkeypatch.setattr("qpane.cache.consumers._INVALID_VALUE_LOGGED", set())
    caplog.set_level("WARNING")
    assert _safe_int("bad", label="tiles") == 0
    assert _safe_int("bad", label="tiles") == 0
    warnings = [
        record for record in caplog.records if "Invalid cache metric" in record.message
    ]
    assert len(warnings) == 1


def test_mask_overlay_consumer_excludes_protected_working_set(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Protected active overlays must not be presented as evictable cache usage."""

    class _ControllerStub:
        def __init__(self) -> None:
            self.cache_usage_bytes = 10
            self.evictable_cache_usage_bytes = 0
            self.drop_calls: list[str] = []

        def drop_oldest(self, *, reason: str) -> int:
            self.drop_calls.append(reason)
            return 0

        def set_cache_usage_callback(self, callback) -> None:
            self._usage_callback = callback

        def set_admission_guard(self, guard) -> None:
            self._admission_guard = guard

    controller = _ControllerStub()
    coordinator = CacheCoordinator(active_budget_bytes=1024)
    consumer = EvictableCacheConsumer(
        controller,
        coordinator,
        consumer_id="mask_overlays",
        priority=CachePriority.DERIVED_OVERLAYS,
    )
    with caplog.at_level("WARNING"):
        consumer._trim_to(0)

    assert controller.drop_calls == []
    assert "failed to trim below target" not in caplog.text


def test_sam_predictor_consumer_trims_and_updates_usage() -> None:
    """SAM predictor trims should drop cache entries until usage meets target."""

    class _ManagerStub:
        def __init__(self) -> None:
            self._image_ids = [uuid.uuid4(), uuid.uuid4()]
            self._usage = 10

        def cache_usage_bytes(self) -> int:
            return self._usage

        def pendingUsageBytes(self) -> int:
            return 0

        def predictorImageIds(self):
            return list(self._image_ids)

        def removeFromCache(self, image_id: uuid.UUID) -> bool:
            if image_id in self._image_ids:
                self._image_ids.remove(image_id)
                self._usage = max(0, self._usage - 5)
                return True
            return False

        def requestPredictor(
            self, image, image_id: uuid.UUID, *, source_path=None
        ) -> None:
            return None

        def cancelPendingPredictor(self, image_id: uuid.UUID) -> bool:
            return False

        class _Signal:
            def connect(self, _callback) -> None:
                return None

        predictorReady = _Signal()
        predictorCacheCleared = _Signal()
        predictorRemoved = _Signal()

    manager = _ManagerStub()
    coordinator = CacheCoordinator(active_budget_bytes=1024)
    KeyedCacheConsumer(
        coordinator,
        consumer_id="predictors",
        priority=CachePriority.BACKGROUND_MODELS,
        get_usage=manager.cache_usage_bytes,
        set_admission_guard=lambda _guard: None,
        keys=lambda: tuple(manager.predictorImageIds()),
        remove=manager.removeFromCache,
        connect_usage_events=lambda _changed, _cleared: None,
    )
    coordinator.set_active_budget(0)
    snapshot = coordinator.snapshot()
    assert snapshot["consumers"]["predictors"]["usage_bytes"] == 0
