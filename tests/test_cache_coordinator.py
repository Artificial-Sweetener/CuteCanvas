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

"""Tests for cache coordinator budgeting and trimming."""

from __future__ import annotations

import logging

import pytest
from cutecanvas import Config
from cutecanvas.core.config_features import MaskConfigSlice
from cutecanvas.masks.live_preview_store import MaskLivePreviewStore
from cutecanvas.masks.mask import MaskAssetStore
from cutecanvas.masks.mask_controller import MaskController
from cutecanvas.resources import ProjectResourceStore
from PySide6.QtGui import QImage, Qt
from qpane.cache.consumers import EvictableCacheConsumer
from qpane.cache.coordinator import (
    CacheConsumerCallbacks,
    CacheCoordinator,
    CachePriority,
)

from tests.helpers.config import fixed_cache_config

MB = 1024 * 1024


class FakeConsumer:
    def __init__(self, usage: int) -> None:
        self.usage = usage
        self.budget = usage
        self.trim_history: list[int] = []

    def callbacks(self) -> CacheConsumerCallbacks:
        return CacheConsumerCallbacks(
            get_usage=lambda: self.usage,
            set_budget=self._set_budget,
            trim_to=self._trim_to,
        )

    def _set_budget(self, target: int) -> None:
        self.budget = target

    def _trim_to(self, target: int) -> None:
        self.trim_history.append(target)
        self.usage = min(self.usage, target)


def test_coordinator_enforces_priority_order():
    coordinator = CacheCoordinator(active_budget_bytes=100)
    predictors = FakeConsumer(usage=80)
    masks = FakeConsumer(usage=40)
    tiles = FakeConsumer(usage=30)
    pyramids = FakeConsumer(usage=20)
    coordinator.register_consumer(
        "predictors",
        priority=CachePriority.BACKGROUND_MODELS,
        callbacks=predictors.callbacks(),
    )
    coordinator.register_consumer(
        "masks",
        priority=CachePriority.DERIVED_OVERLAYS,
        callbacks=masks.callbacks(),
    )
    coordinator.register_consumer(
        "tiles",
        priority=CachePriority.TILES,
        callbacks=tiles.callbacks(),
    )
    coordinator.register_consumer(
        "pyramids",
        priority=CachePriority.PYRAMIDS,
        callbacks=pyramids.callbacks(),
    )
    coordinator.update_usage("predictors", 80)
    coordinator.update_usage("masks", 40)
    coordinator.update_usage("tiles", 30)
    coordinator.update_usage("pyramids", 20)
    assert predictors.trim_history, "Predictors should trim first by overage"
    assert predictors.usage <= predictors.budget
    total_usage = (  # ensure overall budget respected
        predictors.usage + masks.usage + tiles.usage + pyramids.usage
    )
    assert total_usage <= coordinator.active_budget_bytes


def test_has_consumer_reflects_registration():
    coordinator = CacheCoordinator(active_budget_bytes=0)
    consumer = FakeConsumer(usage=0)
    assert not coordinator.has_consumer("tiles")
    coordinator.register_consumer(
        "tiles",
        priority=CachePriority.TILES,
        callbacks=consumer.callbacks(),
    )
    assert coordinator.has_consumer("tiles")


def test_usage_notification_during_trim_does_not_reenter_enforcement() -> None:
    """Synchronous trim notifications must not recursively enforce the budget."""
    coordinator = CacheCoordinator(active_budget_bytes=0)
    usage = 0
    trim_calls = 0

    def trim_to(_target: int) -> None:
        """Report unchanged usage once, then expose any recursive retry."""
        nonlocal trim_calls
        trim_calls += 1
        if trim_calls > 1:
            raise RuntimeError("recursive enforcement")
        coordinator.update_usage("cache", usage)

    coordinator.register_consumer(
        "cache",
        priority=CachePriority.TILES,
        callbacks=CacheConsumerCallbacks(
            get_usage=lambda: usage,
            set_budget=lambda _target: None,
            trim_to=trim_to,
        ),
    )

    usage = 10
    coordinator.update_usage("cache", usage)

    assert trim_calls == 1


