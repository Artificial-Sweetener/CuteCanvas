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
"""Validate Ferrastra crate dependencies, ownership, and native source structure."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, cast

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 only
    import tomli as tomllib

from .model import ArchitecturePolicy, Diagnostic, RustCratePolicy
from .structure_validation import hard_size_message

_PYTHON_BINDING_CRATES = {"cpython", "numpy", "pyo3", "pyo3-ffi"}
_FORBIDDEN_NATIVE_TERMS = {
    "CuteCanvas": "CuteCanvas type",
    "PySide": "Qt binding",
    "QImage": "Qt image type",
    "QPainter": "Qt painter type",
    "QPixmap": "Qt pixmap type",
    "QWidget": "Qt widget type",
    "qpane::": "QPane type",
}
_GLOBAL_PARALLELISM = {
    ".build_global(": "global Rayon pool",
    "rayon::join(": "global Rayon execution",
    "rayon::spawn(": "global Rayon execution",
    "rayon::spawn_fifo(": "global Rayon execution",
}
_OPERATION_METADATA = {
    "SEMANTIC_ID",
    "SEMANTIC_VERSION",
    "backward_demand",
    "cancellation",
    "conformance",
    "forward_damage",
    "memory",
    "quality",
}


def validate_rust(root: Path, policy: ArchitecturePolicy) -> list[Diagnostic]:
    """Return Cargo dependency and Rust source diagnostics."""
    crate_policies = {crate.name: crate for crate in policy.rust_crates}
    diagnostics: list[Diagnostic] = []
    graph: dict[str, set[str]] = {}
    crates_root = root / "crates"
    if not crates_root.exists():
        return [
            Diagnostic("RUST001", "crates", "Rust workspace has no crate directory")
        ]
    for manifest_path in sorted(crates_root.glob("*/Cargo.toml")):
        manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        package = _table(manifest, "package")
        name = _required_string(package, "name", manifest_path)
        crate_policy = crate_policies.get(name)
        relative_manifest = manifest_path.relative_to(root).as_posix()
        if crate_policy is None:
            diagnostics.append(
                Diagnostic(
                    "RUST002", relative_manifest, f"crate {name} has no declared owner"
                )
            )
            continue
        dependencies = _dependencies(manifest)
        internal = {
            dependency
            for dependency in dependencies
            if dependency.startswith("ferrastra-")
        }
        graph[name] = internal
        diagnostics.extend(
            _dependency_diagnostics(relative_manifest, name, dependencies, crate_policy)
        )
        source_root = manifest_path.parent / "src"
        for path in sorted(source_root.rglob("*.rs")):
            diagnostics.extend(_source_diagnostics(root, path, policy, crate_policy))
    diagnostics.extend(_cycle_diagnostics(graph))
    return diagnostics


def _dependency_diagnostics(
    path: str,
    name: str,
    dependencies: set[str],
    policy: RustCratePolicy,
) -> list[Diagnostic]:
    """Validate one crate's declared dependency edges."""
    diagnostics: list[Diagnostic] = []
    for dependency in sorted(dependencies):
        if (
            dependency.startswith("ferrastra-")
            and dependency not in policy.allowed_internal
        ):
            diagnostics.append(
                Diagnostic(
                    "RUST003",
                    path,
                    f"{name} may not depend on internal crate {dependency}",
                )
            )
        if dependency in _PYTHON_BINDING_CRATES and not policy.python_boundary:
            diagnostics.append(
                Diagnostic(
                    "RUST004",
                    path,
                    f"Python binding dependency {dependency} is restricted to ferrastra-python",
                )
            )
        lowered = dependency.lower()
        if any(token in lowered for token in ("pyside", "qmetaobject", "qt6", "qt5")):
            diagnostics.append(
                Diagnostic(
                    "RUST005",
                    path,
                    f"Qt dependency is forbidden in Ferrastra: {dependency}",
                )
            )
        if lowered in {"qpane", "cutecanvas"}:
            diagnostics.append(
                Diagnostic(
                    "RUST006",
                    path,
                    f"application dependency is forbidden: {dependency}",
                )
            )
    return diagnostics


def _source_diagnostics(
    root: Path,
    path: Path,
    policy: ArchitecturePolicy,
    crate: RustCratePolicy,
) -> list[Diagnostic]:
    """Validate one production Rust module."""
    relative_path = path.relative_to(root).as_posix()
    source = path.read_text(encoding="utf-8")
    diagnostics: list[Diagnostic] = []
    head = "\n".join(source.splitlines()[:80])
    if "//! Responsibility:" not in head or "//! Does not own:" not in head:
        diagnostics.append(
            Diagnostic(
                "RUST007",
                relative_path,
                "module docs must declare Responsibility and Does not own",
            )
        )
    forbidden = {
        part.lower()
        for part in path.with_suffix("").parts
        if part.lower() in policy.structure.forbidden_names
    }
    if forbidden:
        diagnostics.append(
            Diagnostic(
                "STRUCT001",
                relative_path,
                f"generic ownership name is forbidden: {min(forbidden)}",
            )
        )
    lines = _production_line_count(source)
    excluded = {category.path.as_posix() for category in policy.structure_categories}
    if relative_path in excluded:
        pass
    elif lines > policy.structure.hard_lines:
        diagnostics.append(
            Diagnostic(
                "STRUCT003",
                relative_path,
                hard_size_message(lines, policy.structure.hard_lines),
            )
        )
    elif lines > policy.structure.soft_lines:
        diagnostics.append(
            Diagnostic(
                "STRUCT002",
                relative_path,
                f"{lines} production lines exceed the soft ceiling "
                f"{policy.structure.soft_lines}; assess whether ownership "
                "remains cohesive before extending this file.",
                severity="warning",
            )
        )
    diagnostics.extend(_unsafe_diagnostics(relative_path, source))
    diagnostics.extend(_forbidden_term_diagnostics(relative_path, source, crate))
    diagnostics.extend(_operation_diagnostics(relative_path, source))
    return diagnostics


