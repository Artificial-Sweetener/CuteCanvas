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

"""Tests for the Auto-mode headroom monitor."""

from __future__ import annotations

import time
from threading import Event

from cutecanvas import CuteCanvas
from cutecanvas_test_support.harness.timing import interaction_clock
from qpane.core import headroom
from qpane.execution import CancellationToken

MB = 1024 * 1024


class _FakePsutil:
    class _VM:
        total = 10 * MB
        available = 8 * MB

    class _Swap:
        total = 4 * MB
        free = 3 * MB

    @staticmethod
    def virtual_memory():
        return _FakePsutil._VM()

    @staticmethod
    def swap_memory():
        return _FakePsutil._Swap()


class _FailingPsutil:
    @staticmethod
    def virtual_memory():
        raise RuntimeError("psutil missing")


def test_default_headroom_sampling_prefers_native_windows_observation(
    monkeypatch,
) -> None:
    """Use the bounded native observation before optional system libraries."""

    expected = headroom.SystemHeadroomSample(
        available_bytes=8 * MB,
        total_bytes=10 * MB,
        swap_total_bytes=4 * MB,
        swap_free_bytes=3 * MB,
    )
    monkeypatch.setattr(headroom, "_sample_windows_headroom", lambda: expected)

    assert headroom.sample_system_headroom(CancellationToken()) == expected


