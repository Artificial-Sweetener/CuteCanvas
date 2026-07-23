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

"""Behavioral coverage for the self-bootstrapping demo entry point."""

from argparse import Namespace

from examples import cutecanvas_demo as demo
from examples import qpane_demo
from examples.demo_environment import DEMO_TIERS


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
    assert DEMO_TIERS["core"].extra is None
    assert DEMO_TIERS["mask"].extra is None
    assert DEMO_TIERS["masksam"].extra == "sam"


def test_main_bootstraps_before_importing_demo_window(monkeypatch) -> None:
    """Select the tier environment even when system Python already has Qt."""
    options = Namespace(
        features="core",
        log_level="INFO",
        config_strict=False,
        sam_download_mode=None,
        sam_model_path=None,
        sam_model_url=None,
        sam_model_hash=None,
    )
    environment = _DifferentTierEnvironment()

    monkeypatch.setattr(demo, "_parse_bootstrap_args", lambda _args: options)
    monkeypatch.setattr(demo, "_DEMO_ENVIRONMENTS", environment)
    monkeypatch.setattr(
        demo,
        "_load_example_types",
        lambda: (_ for _ in ()).throw(AssertionError("imported before bootstrap")),
    )

    result = demo.main(["--features", "core", "--skip-menu"])

    assert result == 23
    assert environment.actions == [
        ("inspect", "core"),
        ("ensure", "core"),
        ("launch", "core"),
    ]


def test_qpane_main_bootstraps_its_viewer_only_environment(monkeypatch) -> None:
    """The QPane entry point provisions QPane without requiring CuteCanvas."""
    environment = _DifferentTierEnvironment()
    monkeypatch.setattr(qpane_demo, "_DEMO_ENVIRONMENTS", environment)

    result = qpane_demo.main([])

    assert result == 23
    assert environment.actions == [
        ("inspect", "qpane"),
        ("ensure", "qpane"),
        ("launch", "qpane"),
    ]