def test_consumer_override_updates_budget():
    coordinator = CacheCoordinator(active_budget_bytes=200)
    consumer = FakeConsumer(usage=150)
    coordinator.register_consumer(
        "tiles",
        priority=CachePriority.TILES,
        callbacks=consumer.callbacks(),
    )
    coordinator.update_usage("tiles", 150)
    coordinator.set_consumer_override("tiles", 80)
    coordinator.update_usage("tiles", consumer.usage)
    assert consumer.budget == 80
    assert consumer.usage <= 80


def test_trim_emits_structured_payload(monkeypatch):
    captured: list[dict[str, object] | None] = []

    def _capture_info(*_args, **kwargs) -> None:
        captured.append(kwargs.get("extra"))

    monkeypatch.setattr("qpane.cache.coordinator.logger.info", _capture_info)
    coordinator = CacheCoordinator(active_budget_bytes=100)
    heavy = FakeConsumer(usage=80)
    secondary = FakeConsumer(usage=40)
    coordinator.register_consumer(
        "heavy",
        priority=CachePriority.BACKGROUND_MODELS,
        callbacks=heavy.callbacks(),
    )
    assert not captured
    coordinator.register_consumer(
        "secondary",
        priority=CachePriority.PYRAMIDS,
        callbacks=secondary.callbacks(),
    )
    assert heavy.trim_history == [50]
    payloads = [item for item in captured if item and "cache_trim" in item]
    assert payloads, "Expected structured cache trim payload"
    last_payload = payloads[-1]["cache_trim"]
    assert last_payload["budget_bytes"] == coordinator.active_budget_bytes
    assert last_payload["events"], "structured events missing"
    trimmed_consumers = {event["consumer"] for event in last_payload["events"]}
    assert "heavy" in trimmed_consumers
    for event in last_payload["events"]:
        assert "entitlement_bytes" in event
        assert "overage_bytes" in event


def test_weighted_contention_orders_by_overage_then_priority(monkeypatch):
    captured: list[dict[str, object] | None] = []

    def _capture_info(*_args, **kwargs) -> None:
        captured.append(kwargs.get("extra"))

    monkeypatch.setattr("qpane.cache.coordinator.logger.info", _capture_info)
    coordinator = CacheCoordinator(active_budget_bytes=100)
    heavy_weight = FakeConsumer(usage=80)
    mid_weight = FakeConsumer(usage=70)
    light_weight = FakeConsumer(usage=60)
    coordinator.register_consumer(
        "heavy",
        priority=CachePriority.BACKGROUND_MODELS,
        callbacks=heavy_weight.callbacks(),
        weight=3.0,
    )
    coordinator.register_consumer(
        "mid",
        priority=CachePriority.DERIVED_OVERLAYS,
        callbacks=mid_weight.callbacks(),
        weight=1.0,
    )
    coordinator.register_consumer(
        "light",
        priority=CachePriority.TILES,
        callbacks=light_weight.callbacks(),
        weight=1.0,
    )
    coordinator.update_usage("heavy", heavy_weight.usage)
    coordinator.update_usage("mid", mid_weight.usage)
    coordinator.update_usage("light", light_weight.usage)
    last_payload = None
    for item in captured:
        if item and "cache_trim" in item:
            last_payload = item["cache_trim"]
    assert last_payload, "Expected trim payload from weighted contention"
    events = last_payload["events"]
    assert len(events) >= 3
    overages = [event["overage_bytes"] for event in events]
    assert overages == sorted(
        overages, reverse=True
    ), "Events should be ordered by overage"
    assert mid_weight.usage <= 20
    assert light_weight.usage <= 20
    assert heavy_weight.usage <= 60


