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

"""Validate physical test ownership against current product policies."""

from __future__ import annotations

import ast
import os
from collections import Counter
from pathlib import Path

from tools.testing.model import TestGroup, TestPolicy
from tools.testing.policy import path_matches_pattern


class InventoryError(ValueError):
    """Report a test inventory or dependency-direction violation."""


def validate_inventory(root: Path, policies: dict[str, TestPolicy]) -> None:
    """Validate test placement, group coverage, source mapping, and imports."""
    validate_root_runtime_ownership(root)
    _validate_test_modules(root, policies)
    _validate_source_coverage(root, policies)
    validate_import_direction(root, policies)


def collect_test_modules(root: Path, policy: TestPolicy) -> tuple[Path, ...]:
    """Return every collected-style test module owned by one policy."""
    test_root = root / policy.test_root
    return tuple(sorted(test_root.rglob("test_*.py")))


def validate_root_runtime_ownership(root: Path) -> None:
    """Reject product runtime tests or fixtures from the repository root."""
    legacy_root = root / "tests"
    offenders = _owned_python_files(legacy_root)
    if offenders:
        relative = ", ".join(str(path.relative_to(root)) for path in offenders)
        raise InventoryError(
            "repository-root tests may cover only policy and orchestration beside "
            f"their tools; move product runtime tests and fixtures: {relative}"
        )
    example_root = root / "examples"
    example_offenders = _owned_python_files(example_root)
    if example_offenders:
        relative = ", ".join(str(path.relative_to(root)) for path in example_offenders)
        raise InventoryError(
            "product examples must live with their independently publishable "
            f"owner; move repository-root runtime examples: {relative}"
        )


def _owned_python_files(root: Path) -> tuple[Path, ...]:
    """Collect Python files without entering ignored local environments or caches."""
    if not root.exists():
        return ()
    files: list[Path] = []
    for current, directories, names in os.walk(root):
        directories[:] = [
            name
            for name in directories
            if name != "__pycache__" and name != ".venv" and not name.startswith("venv")
        ]
        current_path = Path(current)
        files.extend(current_path / name for name in names if name.endswith(".py"))
    return tuple(sorted(files))


def _validate_test_modules(root: Path, policies: dict[str, TestPolicy]) -> None:
    """Require every declared group to exist and every module to have one group."""
    identities: Counter[str] = Counter()
    module_names: Counter[str] = Counter()
    for policy in policies.values():
        modules = collect_test_modules(root, policy)
        found: set[TestGroup] = set()
        for module in modules:
            module_names[module.name] += 1
            relative = module.relative_to(root / policy.test_root)
            if len(relative.parts) != 3:
                raise InventoryError(
                    f"{module.relative_to(root)}: tests must be organized as "
                    "<behavioral-area>/<proof-kind>/test_*.py"
                )
            group = TestGroup(policy.product, relative.parts[0], relative.parts[1])
            if group not in policy.groups():
                raise InventoryError(
                    f"{module.relative_to(root)}: group is absent from "
                    f"{policy.path.relative_to(root)}; move the test or update the "
                    "current policy when ownership genuinely changed"
                )
            found.add(group)
            module_identities = _test_identities(module)
            if not module_identities:
                raise InventoryError(
                    f"{module.relative_to(root)} contains no tests; remove the stale "
                    "module or add proof for its stated concern"
                )
            if relative.parts[1] == "performance" and not _declares_performance(module):
                raise InventoryError(
                    f"{module.relative_to(root)} is filed as performance proof but "
                    "does not declare a performance marker"
                )
            for identity in module_identities:
                identities[f"{policy.product}:{relative.as_posix()}::{identity}"] += 1
        missing = policy.groups() - found
        if missing:
            raise InventoryError(
                f"{policy.path.relative_to(root)} declares empty groups: "
                f"{sorted(missing)}. Add required proof or remove stale policy facts."
            )
    duplicates = sorted(identity for identity, count in identities.items() if count > 1)
    if duplicates:
        raise InventoryError(f"duplicate product test identities: {duplicates}")
    duplicate_modules = sorted(
        name for name, count in module_names.items() if count > 1
    )
    if duplicate_modules:
        raise InventoryError(
            "aggregate pytest collection requires unique test module basenames; "
            f"rename these modules by owned behavior: {duplicate_modules}"
        )


def _validate_source_coverage(root: Path, policies: dict[str, TestPolicy]) -> None:
    """Require every production module to match exactly one current behavior area."""
    candidates = tuple(
        path
        for base in (
            root / "packages" / "qpane" / "src",
            root / "packages" / "qpane" / "examples",
            root / "packages" / "cutecanvas" / "src",
            root / "packages" / "cutecanvas" / "examples",
            root / "packages" / "ferrastra" / "src",
            root / "packages" / "ferrastra" / "examples",
            root / "crates",
        )
        if base.exists()
        for path in base.rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".pyi", ".rs"}
        and path.name != "_version.py"
    )
    for source in candidates:
        relative = source.relative_to(root).as_posix()
        matches = [
            (policy.product, area.name)
            for policy in policies.values()
            for area in policy.areas
            if any(path_matches_pattern(relative, pattern) for pattern in area.sources)
        ]
        if len(matches) != 1:
            raise InventoryError(
                f"{relative}: expected exactly one product and behavioral mapping, "
                f"found {matches}. Correct the authoritative TEST_POLICY.toml; "
                "do not hide ambiguity with overlapping patterns."
            )


def validate_import_direction(root: Path, policies: dict[str, TestPolicy]) -> None:
    """Reject product tests that depend on upstream-private test namespaces."""
    repository_namespaces = ("examples", "tests", "tools")
    forbidden = {
        "qpane": (
            *repository_namespaces,
            "cutecanvas",
            "cutecanvas_test_support",
        ),
        "cutecanvas": repository_namespaces,
        "ferrastra": (
            *repository_namespaces,
            "qpane",
            "qpane_test_support",
            "cutecanvas",
            "cutecanvas_test_support",
        ),
    }
    for product, prefixes in forbidden.items():
        policy = policies[product]
        for module in (root / policy.test_root).rglob("*.py"):
            imports = _imports(module)
            violations = sorted(
                name
                for name in imports
                if any(
                    name == prefix or name.startswith(f"{prefix}.")
                    for prefix in prefixes
                )
            )
            if violations:
                raise InventoryError(
                    f"{module.relative_to(root)} imports forbidden downstream "
                    f"owners {violations}; keep fixtures package-local and exercise "
                    "external products only through allowed dependency direction"
                )


def _imports(path: Path) -> frozenset[str]:
    """Return absolute import names from one Python module."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return frozenset(names)


def _test_identities(path: Path) -> tuple[str, ...]:
    """Return module-local class/function test identities."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    identities: list[str] = []
    for node in tree.body:
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and node.name.startswith("test_"):
            identities.append(node.name)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            identities.extend(
                f"{node.name}.{child.name}"
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name.startswith("test_")
            )
    return tuple(identities)


def _declares_performance(path: Path) -> bool:
    """Return whether a module explicitly opts into performance isolation."""
    source = path.read_text(encoding="utf-8")
    return any(
        token in source
        for token in (
            "interactive_performance",
            "pytest.mark.performance",
            "INTERACTIVE_PERFORMANCE",
        )
    )
