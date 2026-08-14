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

import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from tools.testing.cli import _print_selection
from tools.testing.execution import (
    _parallel_worker_budget,
    _run_ci_command,
    group_paths,
    run_isolated_groups,
    run_parallel_isolated_groups,
    run_selection,
)
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


def test_isolated_gate_runs_one_policy_group_per_pytest_process() -> None:
    """Hosted verification must honor group and stronger case isolation."""
    policies = load_policies(repository_root())
    commands: list[tuple[str, ...]] = []

    def successful_runner(command: Sequence[str], root: Path) -> int:
        """Capture every command without executing the complete repository."""
        assert root == repository_root()
        commands.append(tuple(command))
        return 0

    def two_nodes(path: str, root: Path) -> tuple[int, tuple[str, ...]]:
        """Return two deterministic cases for each strongly isolated group."""
        assert root == repository_root()
        return 0, (
            f"{path}/test_first.py::test_first",
            f"{path}/test_second.py::test_second",
        )

    assert (
        run_isolated_groups(
            repository_root(),
            policies,
            runner=successful_runner,
            node_collector=two_nodes,
        )
        == 0
    )
    pytest_commands = tuple(command for command in commands if "pytest" in command)
    case_isolated_count = sum(
        len(area.case_isolated_proofs)
        for policy in policies.values()
        for area in policy.areas
    )
    expected_process_count = (
        sum(len(area.proofs) for policy in policies.values() for area in policy.areas)
        + case_isolated_count
    )
    assert len(pytest_commands) == expected_process_count
    assert all("-n" not in command for command in pytest_commands)
    assert all(len(command) == 4 for command in pytest_commands)
    assert sum("::" in command[-1] for command in pytest_commands) == (
        case_isolated_count * 2
    )


def test_isolated_gate_stops_after_the_first_failed_group() -> None:
    """A failed isolated group must prevent later groups from masking it."""
    policies = load_policies(repository_root())
    commands: list[tuple[str, ...]] = []

    def second_group_fails(command: Sequence[str], root: Path) -> int:
        """Fail the second pytest process after architecture validation."""
        assert root == repository_root()
        commands.append(tuple(command))
        pytest_count = sum("pytest" in candidate for candidate in commands)
        return 9 if "pytest" in command and pytest_count == 2 else 0

    assert (
        run_isolated_groups(
            repository_root(),
            policies,
            runner=second_group_fails,
        )
        == 9
    )
    assert sum("pytest" in command for command in commands) == 2


def test_ci_gate_parallelizes_groups_but_serializes_strong_cases() -> None:
    """Reduce latency without allowing abuse or performance cases to contend."""
    policies = load_policies(repository_root())
    commands: list[tuple[str, ...]] = []

    def concurrent_runner(command: Sequence[str], root: Path) -> int:
        """Capture aggregate and strongly isolated CI commands."""
        assert root == repository_root()
        commands.append(tuple(command))
        return 0

    def one_node(path: str, root: Path) -> tuple[int, tuple[str, ...]]:
        """Represent each strongly isolated group with one case."""
        assert root == repository_root()
        return 0, (f"{path}/test_case.py::test_case",)

    assert (
        run_parallel_isolated_groups(
            repository_root(),
            policies,
            runner=concurrent_runner,
            node_collector=one_node,
            workers=4,
        )
        == 0
    )
    pytest_commands = [command for command in commands if "pytest" in command]
    groups = [command for command in pytest_commands if "::" not in command[-1]]
    assert len(groups) > 1
    assert all("-n" not in command for command in groups)
    assert len({command[3] for command in groups}) == len(groups)
    serial = [
        command
        for command in groups
        if command[-1].endswith(("/abuse", "/performance"))
        or command[-1]
        in {
            "packages/cutecanvas/tests/painting/integration",
            "packages/cutecanvas/tests/rendering/integration",
        }
    ]
    parallel = [command for command in groups if command not in serial]
    assert serial
    assert any(
        command[-1] == "packages/cutecanvas/tests/rendering/abuse" for command in serial
    )
    assert max(commands.index(command) for command in parallel) < min(
        commands.index(command) for command in serial
    )
    strong = [command for command in pytest_commands if "::" in command[-1]]
    assert strong
    assert max(commands.index(command) for command in serial) < min(
        commands.index(command) for command in strong
    )
    assert all("-n" not in command for command in strong)
    assert len({command[3] for command in strong}) == len(strong)


def test_ci_parallelism_never_oversubscribes_available_cpus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep macOS Qt group concurrency within the runner's CPU envelope."""
    monkeypatch.setattr("tools.testing.execution.sys.platform", "darwin")
    monkeypatch.setattr("tools.testing.execution.os.cpu_count", lambda: 3)
    assert _parallel_worker_budget() == 3


def test_ci_parallelism_retains_the_repository_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the proven fast process budget on non-macOS hosts."""
    monkeypatch.setattr("tools.testing.execution.sys.platform", "win32")
    monkeypatch.setattr("tools.testing.execution.os.cpu_count", lambda: 2)
    assert _parallel_worker_budget() == 8


def test_ci_gate_reports_a_parallel_group_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Return and identify a failed group after concurrent work settles."""
    policies = load_policies(repository_root())
    failed_path = "packages/qpane/tests/cache/integration"

    def group_failure(command: Sequence[str], root: Path) -> int:
        """Fail one known ordinary group without executing repository tests."""
        assert root == repository_root()
        return 9 if command[-1] == failed_path else 0

    def one_node(path: str, root: Path) -> tuple[int, tuple[str, ...]]:
        """Represent each strongly isolated group with one case."""
        assert root == repository_root()
        return 0, (f"{path}/test_case.py::test_case",)

    assert (
        run_parallel_isolated_groups(
            repository_root(),
            policies,
            runner=group_failure,
            node_collector=one_node,
            workers=4,
        )
        == 9
    )
    assert failed_path in capsys.readouterr().err


def test_serial_ci_groups_receive_hosted_timing_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Make local CI execution use the same contention policy as hosted jobs."""
    monkeypatch.delenv("CI", raising=False)
    assert (
        _run_ci_command(
            (
                sys.executable,
                "-c",
                "import os, sys; sys.exit(0 if os.environ.get('CI') else 9)",
            ),
            repository_root(),
        )
        == 0
    )


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
    assert any(
        command[-2:] == ("-m", "tools.verify_python_wheels") for command in commands
    )


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
