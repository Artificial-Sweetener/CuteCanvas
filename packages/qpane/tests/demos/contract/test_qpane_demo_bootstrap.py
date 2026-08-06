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

"""Behavioral coverage for QPane's self-bootstrapping demo entry point."""

from __future__ import annotations

import qpane_demo


class _DifferentTierEnvironment:
    """Record handoff behavior outside the requested QPane environment."""

    def __init__(self) -> None:
        """Initialize an empty action record."""
        self.actions: list[tuple[str, str]] = []

    def is_current_process(self, tier: str) -> bool:
        """Report that the test process is not the requested environment."""
        self.actions.append(("inspect", tier))
        return False

    def ensure_ready(self, tier: str) -> None:
        """Record environment provisioning."""
        self.actions.append(("ensure", tier))

    def launch(self, tier: str, _settings: object) -> int:
        """Record process handoff."""
        self.actions.append(("launch", tier))
        return 23


def test_qpane_main_bootstraps_its_viewer_only_environment(monkeypatch) -> None:
    """Provision QPane's demo without acquiring an editor dependency."""
    environment = _DifferentTierEnvironment()
    monkeypatch.setattr(qpane_demo, "_DEMO_ENVIRONMENTS", environment)

    result = qpane_demo.main([])

    assert result == 23
    assert environment.actions == [
        ("inspect", "qpane"),
        ("ensure", "qpane"),
        ("launch", "qpane"),
    ]
