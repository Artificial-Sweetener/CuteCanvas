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
"""Validate dependency direction and the two-product example boundary."""

from __future__ import annotations

import ast
from pathlib import Path

from .model import ProductContract

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
    del products
    policy = load_policy(root / "ARCHITECTURE_POLICY.toml")
    errors = [
        diagnostic.render()
        for diagnostic in validate_python(root, policy)
        if diagnostic.severity == "error"
    ]
    demos = {path.name for path in (root / "examples").glob("*_demo.py")}
    expected = {"ferrastra_demo.py", "qpane_demo.py", "cutecanvas_demo.py"}
    if demos != expected:
        errors.append(
            f"examples: expected exactly {sorted(expected)}, found {sorted(demos)}"
        )
    return errors


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
