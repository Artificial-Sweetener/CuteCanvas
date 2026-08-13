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
"""Validate dependency direction and package-owned public demo boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

from .model import ProductContract

_GENERATED_PYTHON_DIRECTORY_NAMES = frozenset({".venv", "__pycache__", "venv"})

try:
    from tools.architecture.policy import load_policy
    from tools.architecture.python_validation import validate_python
except ModuleNotFoundError:  # Script execution places tools on sys.path.
    from architecture.policy import load_policy
    from architecture.python_validation import validate_python


def validate_boundaries(
    root: Path,
    products: tuple[ProductContract, ...],
) -> list[str]:
    """Return declarative product-boundary and public-demo violations."""
    policy = load_policy(root / "ARCHITECTURE_POLICY.toml")
    errors = [
        diagnostic.render()
        for diagnostic in validate_python(root, policy)
        if diagnostic.severity == "error"
    ]
    root_examples = root / "examples"
    if _owns_python_examples(root_examples):
        errors.append("repository root must not own Python product examples")
    for product in products:
        examples = product.root / "examples"
        demos = {path.resolve() for path in examples.glob("*_demo.py")}
        expected = {
            path.resolve()
            for path in product.demo_paths
            if path.name.endswith("_demo.py")
        }
        if demos != expected:
            errors.append(
                f"{product.package} examples: expected exactly "
                f"{sorted(path.name for path in expected)}, found "
                f"{sorted(path.name for path in demos)}"
            )
    return errors


def _owns_python_examples(examples: Path) -> bool:
    """Return whether a directory contains source rather than generated environments."""
    if not examples.exists():
        return False
    for path in examples.rglob("*.py"):
        relative_parts = (part.casefold() for part in path.relative_to(examples).parts)
        if all(
            part not in _GENERATED_PYTHON_DIRECTORY_NAMES
            and not part.startswith("venv-")
            for part in relative_parts
        ):
            return True
    return False


def _forbidden_imports(source: Path, forbidden_root: str) -> list[str]:
    """Return imports that violate the repository's dependency direction."""
    errors: list[str] = []
    for path in source.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                modules = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = (node.module,)
            if any(
                module == forbidden_root or module.startswith(f"{forbidden_root}.")
                for module in modules
            ):
                errors.append(
                    f"{path}:{node.lineno} imports forbidden package {forbidden_root}"
                )
    return errors


def _private_dependency_imports(source: Path, dependency_root: str) -> list[str]:
    """Return imports outside a dependency's facade and integration SDK."""
    errors: list[str] = []
    for path in (*source.rglob("*.py"), *source.rglob("*.pyi")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        lines: list[int] = []
        for node in ast.walk(tree):
            modules: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                modules = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = (node.module,)
            if any(
                module.startswith(f"{dependency_root}.")
                and module != f"{dependency_root}.sdk"
                and not module.startswith(f"{dependency_root}.sdk.")
                for module in modules
            ):
                lines.append(node.lineno)
        if lines:
            positions = ", ".join(str(line) for line in sorted(set(lines)))
            errors.append(
                f"{path}:{positions} bypasses the supported {dependency_root} "
                "facade or SDK"
            )
    return errors
