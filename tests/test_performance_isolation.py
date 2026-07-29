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
"""Prove performance isolation topology under xdist worker replacement."""

from __future__ import annotations

from types import SimpleNamespace

from tests.harness.process_lock import performance_worker_slots


def _request(
    worker_id: str | None,
    *,
    worker_count: int = 24,
    max_restarts: int | None = None,
) -> SimpleNamespace:
    """Build the request fields consumed by the topology owner."""
    worker_input = (
        None
        if worker_id is None
        else {"workerid": worker_id, "workercount": worker_count}
    )
    return SimpleNamespace(
        config=SimpleNamespace(
            workerinput=worker_input,
            option=SimpleNamespace(maxworkerrestart=max_restarts),
        )
    )


def test_non_xdist_execution_uses_one_activity_slot() -> None:
    """A local run needs only its own activity byte."""
    assert performance_worker_slots(_request(None)) == (0, 1)


def test_default_xdist_capacity_includes_every_allowed_replacement() -> None:
    """Default xdist restarts cannot outgrow the activity lock topology."""
    assert performance_worker_slots(_request("gw24")) == (24, 120)
    assert performance_worker_slots(_request("gw119")) == (119, 120)


def test_explicit_xdist_restart_capacity_is_honored_exactly() -> None:
    """An explicit restart limit defines the final valid replacement slot."""
    assert performance_worker_slots(_request("gw25", max_restarts=2)) == (25, 26)
