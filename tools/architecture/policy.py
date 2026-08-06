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
"""Load and validate the machine-readable architecture policy."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 only
    import tomli as tomllib

from .model import (
    ArchitecturePolicy,
    PythonDependencyPolicy,
    PythonLayerPolicy,
    PythonProductPolicy,
    PythonProtectedRootPolicy,
    RustCratePolicy,
    StructureCategoryPolicy,
    StructurePolicy,
)


def load_policy(path: Path) -> ArchitecturePolicy:
    """Load one schema-versioned architecture policy."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 2:
        raise ValueError(f"{path} must declare schema_version = 2")
    structure_data = _mapping(data, "structure")
    return ArchitecturePolicy(
        structure=StructurePolicy(
            soft_lines=_integer(structure_data, "soft_lines"),
            hard_lines=_integer(structure_data, "hard_lines"),
            forbidden_names=frozenset(_strings(structure_data, "forbidden_names")),
        ),
        python_products=tuple(
            PythonProductPolicy(
                name=_string(item, "name"),
                root=Path(_string(item, "root")),
                debt_registry=Path(_string(item, "debt_registry")),
                waiver_registry=Path(_string(item, "waiver_registry")),
            )
            for item in _tables(data, "python_products")
        ),
        structure_categories=tuple(
            StructureCategoryPolicy(
                name=_string(item, "name"),
                product=_string(item, "product"),
                path=Path(_string(item, "path")),
                justification=_string(item, "justification"),
            )
            for item in _tables(data, "structure_categories")
        ),
        python_dependencies=tuple(
            PythonDependencyPolicy(
                source=_string(item, "source"),
                target=_string(item, "target"),
                allowed_paths=_strings(item, "allowed_paths"),
                allowed_modules=_strings(item, "allowed_modules"),
            )
            for item in _tables(data, "python_dependencies")
        ),
        python_protected_roots=tuple(
            PythonProtectedRootPolicy(
                path=Path(_string(item, "path")),
                product=_string(item, "product"),
                require_responsibility=_boolean(item, "require_responsibility"),
                detect_cycles=_boolean(item, "detect_cycles"),
                forbidden_imports=_strings(item, "forbidden_imports"),
            )
            for item in _tables(data, "python_protected_roots")
        ),
        python_layers=tuple(
            PythonLayerPolicy(
                name=_string(item, "name"),
                module_prefix=_string(item, "module_prefix"),
                allowed_internal=_strings(item, "allowed_internal"),
            )
            for item in _tables(data, "python_layers")
        ),
        rust_crates=tuple(
            RustCratePolicy(
                name=_string(item, "name"),
                product=_string(item, "product"),
                allowed_internal=frozenset(_strings(item, "allowed_internal")),
                python_boundary=bool(item.get("python_boundary", False)),
            )
            for item in _tables(data, "rust_crates")
        ),
    )


def _tables(data: dict[str, Any], key: str) -> tuple[dict[str, Any], ...]:
    """Return a validated array of TOML tables."""
    value = data.get(key, [])
    if not isinstance(value, list):
        raise TypeError(f"{key} must be an array of tables")
    items = cast(list[object], value)
    if not all(isinstance(item, dict) for item in items):
        raise ValueError(f"{key} must be an array of tables")
    return tuple(cast(dict[str, Any], item) for item in items)


def _mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    """Return one required TOML table."""
    value = data.get(key)
    if not isinstance(value, dict):
        raise TypeError(f"{key} must be a table")
    return cast(dict[str, Any], value)


def _string(data: dict[str, Any], key: str) -> str:
    """Return one required nonempty string."""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a nonempty string")
    return value


def _strings(data: dict[str, Any], key: str) -> tuple[str, ...]:
    """Return one required string array."""
    value = data.get(key)
    if not isinstance(value, list):
        raise TypeError(f"{key} must be an array of strings")
    items = cast(list[object], value)
    if not all(isinstance(item, str) for item in items):
        raise ValueError(f"{key} must be an array of strings")
    return tuple(cast(list[str], items))


def _integer(data: dict[str, Any], key: str) -> int:
    """Return one required positive integer."""
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{key} must be a positive integer")
    return value


def _boolean(data: dict[str, Any], key: str) -> bool:
    """Return one required boolean."""
    value = data.get(key)
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be a boolean")
    return value
