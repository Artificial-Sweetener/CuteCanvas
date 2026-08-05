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
"""Keep tutorial demos on supported package facades and public names."""

from __future__ import annotations

import ast
import importlib
from collections.abc import Iterator
from pathlib import Path

from .model import ProductContract

_PRODUCT_PACKAGES = {"ferrastra", "qpane", "cutecanvas"}
_ALLOWED_PRODUCT_IMPORTS = {
    "ferrastra": {"ferrastra"},
    "qpane": {"ferrastra", "qpane"},
    "cutecanvas": {"ferrastra", "qpane", "cutecanvas"},
}


def validate_demo(product: ProductContract) -> list[str]:
    """Return private, cross-boundary, and unavailable tutorial import errors."""
    errors: list[str] = []
    allowed_packages = _ALLOWED_PRODUCT_IMPORTS[product.package]
    exports = {
        package: set(importlib.import_module(package).__all__)
        for package in allowed_packages
    }
    found_paths = tuple(_python_paths(product.demo_paths))
    if not found_paths:
        return [f"{product.package}: tutorial demo sources are missing"]
    for path in found_paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        if ast.get_docstring(tree) is None:
            errors.append(
                f"{product.package}: {path} lacks a tutorial module docstring"
            )
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".", 1)[0]
                if root not in _PRODUCT_PACKAGES:
                    continue
                if root not in allowed_packages:
                    errors.append(
                        f"{product.package}: {path}:{node.lineno} imports forbidden "
                        f"product {root}"
                    )
                elif node.module != root:
                    errors.append(
                        f"{product.package}: {path}:{node.lineno} bypasses the "
                        f"{root} facade via {node.module}"
                    )
                else:
                    errors.extend(
                        f"{product.package}: {path}:{node.lineno} imports unavailable "
                        f"{root} symbol {alias.name!r}"
                        for alias in node.names
                        if alias.name != "*" and alias.name not in exports[root]
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root not in _PRODUCT_PACKAGES:
                        continue
                    if root not in allowed_packages:
                        errors.append(
                            f"{product.package}: {path}:{node.lineno} imports "
                            f"forbidden product {root}"
                        )
                    elif alias.name != root:
                        errors.append(
                            f"{product.package}: {path}:{node.lineno} bypasses the "
                            f"{root} facade via {alias.name}"
                        )
    return errors


def _python_paths(paths: tuple[Path, ...]) -> Iterator[Path]:
    """Yield tutorial Python sources once in deterministic order."""
    seen: set[Path] = set()
    for root in paths:
        candidates = (root,) if root.is_file() else tuple(sorted(root.rglob("*.py")))
        for path in candidates:
            if path not in seen:
                seen.add(path)
                yield path
