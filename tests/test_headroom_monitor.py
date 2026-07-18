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

"""Tests for the Auto-mode headroom monitor."""

from __future__ import annotations

from qpane import QPane

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


def test_headroom_monitor_updates_budget_and_snapshot(qapp) -> None:
    qpane_widget = QPane(features=())
    try:
        state = qpane_widget._state
        state._headroom_psutil_module = _FakePsutil
        state._headroom_psutil_missing = False
        state._restart_headroom_monitor()
        state._headroom_tick()
        expected_budget = 7 * MB
        assert qpane_widget.cacheCoordinator.active_budget_bytes == expected_budget
        snapshot = qpane_widget.cacheCoordinator.snapshot().get("headroom") or {}
        assert snapshot.get("available_bytes") == 8 * MB
        assert snapshot.get("total_bytes") == 10 * MB
        assert snapshot.get("swap_total_bytes") == 4 * MB
        assert snapshot.get("swap_free_bytes") == 3 * MB
    finally:
        qpane_widget.deleteLater()
        qapp.processEvents()


def test_headroom_monitor_stops_in_hard_mode(qapp) -> None:
    qpane_widget = QPane(features=())
    try:
        qpane_widget.applySettings(cache={"mode": "hard"})
        state = qpane_widget._state
        state._restart_headroom_monitor()
        timer = state._headroom_timer
        assert timer is None or not timer.isActive()
    finally:
        qpane_widget.deleteLater()
        qapp.processEvents()


def test_headroom_monitor_falls_back_when_psutil_missing(qapp) -> None:
    qpane_widget = QPane(features=())
    try:
        state = qpane_widget._state
        state._headroom_psutil_module = _FailingPsutil
        state._headroom_psutil_missing = False
        state._restart_headroom_monitor()
        state._headroom_tick()
        coordinator = qpane_widget.cacheCoordinator
        assert coordinator is not None
        assert coordinator.active_budget_bytes == 1024 * MB
        assert coordinator.snapshot().get("hard_cap") is True
        assert coordinator.should_admit(2048 * MB) is False
        timer = state._headroom_timer
        assert timer is None or not timer.isActive()
    finally:
        qpane_widget.deleteLater()
        qapp.processEvents()


def test_headroom_monitor_trims_when_headroom_shrinks(qapp) -> None:
    """Auto mode trims when usage exceeds the capacity after headroom recalc."""
    qpane_widget = QPane(features=())
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
        state._headroom_psutil_module = _LowHeadroomPsutil
        state._headroom_psutil_missing = False
        state._restart_headroom_monitor()
        # Re-assert the test psutil module after restart to avoid any resets.
        state._headroom_psutil_module = _LowHeadroomPsutil
        state._headroom_tick()
        snapshot_after = coordinator.snapshot()
        headroom = snapshot_after.get("headroom", {})
        assert headroom.get("available_bytes") == 4 * MB
        assert headroom.get("total_bytes") == 10 * MB
        # Budget should track available-minus-headroom and trims should fire.
        assert coordinator.active_budget_bytes == 3 * MB
        tiles_after = snapshot_after["consumers"]["tiles"]
        assert tiles_after["usage_bytes"] <= coordinator.active_budget_bytes
        assert trim_calls, "Expected a trim when usage exceeds recomputed capacity"
        assert any(reason == "global" for _, _, reason in trim_calls)
    finally:
        coordinator._trim_consumer_to = original_trim  # type: ignore[assignment]
        qpane_widget.deleteLater()
        qapp.processEvents()
