#    QPane + CuteCanvas + Ferrastra - Native graphics architecture tooling
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
"""Orchestrate repository-wide architecture and current-state validation."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .model import Diagnostic
from .policy import load_policy
from .python_validation import validate_python
from .qt_allocation_validation import validate_qt_allocation_safety
from .rust_validation import validate_rust
from .snapshot import repository_snapshot
from .state_validation import validate_architecture_state
from .structure_validation import validate_python_structure
from .waiver_application import apply_architecture_waivers


def validate_repository(
    root: Path,
    *,
    policy_path: Path | None = None,
    staged: bool = False,
    today: date | None = None,
) -> list[Diagnostic]:
    """Return every unsuppressed diagnostic for worktree or staged state."""
    with repository_snapshot(root, staged=staged) as snapshot:
        resolved_policy = policy_path or snapshot / "ARCHITECTURE_POLICY.toml"
        policy = load_policy(resolved_policy)
        states, state_diagnostics = validate_architecture_state(
            snapshot,
            policy,
            today=today,
        )
        source_diagnostics = [
            *validate_python(snapshot, policy),
            *validate_qt_allocation_safety(snapshot),
            *validate_python_structure(snapshot, policy),
            *validate_rust(snapshot, policy),
        ]
        diagnostics = [
            *state_diagnostics,
            *apply_architecture_waivers(
                source_diagnostics,
                states,
                today=today,
            ),
        ]
        return sorted(
            diagnostics,
            key=lambda item: (item.path, item.line, item.rule, item.message),
        )


def run(root: Path, *, staged: bool = False) -> None:
    """Print actionable diagnostics and fail when architecture errors exist."""
    diagnostics = validate_repository(root, staged=staged)
    for diagnostic in diagnostics:
        print(diagnostic.render())
    errors = [item for item in diagnostics if item.severity == "error"]
    if errors:
        raise SystemExit(
            f"FAILED: Found {len(errors)} repository architecture violations."
        )
    warning_count = len(diagnostics) - len(errors)
    print(
        f"SUCCESS: Repository architecture is valid ({warning_count} structural warnings)."
    )
