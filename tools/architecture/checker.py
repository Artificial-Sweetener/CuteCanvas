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
"""Orchestrate declarative Python and Rust architecture validation."""

from __future__ import annotations

from pathlib import Path

from .model import Diagnostic
from .policy import load_policy
from .python_validation import validate_python
from .rust_validation import validate_rust
from .waivers import apply_waivers


def validate_repository(
    root: Path,
    *,
    policy_path: Path | None = None,
    waiver_path: Path | None = None,
) -> list[Diagnostic]:
    """Return every unsuppressed cross-language architecture diagnostic."""
    resolved_policy = policy_path or root / "ARCHITECTURE_POLICY.toml"
    resolved_waivers = waiver_path or root / "ARCHITECTURE_WAIVERS.toml"
    policy = load_policy(resolved_policy)
    diagnostics = [*validate_python(root, policy), *validate_rust(root, policy)]
    return sorted(
        apply_waivers(diagnostics, resolved_waivers),
        key=lambda item: (item.path, item.line, item.rule, item.message),
    )


def run(root: Path) -> None:
    """Print actionable diagnostics and fail when architecture errors exist."""
    diagnostics = validate_repository(root)
    for diagnostic in diagnostics:
        print(diagnostic.render())
    errors = [item for item in diagnostics if item.severity == "error"]
    if errors:
        raise SystemExit(
            f"FAILED: Found {len(errors)} Ferrastra architecture violations."
        )
    warning_count = len(diagnostics) - len(errors)
    print(
        f"SUCCESS: Ferrastra architecture is valid ({warning_count} structural warnings)."
    )
