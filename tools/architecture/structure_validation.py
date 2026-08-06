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
"""Enforce repository-wide source size as an ownership review signal."""

from __future__ import annotations

from pathlib import Path

from .model import ArchitecturePolicy, Diagnostic
from .source_metrics import production_line_count

_OWNERSHIP_ASSESSMENT = (
    "First assess ownership: decide whether this file has one cohesive "
    "responsibility, one authoritative state or behavior owner, one change "
    "cadence and verification boundary, and no independently coordinated "
    "state, lifecycle, cache, policy, persistence, presentation, numerical, "
    "or scheduling concerns. If it is mixed, adding behavior is prohibited: "
    "characterize the touched behavior, extract focused owners, migrate every "
    "caller, remove replaced code and bridges, and verify the boundary. If it "
    "is cohesive, use a narrowly bounded structural waiver only when genuinely "
    "warranted. If unresolved mixed debt must remain outside the active blast "
    "area, record its current facts and use a linked remediation waiver. Never "
    "raise a limit merely to pass, move lines mechanically into a dumping "
    "ground, retain forwarding shims or duplicate ownership, or use a waiver "
    "as permission to extend mixed code."
)


def hard_size_message(lines: int, hard_limit: int) -> str:
    """Return the required judgment-first hard-limit diagnostic."""
    return (
        f"{lines} production lines exceed the hard gate {hard_limit}. "
        f"{_OWNERSHIP_ASSESSMENT}"
    )


def validate_python_structure(
    root: Path,
    policy: ArchitecturePolicy,
) -> list[Diagnostic]:
    """Return size diagnostics for every declared Python product source."""
    excluded = {category.path.as_posix() for category in policy.structure_categories}
    diagnostics: list[Diagnostic] = []
    for product in policy.python_products:
        source_root = root / product.root
        if not source_root.is_dir():
            continue
        for path in sorted(
            candidate
            for candidate in source_root.rglob("*")
            if candidate.is_file() and candidate.suffix in {".py", ".pyi"}
        ):
            relative_path = path.relative_to(root).as_posix()
            if relative_path in excluded:
                continue
            diagnostics.extend(_size_diagnostics(path, relative_path, policy))
    return diagnostics


def _size_diagnostics(
    path: Path,
    relative_path: str,
    policy: ArchitecturePolicy,
) -> list[Diagnostic]:
    """Return the applicable soft or hard diagnostic for one source file."""
    lines = production_line_count(path)
    if lines > policy.structure.hard_lines:
        return [
            Diagnostic(
                "STRUCT003",
                relative_path,
                hard_size_message(lines, policy.structure.hard_lines),
            )
        ]
    if lines > policy.structure.soft_lines:
        return [
            Diagnostic(
                "STRUCT002",
                relative_path,
                f"{lines} production lines exceed the soft ceiling "
                f"{policy.structure.soft_lines}; assess whether ownership "
                "remains cohesive before extending this file.",
                severity="warning",
            )
        ]
    return []
