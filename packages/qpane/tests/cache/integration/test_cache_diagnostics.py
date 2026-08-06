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

"""Tests for cache diagnostics formatting and fallbacks."""

from __future__ import annotations

from types import SimpleNamespace

from qpane.cache.diagnostics import (
    _build_aggregate_record,
    _bundle_metrics,
    _CacheMetricsBundle,
    _format_counters,
)


def test_build_aggregate_record_handles_zero_budget() -> None:
    """Zero budgets should emit a 0.0/0.0 MB aggregate row."""
    record = _build_aggregate_record({"budget_bytes": 0, "usage_bytes": 0})
    assert record is not None
    assert record.label == "Cache"
    assert record.value == "0.0/0.0 MB (0%)"


def test_build_aggregate_record_includes_headroom_and_swap() -> None:
    """Headroom fields should appear when both availability and swap data exist."""
    mb = 1024 * 1024
    record = _build_aggregate_record(
        {
            "budget_bytes": 4 * mb,
            "usage_bytes": 2 * mb,
            "hard_cap": True,
            "admissions_blocked": True,
            "headroom": {
                "available_bytes": 1 * mb,
                "total_bytes": 2 * mb,
                "swap_total_bytes": 4 * mb,
                "swap_free_bytes": 3 * mb,
            },
        }
    )
    assert record is not None
    assert "headroom 1.0/2.0 MB" in record.value
    assert "swap 3.0/4.0 MB" in record.value
    assert "(hard)" in record.value
    assert "admissions blocked" in record.value


def test_format_counters_includes_colorize_and_prefetch() -> None:
    """Counter formatting should include prefetch and colorize metadata."""
    bundle = _CacheMetricsBundle(
        hits=2,
        misses=1,
        evictions=3,
        pending_retries=4,
        prefetch_requested=5,
        prefetch_completed=3,
        prefetch_failed=1,
        last_prefetch_ms=12.5,
        colorize_last_ms=10.0,
        colorize_avg_ms=9.5,
        colorize_max_ms=20.0,
        colorize_samples=4,
        colorize_slow_count=2,
        colorize_threshold_ms=8.0,
        colorize_last_source="sam",
    )
    rendered = _format_counters(bundle)
    assert "hit=2" in rendered
    assert "miss=1" in rendered
    assert "evict=3" in rendered
    assert "retry=4" in rendered
    assert "prefetch=3/5" in rendered
    assert "prefetch_fail=1" in rendered
    assert "prefetch_ms=12" in rendered
    assert "colorize=10.0ms@sam" in rendered
    assert "avg=9.5ms" in rendered
    assert "max=20.0ms" in rendered
    assert "samples=4" in rendered
    assert "slow>8ms=2" in rendered


def test_bundle_metrics_logs_once_when_manager_missing(caplog, monkeypatch) -> None:
    """Missing managers should return an empty bundle and log once."""
    monkeypatch.setattr("qpane.cache.diagnostics._MISSING_DETAIL_MANAGER_LOGS", set())
    caplog.set_level("WARNING")
    qpane = SimpleNamespace()
    bundle = _bundle_metrics(qpane, "tiles")
    assert bundle == _CacheMetricsBundle()
    assert "missing manager" in caplog.text
