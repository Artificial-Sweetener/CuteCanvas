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
"""Validate product routing, state locations, and structural categories."""

from __future__ import annotations

from collections import Counter
from pathlib import Path, PurePosixPath

from .model import ArchitecturePolicy, Diagnostic

_REGISTRY_NAMES = {"ARCHITECTURE_DEBT.toml", "ARCHITECTURE_WAIVERS.toml"}
_GLOB_MARKERS = "*?[]"


def validate_policy_ownership(
    root: Path,
    policy: ArchitecturePolicy,
) -> list[Diagnostic]:
    """Validate product routing, registry locations, and exact categories."""
    diagnostics: list[Diagnostic] = []
    products = {product.name: product for product in policy.python_products}
    if len(products) != len(policy.python_products):
        diagnostics.append(
            Diagnostic(
                "POLICY001",
                "ARCHITECTURE_POLICY.toml",
                "product names must be unique",
            )
        )
    declared_registries: set[str] = set()
    roots: list[tuple[str, str]] = []
    for product in policy.python_products:
        roots.append((product.name, product.root.as_posix()))
        diagnostics.extend(
            _validate_product_policy(
                root,
                product.name,
                product.root,
                product.debt_registry,
                product.waiver_registry,
            )
        )
        declared_registries.update(
            {product.debt_registry.as_posix(), product.waiver_registry.as_posix()}
        )
    diagnostics.extend(_overlapping_root_diagnostics(roots))
    for path in root.rglob("ARCHITECTURE_*.toml"):
        relative_path = path.relative_to(root)
        relative = relative_path.as_posix()
        if any(part.startswith(".") for part in relative_path.parts):
            continue
        if path.name in _REGISTRY_NAMES and relative not in declared_registries:
            diagnostics.append(
                Diagnostic(
                    "POLICY002",
                    relative,
                    "architecture state must be owned by exactly one product registry; remove repository-wide or undeclared state",
                )
            )
    crate_names = Counter(crate.name for crate in policy.rust_crates)
    for crate in policy.rust_crates:
        if crate.product not in products:
            diagnostics.append(
                Diagnostic(
                    "POLICY003",
                    "ARCHITECTURE_POLICY.toml",
                    f"crate {crate.name} names unknown product {crate.product}",
                )
            )
        if crate_names[crate.name] > 1:
            diagnostics.append(
                Diagnostic(
                    "POLICY004",
                    "ARCHITECTURE_POLICY.toml",
                    f"crate {crate.name} is declared more than once",
                )
            )
    diagnostics.extend(_category_diagnostics(root, policy))
    return diagnostics


def owner_for_path(policy: ArchitecturePolicy, path: str) -> str | None:
    """Return the sole product that owns an exact repository source path."""
    normalized = PurePosixPath(path).as_posix()
    owners = {
        product.name
        for product in policy.python_products
        if _is_within(normalized, product.root.as_posix())
    }
    owners.update(
        crate.product
        for crate in policy.rust_crates
        if _is_within(normalized, f"crates/{crate.name}")
    )
    return next(iter(owners)) if len(owners) == 1 else None


def path_is_exact(path: str) -> bool:
    """Return whether a registry path is repository-relative and unglobbed."""
    candidate = PurePosixPath(path.replace("\\", "/"))
    return not (
        candidate.is_absolute()
        or ".." in candidate.parts
        or any(marker in path for marker in _GLOB_MARKERS)
    )


def _validate_product_policy(
    root: Path,
    product: str,
    source_root: Path,
    debt_registry: Path,
    waiver_registry: Path,
) -> list[Diagnostic]:
    """Validate one product's source and architecture-state declarations."""
    diagnostics: list[Diagnostic] = []
    expected_parent = PurePosixPath("packages") / product
    expected = {
        debt_registry: expected_parent / "ARCHITECTURE_DEBT.toml",
        waiver_registry: expected_parent / "ARCHITECTURE_WAIVERS.toml",
    }
    if not (root / source_root).is_dir():
        diagnostics.append(
            Diagnostic(
                "POLICY005",
                source_root.as_posix(),
                f"{product} production source root does not exist",
            )
        )
    for actual, required in expected.items():
        if PurePosixPath(actual.as_posix()) != required:
            diagnostics.append(
                Diagnostic(
                    "POLICY006",
                    actual.as_posix(),
                    f"{product} registry must be {required.as_posix()}",
                )
            )
        if not (root / actual).is_file():
            diagnostics.append(
                Diagnostic(
                    "POLICY007",
                    actual.as_posix(),
                    "declared product architecture registry is missing",
                )
            )
    return diagnostics


def _overlapping_root_diagnostics(
    roots: list[tuple[str, str]],
) -> list[Diagnostic]:
    """Reject production roots that can assign a path to multiple products."""
    diagnostics: list[Diagnostic] = []
    for index, (product, path) in enumerate(roots):
        for other_product, other_path in roots[index + 1 :]:
            if _is_within(path, other_path) or _is_within(other_path, path):
                diagnostics.append(
                    Diagnostic(
                        "POLICY008",
                        "ARCHITECTURE_POLICY.toml",
                        f"{product} and {other_product} production roots overlap",
                    )
                )
    return diagnostics


def _category_diagnostics(
    root: Path,
    policy: ArchitecturePolicy,
) -> list[Diagnostic]:
    """Validate exact, used structural metric categories."""
    diagnostics: list[Diagnostic] = []
    category_paths = Counter(
        category.path.as_posix() for category in policy.structure_categories
    )
    for category in policy.structure_categories:
        path = category.path.as_posix()
        if category_paths[path] > 1:
            diagnostics.append(
                Diagnostic(
                    "POLICY009",
                    path,
                    "structural category paths must be unique",
                )
            )
        if not path_is_exact(path) or not (root / category.path).is_file():
            diagnostics.append(
                Diagnostic(
                    "POLICY010",
                    path,
                    "structural category must name one existing exact source file",
                )
            )
        if owner_for_path(policy, path) != category.product:
            diagnostics.append(
                Diagnostic(
                    "POLICY011",
                    path,
                    f"structural category is not owned by {category.product}",
                )
            )
    return diagnostics


def _is_within(path: str, root: str) -> bool:
    """Return whether a normalized path equals or descends from a root."""
    return path == root or path.startswith(f"{root.rstrip('/')}/")
