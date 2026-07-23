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
"""Compare documented package configuration with actual public defaults."""

from __future__ import annotations

import ast
import importlib
import re
from dataclasses import asdict, is_dataclass
from typing import Any

from .model import ProductContract


def validate_configuration(product: ProductContract) -> list[str]:
    """Return errors when the configuration reference omits or changes defaults."""
    path = product.docs / "configuration-reference.md"
    if not path.exists():
        return [f"{product.package}: configuration reference is missing: {path}"]
    documented = _documented_config(path.read_text(encoding="utf-8"))
    if isinstance(documented, str):
        return [f"{product.package}: {documented}"]
    module = importlib.import_module(product.package)
    config_type = getattr(module, product.config_class)
    actual = config_type().as_dict()
    return [
        f"{product.package}: [Config Reference] {error}"
        for error in _compare_mapping("root", documented, actual)
    ]


def _documented_config(markdown: str) -> dict[str, Any] | str:
    """Return the literal ``config`` mapping from documented Python blocks."""
    for match in re.finditer(r"```python\s*(.*?)```", markdown, re.DOTALL):
        try:
            tree = ast.parse(match.group(1))
        except SyntaxError:
            continue
        for node in tree.body:
            value: ast.expr | None = None
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "config"
                    for target in node.targets
                )
                or (
                    isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Name)
                    and node.target.id == "config"
                )
            ):
                value = node.value
            if value is not None:
                try:
                    result = ast.literal_eval(value)
                except (ValueError, TypeError) as exc:
                    return f"configuration mapping is not literal: {exc}"
                if isinstance(result, dict):
                    return result
                return "documented config value is not a mapping"
    return "configuration reference has no literal `config` mapping"


def _compare_mapping(
    path: str,
    documented: dict[str, Any],
    actual: dict[str, Any],
) -> list[str]:
    """Return recursive missing, extra, and mismatched configuration errors."""
    errors: list[str] = []
    normalized_actual = {
        key: asdict(value) if is_dataclass(value) else value
        for key, value in actual.items()
    }
    for key, value in normalized_actual.items():
        location = f"{path}.{key}"
        if key not in documented:
            errors.append(f"missing key {location}")
        elif isinstance(value, dict) and isinstance(documented[key], dict):
            errors.extend(_compare_mapping(location, documented[key], value))
        elif not _equivalent(documented[key], value):
            errors.append(
                f"value mismatch at {location}: "
                f"docs={documented[key]!r}, actual={value!r}"
            )
    errors.extend(
        f"extra key {path}.{key}" for key in documented if key not in normalized_actual
    )
    return errors


def _equivalent(documented: Any, actual: Any) -> bool:
    """Return whether common JSON-shaped documentation matches runtime values."""
    if documented == actual:
        return True
    if isinstance(actual, tuple) and isinstance(documented, list):
        return tuple(documented) == actual
    if isinstance(actual, float) and isinstance(documented, (float, int)):
        return abs(actual - documented) < 1e-9
    return False
