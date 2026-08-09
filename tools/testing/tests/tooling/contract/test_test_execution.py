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

"""Prove selected test commands propagate failures and preserve targeting."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from tools.testing.cli import _print_selection
from tools.testing.execution import group_paths, run_selection
from tools.testing.model import SelectionReason
from tools.testing.model import TestGroup as _TestGroup
from tools.testing.model import TestSelection as _TestSelection
from tools.testing.policy import load_policies, repository_root


def test_group_paths_hide_private_pytest_node_ids() -> None:
    """Translate a public logical target into its owned physical directory."""
    policies = load_policies(repository_root())
    groups = frozenset({_TestGroup("qpane", "cache", "integration")})
    assert group_paths(groups, policies) == ("packages/qpane/tests/cache/integration",)


def test_test_process_failure_is_returned_to_the_caller() -> None:
    """Never report a selected gate as successful after pytest fails."""
    policies = load_policies(repository_root())
    selection = _TestSelection(
        groups=frozenset({_TestGroup("qpane", "cache", "integration")}),
        reasons=(),
    )
    commands: list[tuple[str, ...]] = []

    def failing_runner(command: Sequence[str], root: Path) -> int:
        """Capture the command and simulate one failed test process."""
        assert root == repository_root()
        commands.append(tuple(command))
        return 7 if "pytest" in command else 0

    assert (
        run_selection(
            repository_root(),
            selection,
            policies,
            runner=failing_runner,
        )
        == 7
    )
    assert commands[0][-1] == "tools/check_architecture.py"
    assert "pytest" in commands[1]
    assert commands[1][3:6] == ("-n", "auto", "--maxprocesses=8")


def test_native_commit_gate_denies_warnings_and_dependency_risk() -> None:
    """Keep Ferrastra commit selection aligned with every native safety gate."""
    policies = load_policies(repository_root())
    selection = _TestSelection(
        groups=frozenset({_TestGroup("ferrastra", "native", "contract")}),
        reasons=(
            SelectionReason(
                "crates/ferrastra-python/src/lib.rs",
                "ferrastra.native production ownership",
                _TestGroup("ferrastra", "native", "contract"),
            ),
        ),
    )
    commands: list[tuple[str, ...]] = []

    def successful_runner(command: Sequence[str], root: Path) -> int:
        """Capture every successful command for exact gate assertions."""
        assert root == repository_root()
        commands.append(tuple(command))
        return 0

    assert (
        run_selection(
            repository_root(),
            selection,
            policies,
            commit=True,
            runner=successful_runner,
        )
        == 0
    )
    assert any(command[-1] == "--staged" for command in commands)
    assert (
        "cargo",
        "clippy",
        "--workspace",
        "--all-targets",
        "--all-features",
        "--",
        "-D",
        "warnings",
    ) in commands
    assert ("cargo", "deny", "check") in commands
    assert any(command[-1] == "tools/verify_ferrastra_wheel.py" for command in commands)


def test_python_packaging_commit_builds_isolated_consumer_wheels() -> None:
    """Run the QPane/CuteCanvas wheel boundary for staged package metadata."""
    policies = load_policies(repository_root())
    group = _TestGroup("qpane", "api", "packaging")
    selection = _TestSelection(
        groups=frozenset({group}),
        reasons=(
            SelectionReason(
                "packages/qpane/pyproject.toml",
                "qpane.api production ownership",
                group,
            ),
        ),
    )
    commands: list[tuple[str, ...]] = []

    def successful_runner(command: Sequence[str], root: Path) -> int:
        """Capture the packaging gate command without building a wheel."""
        assert root == repository_root()
        commands.append(tuple(command))
        return 0

    assert (
        run_selection(
            repository_root(),
            selection,
            policies,
            commit=True,
            runner=successful_runner,
        )
        == 0
    )
    assert any(command[-1] == "tools/verify_python_wheels.py" for command in commands)


def test_large_selection_reports_facts_without_repeating_every_edge(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Keep broad changed-work diagnostics concise and still explanatory."""
    group = _TestGroup("qpane", "api", "contract")
    selection = _TestSelection(
        groups=frozenset({group}),
        reasons=tuple(
            SelectionReason(f"path-{index}.py", "owned source", group)
            for index in range(25)
        ),
    )

    _print_selection(selection)

    output = capsys.readouterr().out
    assert "25 changed paths produced 25 proof requirements" in output
    assert "owned source: 25" in output
    assert output.count("qpane/api/contract <-") == 1
    assert "(+24 additional edges)" in output