def test_allows_borrowing_when_within_budget():
    coordinator = CacheCoordinator(active_budget_bytes=100)
    primary = FakeConsumer(usage=90)
    secondary = FakeConsumer(usage=5)
    coordinator.register_consumer(
        "primary",
        priority=CachePriority.BACKGROUND_MODELS,
        callbacks=primary.callbacks(),
        weight=3.0,
    )
    coordinator.register_consumer(
        "secondary",
        priority=CachePriority.DERIVED_OVERLAYS,
        callbacks=secondary.callbacks(),
        weight=1.0,
    )
    coordinator.update_usage("primary", primary.usage)
    coordinator.update_usage("secondary", secondary.usage)
    assert not primary.trim_history
    assert not secondary.trim_history
    assert primary.usage == 90
    assert secondary.usage == 5


def test_unbounded_consumer_can_borrow_the_global_budget_and_follow_growth() -> None:
    """A shared cache without a private target must use the global capacity."""
    coordinator = CacheCoordinator(active_budget_bytes=100)
    consumer = FakeConsumer(usage=0)
    coordinator.register_consumer(
        "shared",
        priority=CachePriority.VECTOR_PRODUCTS,
        callbacks=consumer.callbacks(),
    )

    assert consumer.budget == 100

    coordinator.set_active_budget(240)

    assert consumer.budget == 240


def test_idle_consumers_do_not_reserve_cache_entitlement() -> None:
    """Zero-usage caches must not force active rendering data out of memory."""
    coordinator = CacheCoordinator(active_budget_bytes=100)
    active = FakeConsumer(usage=100)
    idle = FakeConsumer(usage=0)
    coordinator.register_consumer(
        "active",
        priority=CachePriority.VECTOR_PRODUCTS,
        callbacks=active.callbacks(),
    )
    coordinator.register_consumer(
        "idle",
        priority=CachePriority.VECTOR_PRODUCTS,
        callbacks=idle.callbacks(),
    )

    coordinator.update_usage("active", active.usage)

    assert active.usage == 100
    assert not active.trim_history
    snapshot = coordinator.snapshot()
    assert snapshot["consumers"]["active"]["entitlement_bytes"] == 100
    assert snapshot["consumers"]["idle"]["entitlement_bytes"] == 0


def test_global_pressure_trim_restores_borrowing_capacity() -> None:
    """Pressure may evict allocations without permanently shrinking caches."""
    coordinator = CacheCoordinator(active_budget_bytes=100)
    first = FakeConsumer(usage=0)
    second = FakeConsumer(usage=0)
    coordinator.register_consumer(
        "first",
        priority=CachePriority.VECTOR_PRODUCTS,
        callbacks=first.callbacks(),
    )
    coordinator.register_consumer(
        "second",
        priority=CachePriority.VECTOR_PRODUCTS,
        callbacks=second.callbacks(),
    )

    first.usage = 80
    coordinator.update_usage("first", first.usage)
    second.usage = 80
    coordinator.update_usage("second", second.usage)

    assert first.usage + second.usage <= 100
    assert first.budget == 100
    assert second.budget == 100


def test_trim_handles_reentrant_usage_updates():
    coordinator = CacheCoordinator(active_budget_bytes=50)

    class ReentrantConsumer:
        def __init__(self) -> None:
            self.usage = 100
            self.budget = None
            self.trim_calls = 0
            self.notify_calls = 0

        def callbacks(self) -> CacheConsumerCallbacks:
            return CacheConsumerCallbacks(
                get_usage=self._get_usage,
                set_budget=self._set_budget,
                trim_to=self._trim_to,
            )

        def _get_usage(self) -> int:
            return self.usage

        def _set_budget(self, target: int) -> None:
            self.budget = target

        def _trim_to(self, target: int) -> None:
            self.trim_calls += 1
            self.usage = min(self.usage, target)
            self.notify_calls += 1
            coordinator.update_usage("reentrant", self.usage)

    consumer = ReentrantConsumer()
    coordinator.register_consumer(
        "reentrant",
        priority=CachePriority.BACKGROUND_MODELS,
        callbacks=consumer.callbacks(),
    )
    snapshot = coordinator.snapshot()
    assert snapshot["consumers"]["reentrant"]["usage_bytes"] == 50
    assert consumer.budget == 50
    assert consumer.trim_calls == 1
    assert consumer.notify_calls == 1


