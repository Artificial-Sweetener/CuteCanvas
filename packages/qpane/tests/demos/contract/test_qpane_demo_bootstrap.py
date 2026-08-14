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

from pathlib import Path
from subprocess import CompletedProcess

import qpane_demo
from qpane_demo_environment import DemoEnvironmentManager


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


def test_qpane_demo_installs_local_ferrastra_before_qpane(
    monkeypatch, tmp_path: Path
) -> None:
    """Provision the demo from both editable products in the source checkout."""
    package_root = tmp_path / "packages" / "qpane"
    examples_root = package_root / "examples"
    examples_root.mkdir(parents=True)
    entry_point = examples_root / "qpane_demo.py"
    entry_point.touch()
    manager = DemoEnvironmentManager(entry_point)
    commands: list[tuple[list[str], Path]] = []

    def record_command(command, *, check, cwd):
        """Capture provisioning commands without creating an environment."""
        assert check is True
        commands.append((command, cwd))
        return CompletedProcess(command, 0)

    monkeypatch.setattr(manager, "python_path", lambda _tier: Path("python.exe"))
    monkeypatch.setattr(manager, "_write_fingerprint", lambda _tier: None)
    monkeypatch.setattr("qpane_demo_environment.subprocess.run", record_command)

    manager._install("qpane")

    assert commands[1] == (
        [
            "python.exe",
            "-m",
            "pip",
            "install",
            "-e",
            str(tmp_path / "packages" / "ferrastra"),
            "-e",
            str(package_root),
        ],
        package_root,
    )