def _unsafe_diagnostics(path: str, source: str) -> list[Diagnostic]:
    """Reject unsafe syntax unless a repository waiver owns it."""
    pattern = re.compile(r"\bunsafe\s+(?:extern|fn|impl|trait|\{)")
    return [
        Diagnostic(
            "RUST008",
            path,
            "unsafe Rust requires SAFETY.md, focused proof, and an active waiver",
            source.count("\n", 0, match.start()) + 1,
        )
        for match in pattern.finditer(source)
    ]


def _forbidden_term_diagnostics(
    path: str,
    source: str,
    crate: RustCratePolicy,
) -> list[Diagnostic]:
    """Reject framework types and hidden global parallel execution."""
    diagnostics: list[Diagnostic] = []
    for term, description in _FORBIDDEN_NATIVE_TERMS.items():
        if term in source:
            diagnostics.append(
                Diagnostic(
                    "RUST009",
                    path,
                    f"Ferrastra source references forbidden {description}: {term}",
                    _line_of(source, term),
                )
            )
    for term, description in _GLOBAL_PARALLELISM.items():
        if term in source:
            diagnostics.append(
                Diagnostic(
                    "RUST010",
                    path,
                    f"{description} bypasses caller-supplied execution budgets",
                    _line_of(source, term),
                )
            )
    if not crate.python_boundary and "pyo3::" in source:
        diagnostics.append(
            Diagnostic(
                "RUST011",
                path,
                "PyO3 source is restricted to ferrastra-python",
                _line_of(source, "pyo3::"),
            )
        )
    return diagnostics


def _operation_diagnostics(path: str, source: str) -> list[Diagnostic]:
    """Require complete contracts beside operation implementations."""
    if "impl Operation for" not in source:
        return []
    missing = sorted(field for field in _OPERATION_METADATA if field not in source)
    if not missing:
        return []
    return [
        Diagnostic(
            "RUST012",
            path,
            f"operation implementation lacks contract metadata: {', '.join(missing)}",
            _line_of(source, "impl Operation for"),
        )
    ]


def _cycle_diagnostics(graph: dict[str, set[str]]) -> list[Diagnostic]:
    """Reject cycles in the active Ferrastra crate graph."""
    diagnostics: list[Diagnostic] = []

    def visit(node: str, stack: tuple[str, ...]) -> None:
        """Walk one crate path and record cycles as architecture diagnostics."""
        if node in stack:
            cycle = stack[stack.index(node) :]
            rendered = " -> ".join((*cycle, node))
            diagnostic = Diagnostic("RUST013", "Cargo.toml", f"crate cycle: {rendered}")
            if diagnostic not in diagnostics:
                diagnostics.append(diagnostic)
            return
        for target in sorted(graph.get(node, set())):
            visit(target, (*stack, node))

    for crate in sorted(graph):
        visit(crate, ())
    return diagnostics


def _dependencies(manifest: dict[str, Any]) -> set[str]:
    """Return direct normal, build, development, and target dependencies."""
    dependencies: set[str] = set()
    for key in ("dependencies", "dev-dependencies", "build-dependencies"):
        value = manifest.get(key, {})
        if isinstance(value, dict):
            dependency_table = cast(dict[str, object], value)
            dependencies.update(dependency_table)
    targets = manifest.get("target", {})
    if isinstance(targets, dict):
        target_tables = cast(dict[str, object], targets)
        for target in target_tables.values():
            if not isinstance(target, dict):
                continue
            target_table = cast(dict[str, object], target)
            for key in ("dependencies", "dev-dependencies", "build-dependencies"):
                value = target_table.get(key, {})
                if isinstance(value, dict):
                    dependency_table = cast(dict[str, object], value)
                    dependencies.update(dependency_table)
    return dependencies


def _table(data: dict[str, Any], key: str) -> dict[str, Any]:
    """Return one required TOML table."""
    value = data.get(key)
    if not isinstance(value, dict):
        raise TypeError(f"Cargo manifest is missing [{key}]")
    return cast(dict[str, Any], value)


def _required_string(data: dict[str, Any], key: str, path: Path) -> str:
    """Return one required Cargo string value."""
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} package.{key} must be a string")
    return value


def _production_line_count(source: str) -> int:
    """Count nonblank, noncomment physical Rust lines."""
    return sum(
        1
        for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith(("//", "/*", "*", "*/"))
    )


def _line_of(source: str, value: str) -> int:
    """Return the one-based line containing a substring."""
    return source.count("\n", 0, source.index(value)) + 1
