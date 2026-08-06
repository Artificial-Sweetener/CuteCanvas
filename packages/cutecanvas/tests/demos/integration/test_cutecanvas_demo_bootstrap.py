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

"""Behavioral coverage for the self-bootstrapping demo entry point."""

from argparse import Namespace
from pathlib import Path
from subprocess import CompletedProcess

import cutecanvas_demo as demo
from cutecanvas_demo_environment import DEMO_TIERS, DemoEnvironmentManager


class _DifferentTierEnvironment:
    """Record handoff behavior for a process outside the requested tier."""

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

    def launch(self, tier: str, _settings) -> int:
        """Record process handoff."""
        self.actions.append(("launch", tier))
        return 23


def test_editor_demo_tiers_match_cutecanvas_dependency_ownership() -> None:
    """Masks ship normally while only SAM requires an optional dependency."""
    assert DEMO_TIERS["cutecanvas"].extra is None
    assert DEMO_TIERS["cutecanvas"].sam_enabled is False
    assert DEMO_TIERS["cutecanvas-sam"].extra == "sam"
    assert DEMO_TIERS["cutecanvas-sam"].sam_enabled is True


def test_main_bootstraps_before_importing_demo_window(monkeypatch) -> None:
    """Select the tier environment even when system Python already has Qt."""
    options = Namespace(
        sam=False,
        log_level="INFO",
        config_strict=False,
        sam_download_mode=None,
        sam_model_path=None,
        sam_model_url=None,
        sam_model_hash=None,
        navigation_trace_output=None,
        navigation_document=None,
    )
    environment = _DifferentTierEnvironment()

    monkeypatch.setattr(demo, "_parse_bootstrap_args", lambda _args: options)
    monkeypatch.setattr(demo, "_DEMO_ENVIRONMENTS", environment)
    monkeypatch.setattr(
        demo,
        "_load_example_types",
        lambda: (_ for _ in ()).throw(AssertionError("imported before bootstrap")),
    )

    result = demo.main(["--skip-menu"])

    assert result == 23
    assert environment.actions == [
        ("inspect", "cutecanvas"),
        ("ensure", "cutecanvas"),
        ("launch", "cutecanvas"),
    ]


def test_demo_environment_installs_local_qpane_with_cutecanvas(
    monkeypatch, tmp_path: Path
) -> None:
    """Provision the demo from both editable packages in the source checkout."""
    package_root = tmp_path / "packages" / "cutecanvas"
    examples_root = package_root / "examples"
    examples_root.mkdir(parents=True)
    entry_point = examples_root / "cutecanvas_demo.py"
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
    monkeypatch.setattr("cutecanvas_demo_environment.subprocess.run", record_command)

    manager._install("cutecanvas-sam")

    assert commands[1] == (
        [
            "python.exe",
            "-m",
            "pip",
            "install",
            "-e",
            str(tmp_path / "packages" / "qpane"),
            "-e",
            f"{package_root}[sam]",
        ],
        package_root,
    )
