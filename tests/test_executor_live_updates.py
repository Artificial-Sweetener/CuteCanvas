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

"""Tests for live executor configuration updates."""

from qpane.concurrency import QThreadPoolExecutor, build_thread_policy


class _DummyPool:
    def __init__(self) -> None:
        self.max_threads = 0
        self.started = False
        self.waited = False

    def setMaxThreadCount(self, value: int) -> None:
        self.max_threads = int(value)

    def maxThreadCount(self) -> int:
        return int(self.max_threads)

    def start(self, *_args, **_kwargs) -> None:
        self.started = True

    def waitForDone(self) -> None:
        self.waited = True


def _make_executor(policy=None):
    pool = _DummyPool()
    dirty_calls: list[str] = []
    executor = QThreadPoolExecutor(policy=policy, pool=pool, name="dummy")
    executor.set_dirty_callback(lambda domain="executor": dirty_calls.append(domain))
    return executor, pool, dirty_calls


def test_set_max_workers_updates_policy_and_pool() -> None:
    policy = build_thread_policy({"max_workers": 4})
    executor, pool, dirty_calls = _make_executor(policy)
    executor.setMaxWorkers(7)
    snapshot = executor.snapshot()
    assert snapshot.max_workers == 7
    assert pool.max_threads == 7
    assert "executor" in dirty_calls


def test_pending_limits_update_live() -> None:
    executor, _pool, dirty_calls = _make_executor(
        build_thread_policy({"max_workers": 4, "max_pending_total": None})
    )
    executor.setPendingTotal(5)
    assert executor.snapshot().max_pending_total == 5
    executor.setPendingTotal(None)
    assert executor.snapshot().max_pending_total is None
    executor.setPendingLimits({"tiles": 2})
    snapshot = executor.snapshot()
    assert snapshot.pending_limits.get("tiles") == 2
    assert len(dirty_calls) >= 3


def test_category_and_device_limits_preserve_existing_entries() -> None:
    base_policy = build_thread_policy(
        {
            "max_workers": 4,
            "category_limits": {"pyramid": 2},
            "device_limits": {"cpu": {"sam": 2}},
        }
    )
    executor, _pool, _dirty_calls = _make_executor(base_policy)
    executor.setCategoryLimits({"tiles": 3})
    executor.setDeviceLimits({"cuda": {"sam": 4}})
    snapshot = executor.snapshot()
    assert snapshot.category_limits["pyramid"] == 2
    assert snapshot.category_limits["tiles"] == 3
    assert snapshot.device_limits["cpu"]["sam"] == 2
    assert snapshot.device_limits["cuda"]["sam"] == 4


def test_category_priorities_update_live() -> None:
    executor, _pool, _dirty_calls = _make_executor(
        build_thread_policy({"max_workers": 4, "category_priorities": {"tiles": 10}})
    )
    executor.setCategoryPriorities({"tiles": 5, "pyramid": 3})
    snapshot = executor.snapshot()
    assert snapshot.category_priorities["tiles"] == 5
    assert snapshot.category_priorities["pyramid"] == 3