def _wait_until(qapp, predicate, *, timeout_seconds: float = 2.0) -> None:
    """Process queued Qt work until one asynchronous assertion is ready."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.001)
    qapp.processEvents()
    assert predicate(), "asynchronous headroom work did not settle"


def test_headroom_monitor_updates_budget_and_snapshot(qapp) -> None:
    qpane_widget = CuteCanvas(features=())
    try:
        monitor = qpane_widget._state._headroom
        monitor.set_provider(_FakePsutil)
        monitor.restart()
        monitor.sample()
        expected_budget = 7 * MB
        _wait_until(
            qapp,
            lambda: (
                qpane_widget.cacheCoordinator.active_budget_bytes == expected_budget
            ),
        )
        assert qpane_widget.cacheCoordinator.active_budget_bytes == expected_budget
        snapshot = qpane_widget.cacheCoordinator.snapshot().get("headroom") or {}
        assert snapshot.get("available_bytes") == 8 * MB
        assert snapshot.get("total_bytes") == 10 * MB
        assert snapshot.get("swap_total_bytes") == 4 * MB
        assert snapshot.get("swap_free_bytes") == 3 * MB
    finally:
        qpane_widget.deleteLater()
        qapp.processEvents()


def test_headroom_monitor_limits_caches_when_windows_commit_is_contended(qapp) -> None:
    """Commit exhaustion must trigger relief even while physical RAM is abundant."""

    class _CommitContendedProvider:
        class _VM:
            total = 100 * MB
            available = 80 * MB

        class _Swap:
            total = 20 * MB
            free = 2 * MB

        @staticmethod
        def virtual_memory():
            return _CommitContendedProvider._VM()

        @staticmethod
        def swap_memory():
            return _CommitContendedProvider._Swap()

    qpane_widget = CuteCanvas(features=())
    try:
        coordinator = qpane_widget.cacheCoordinator
        assert coordinator is not None
        monitor = qpane_widget._state._headroom
        monitor.set_provider(_CommitContendedProvider)
        sample = headroom.SystemHeadroomSample(
            available_bytes=80 * MB,
            total_bytes=100 * MB,
            swap_total_bytes=20 * MB,
            swap_free_bytes=2 * MB,
            commit_limit_bytes=120 * MB,
            commit_available_bytes=2 * MB,
        )
        monitor._adopt(sample)

        assert coordinator.active_budget_bytes == 0
        snapshot = coordinator.snapshot().get("headroom") or {}
        assert snapshot["commit_limit_bytes"] == 120 * MB
        assert snapshot["commit_available_bytes"] == 2 * MB
    finally:
        qpane_widget.deleteLater()
        qapp.processEvents()


def test_headroom_monitor_stops_in_hard_mode(qapp) -> None:
    qpane_widget = CuteCanvas(features=())
    try:
        qpane_widget.applySettings(cache={"mode": "hard"})
        monitor = qpane_widget._state._headroom
        monitor.restart()
        assert not monitor.timer.isActive()
    finally:
        qpane_widget.deleteLater()
        qapp.processEvents()


def test_headroom_monitor_falls_back_when_psutil_missing(qapp) -> None:
    qpane_widget = CuteCanvas(features=())
    try:
        monitor = qpane_widget._state._headroom
        monitor.set_provider(_FailingPsutil)
        monitor.restart()
        monitor.sample()
        coordinator = qpane_widget.cacheCoordinator
        assert coordinator is not None
        _wait_until(qapp, lambda: coordinator.snapshot().get("hard_cap") is True)
        assert coordinator.active_budget_bytes == 1024 * MB
        assert coordinator.snapshot().get("hard_cap") is True
        assert coordinator.should_admit(2048 * MB) is False
        assert not monitor.timer.isActive()
    finally:
        qpane_widget.deleteLater()
        qapp.processEvents()


def test_headroom_monitor_trims_when_headroom_shrinks(qapp) -> None:
    """Auto mode trims when usage exceeds the capacity after headroom recalc."""
    qpane_widget = CuteCanvas(features=())
    try:
        state = qpane_widget._state
        coordinator = qpane_widget.cacheCoordinator
        assert coordinator is not None

        # Give tiles the full temporary budget so the pre-tick usage is not trimmed.
        for consumer_id in ("pyramids", "mask_overlays", "predictors"):
            coordinator.set_consumer_weight(consumer_id, 0.0)
        coordinator.set_consumer_weight("tiles", 1.0)
        coordinator.set_active_budget(50 * MB)

        class _LowHeadroomPsutil:
            class _VM:
                total = 10 * MB
                available = 4 * MB

            class _Swap:
                total = 0
                free = 0

            @staticmethod
            def virtual_memory():
                return _LowHeadroomPsutil._VM()

            @staticmethod
            def swap_memory():
                return _LowHeadroomPsutil._Swap()

        trim_calls: list[tuple[str, int, str]] = []
        original_trim = coordinator._trim_consumer_to

        def _recording_trim(state_obj, target, *, reason):
            trim_calls.append((getattr(state_obj, "consumer_id", ""), target, reason))
            return original_trim(state_obj, target, reason=reason)

        coordinator._trim_consumer_to = _recording_trim  # type: ignore[assignment]
        # Set usage above the capacity (total - headroom = 9MB) to force a trim.
        coordinator.update_usage("tiles", 12 * MB)
        snapshot_before = coordinator.snapshot()
        assert (
            snapshot_before["consumers"]["tiles"]["usage_bytes"] == 12 * MB
        ), "pre-tick usage should remain high so headroom tick can trim it"
        assert (
            coordinator.total_usage_bytes == 12 * MB
        ), "total_usage_bytes should reflect the pre-tick usage"
        monitor = state._headroom
        monitor.set_provider(_LowHeadroomPsutil)
        monitor.restart()
        monitor.sample()
        _wait_until(
            qapp,
            lambda: (
                (coordinator.snapshot().get("headroom") or {}).get("available_bytes")
                == 4 * MB
            ),
        )
        snapshot_after = coordinator.snapshot()
        headroom = snapshot_after.get("headroom", {})
        assert headroom.get("available_bytes") == 4 * MB
        assert headroom.get("total_bytes") == 10 * MB
        # The cache can reclaim no more than physical capacity after headroom.
        assert coordinator.active_budget_bytes == 9 * MB
        tiles_after = snapshot_after["consumers"]["tiles"]
        assert tiles_after["usage_bytes"] <= coordinator.active_budget_bytes
        assert trim_calls, "Expected a trim when usage exceeds recomputed capacity"
        assert any(reason == "global" for _, _, reason in trim_calls)
    finally:
        coordinator._trim_consumer_to = original_trim  # type: ignore[assignment]
        qpane_widget.deleteLater()
        qapp.processEvents()


def test_headroom_monitor_never_waits_for_system_observation(qapp) -> None:
    """A stalled OS-memory query must not consume the GUI interaction budget."""

    class _SlowPsutil:
        started = Event()
        release = Event()

        class _VM:
            total = 10 * MB
            available = 8 * MB

        class _Swap:
            total = 0
            free = 0

        @classmethod
        def virtual_memory(cls):
            cls.started.set()
            cls.release.wait(timeout=2.0)
            return cls._VM()

        @classmethod
        def swap_memory(cls):
            return cls._Swap()

    qpane_widget = CuteCanvas(features=())
    try:
        monitor = qpane_widget._state._headroom
        monitor.set_provider(_SlowPsutil)
        monitor.restart()
        started = interaction_clock()
        monitor.sample()
        submission_ms = (interaction_clock() - started) * 1000.0
        assert submission_ms < 16.0
        assert _SlowPsutil.started.wait(timeout=1.0)
        assert monitor.pending is not None
        _SlowPsutil.release.set()
        _wait_until(qapp, lambda: monitor.pending is None)
        assert qpane_widget.cacheCoordinator.active_budget_bytes == 7 * MB
    finally:
        _SlowPsutil.release.set()
        qpane_widget.deleteLater()
        qapp.processEvents()
