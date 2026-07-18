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

"""Tests covering concurrency policy normalization utilities."""

from __future__ import annotations

import pytest

from qpane.concurrency.thread_policy import build_thread_policy


def test_build_thread_policy_merges_overrides() -> None:
    """ThreadPolicy should deep-merge nested override mappings."""
    base = {
        "max_workers": 4,
        "max_pending_total": 10,
        "category_priorities": {"pyramid": 1},
        "category_limits": {"tiles": 2},
        "pending_limits": {"tiles": 3},
        "device_limits": {"cuda": {"sam": 1}},
    }
    policy = build_thread_policy(
        base,
        max_pending_total=12,
        category_priorities={"tiles": 5, "io": 2},
        pending_limits={"pyramid": 6},
        device_limits={"cuda": {"sam": 2, "tiles": 1}},
    )
    assert policy.max_workers == 4
    assert policy.max_pending_total == 12
    assert policy.pending_limits == {"tiles": 3, "pyramid": 6}
    assert policy.priority_for("pyramid") == 1
    assert policy.priority_for("tiles") == 5
    assert policy.limit_for("tiles") == 2
    assert policy.limit_for("sam") is None
    assert policy.device_limit("cuda", "sam") == 2
    assert policy.device_limit("cuda", "tiles") == 1


def test_build_thread_policy_defaults_unset_pending_limits() -> None:
    """Unset pending limits should default to unbounded."""
    policy = build_thread_policy({"max_workers": 2})
    assert policy.max_pending_total is None
    assert policy.pending_limits == {}


def test_build_thread_policy_rejects_invalid_max_workers() -> None:
    """Invalid worker counts should raise TypeError to guard configurations."""
    with pytest.raises(TypeError):
        build_thread_policy({"max_workers": True})


def test_build_thread_policy_rejects_invalid_pending_limits() -> None:
    """Negative or non-integer pending limits should be rejected."""
    with pytest.raises(ValueError):
        build_thread_policy({"max_workers": 2, "max_pending_total": -1})
    with pytest.raises(TypeError):
        build_thread_policy({"max_workers": 2, "max_pending_total": True})
    with pytest.raises(ValueError):
        build_thread_policy({"max_workers": 2, "pending_limits": {"tiles": -3}})


def test_thread_policy_omits_non_positive_device_limits() -> None:
    """Device limits less than one should behave as unset."""
    policy = build_thread_policy(
        {
            "max_workers": 2,
            "device_limits": {"cuda": {"sam": 0}},
        }
    )
    assert policy.priority_for("missing") == 0
    assert policy.limit_for("sam") is None
    assert policy.device_limit("cuda", "sam") is None
    assert policy.device_limit(None, "sam") is None