@pytest.mark.usefixtures("qapp")
def test_mask_overlay_consumer_uses_controller_callback():
    manager = MaskAssetStore(ProjectResourceStore())
    controller = MaskController(
        manager,
        lambda pt: pt,
        fixed_cache_config(),
        mask_config=MaskConfigSlice(),
        live_previews=MaskLivePreviewStore(),
    )
    coordinator = CacheCoordinator(active_budget_bytes=8 * 1024 * 1024)
    consumer = EvictableCacheConsumer(
        controller.renders,
        coordinator,
        consumer_id="mask_overlays",
        priority=CachePriority.DERIVED_OVERLAYS,
    )
    assert getattr(controller.renders._get, "__name__", "") == "_get"
    mask_image = QImage(8, 8, QImage.Format_Grayscale8)
    mask_image.fill(Qt.white)
    mask_id = manager.create_mask(mask_image)
    layer = manager.get_layer(mask_id)
    assert layer is not None
    layer.coverage.raster.fill(Qt.white)
    assert controller.renders.get(layer) is not None
    snapshot = coordinator.snapshot()
    usage = snapshot["consumers"]["mask_overlays"]["usage_bytes"]
    assert usage > 0
    controller.renders.clear()
    snapshot_after = coordinator.snapshot()
    assert snapshot_after["consumers"]["mask_overlays"]["usage_bytes"] == 0
    assert consumer is not None


@pytest.mark.usefixtures("qapp")
def test_mask_guard_rejects_oversized_item(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Mask overlays that exceed the hard budget should not be cached."""
    manager = MaskAssetStore(ProjectResourceStore())
    controller = MaskController(
        manager,
        lambda pt: pt,
        Config(
            cache={
                "mode": "hard",
                "budget_mb": 1,
                "weights": {
                    "tiles": 0,
                    "pyramids": 0,
                    "extensions": {"mask_overlays": 1, "models": 0},
                },
            }
        ),
        mask_config=MaskConfigSlice(),
        live_previews=MaskLivePreviewStore(),
    )
    mask_image = QImage(128, 128, QImage.Format_Grayscale8)
    mask_image.fill(Qt.white)
    mask_id = manager.create_mask(mask_image)
    layer = manager.get_layer(mask_id)
    assert layer is not None
    oversized = QImage(800, 800, QImage.Format_ARGB32)
    oversized.fill(Qt.white)
    with caplog.at_level(logging.WARNING):
        controller.renders.commit_prefetched(mask_id, layer, oversized)
        controller.renders.commit_prefetched(mask_id, layer, oversized)
    assert controller.renders.cache_usage_bytes == 0
    warnings = [record for record in caplog.records if "not cached" in record.message]
    assert len(warnings) == 1


def test_hard_cap_rejects_admission_when_over_budget() -> None:
    """Hard mode should refuse new items that would exceed the global budget."""
    coordinator = CacheCoordinator(active_budget_bytes=MB)
    coordinator.set_hard_cap(True)
    consumer = FakeConsumer(usage=MB - 100_000)
    coordinator.register_consumer(
        "tiles",
        priority=CachePriority.TILES,
        callbacks=consumer.callbacks(),
    )
    coordinator.update_usage("tiles", consumer.usage)
    assert coordinator.should_admit(200_000) is False
    assert coordinator.should_admit(50_000) is True
