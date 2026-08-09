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

"""Execute selected pytest groups and commit-level native gates."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from tools.testing.model import TestGroup, TestPolicy, TestSelection

CommandRunner = Callable[[Sequence[str], Path], int]
_MAX_PARALLEL_TEST_PROCESSES = 8


def group_paths(
    groups: frozenset[TestGroup],
    policies: dict[str, TestPolicy],
) -> tuple[str, ...]:
    """Return deterministic physical paths for selected logical groups."""
    return tuple(
        f"{policies[group.product].test_root}/{group.area}/{group.proof}"
        for group in sorted(groups)
    )


def run_selection(
    root: Path,
    selection: TestSelection,
    policies: dict[str, TestPolicy],
    *,
    commit: bool = False,
    runner: CommandRunner | None = None,
) -> int:
    """Run selected Python proof and applicable commit-level native gates."""
    active_runner = runner or _run_command
    architecture_command = [sys.executable, "tools/check_architecture.py"]
    if commit:
        architecture_command.append("--staged")
    result = active_runner(tuple(architecture_command), root)
    if result:
        return result
    if selection.validate_artifacts:
        result = active_runner(("git", "diff", "--check"), root)
        if result:
            return result
    paths = group_paths(selection.groups, policies)
    if paths:
        result = active_runner(
            (
                sys.executable,
                "-m",
                "pytest",
                "-n",
                "auto",
                f"--maxprocesses={_MAX_PARALLEL_TEST_PROCESSES}",
                *paths,
            ),
            root,
        )
        if result:
            return result
    if commit and _requires_python_wheel_gate(selection):
        result = active_runner(
            (sys.executable, "tools/verify_python_wheels.py"),
            root,
        )
        if result:
            return result
    if commit and _requires_ferrastra_wheel_gate(selection):
        result = active_runner(
            (sys.executable, "tools/verify_ferrastra_wheel.py"),
            root,
        )
        if result:
            return result
    if commit and _requires_native_commit_gate(selection):
        for command in (
            ("cargo", "fmt", "--all", "--", "--check"),
            (
                "cargo",
                "clippy",
                "--workspace",
                "--all-targets",
                "--all-features",
                "--",
                "-D",
                "warnings",
            ),
            ("cargo", "test", "--workspace", "--all-features"),
            ("cargo", "deny", "check"),
        ):
            result = active_runner(command, root)
            if result:
                return result
    return 0


def _requires_python_wheel_gate(selection: TestSelection) -> bool:
    """Return whether staged packaging or public contracts affect Python wheels."""
    for path in _changed_paths(selection):
        if path in {
            "packages/qpane/pyproject.toml",
            "packages/cutecanvas/pyproject.toml",
        }:
            return True
        if path.startswith(
            (
                "packages/qpane/src/qpane/",
                "packages/cutecanvas/src/cutecanvas/",
            )
        ):
            name = Path(path).name
            if name in {"__init__.py", "py.typed"} or name.endswith(".pyi"):
                return True
    return False


def _requires_ferrastra_wheel_gate(selection: TestSelection) -> bool:
    """Return whether staged Ferrastra changes affect its native wheel boundary."""
    return any(
        path == "packages/ferrastra/pyproject.toml"
        or path.startswith(
            (
                "packages/ferrastra/src/ferrastra/",
                "crates/ferrastra-python/",
            )
        )
        for path in _changed_paths(selection)
    )


def _requires_native_commit_gate(selection: TestSelection) -> bool:
    """Return whether staged paths require the complete Rust workspace gate."""
    native_configuration = {
        "Cargo.toml",
        "Cargo.lock",
        "deny.toml",
        "rust-toolchain.toml",
        "rustfmt.toml",
    }
    return any(
        path in native_configuration
        or (path.startswith("crates/") and Path(path).suffix == ".rs")
        for path in _changed_paths(selection)
    )


def _changed_paths(selection: TestSelection) -> frozenset[str]:
    """Return concrete changed paths without synthetic selection reasons."""
    return frozenset(
        reason.changed_path
        for reason in selection.reasons
        if not reason.changed_path.startswith("<")
    )


def _run_command(command: Sequence[str], root: Path) -> int:
    """Run one gate with inherited output and return its process status."""
    return subprocess.run(tuple(command), cwd=root, check=False).returncode
