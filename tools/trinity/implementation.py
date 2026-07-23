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
"""Verify that runtime package facades realize their typed contracts."""

from __future__ import annotations

import ast
import importlib
import inspect
import textwrap
from dataclasses import fields, is_dataclass
from types import ModuleType
from typing import Any

from .model import ProductContract
from .stubs import StubContract


def validate_implementation(
    product: ProductContract,
    contract: StubContract,
) -> tuple[set[str], list[str]]:
    """Return runtime exports and implementation-contract violations."""
    module = importlib.import_module(product.package)
    exports = _module_exports(module)
    errors = [
        f"{product.package}: exported symbol {name!r} is absent from the stub"
        for name in sorted(exports - set(contract.top_level))
    ]
    errors.extend(
        f"{product.package}: stub symbol {name!r} is not exported"
        for name in sorted(set(contract.top_level) - exports)
    )
    errors.extend(
        f"{product.package}: exported symbol {name!r} is unavailable at runtime"
        for name in sorted(exports)
        if not hasattr(module, name)
    )
    for qualified in sorted(contract.members):
        class_name, member_name = qualified.split(".", 1)
        runtime_class = getattr(module, class_name, None)
        if runtime_class is not None and not _class_realizes_member(
            runtime_class,
            member_name,
        ):
            errors.append(
                f"{product.package}: stubbed member {qualified!r} is unavailable "
                "at runtime"
            )
    return exports, errors


def _module_exports(module: ModuleType) -> set[str]:
    """Return the explicit public exports from a package facade."""
    exported = getattr(module, "__all__", None)
    if not isinstance(exported, (list, tuple)) or not all(
        isinstance(name, str) for name in exported
    ):
        raise TypeError(f"{module.__name__}.__all__ must be a sequence of strings")
    return set(exported)


def _class_realizes_member(runtime_class: Any, member_name: str) -> bool:
    """Return whether a runtime class exposes or initializes one stubbed member."""
    if hasattr(runtime_class, member_name):
        return True
    annotations = getattr(runtime_class, "__annotations__", {})
    if member_name in annotations:
        return True
    if is_dataclass(runtime_class) and member_name in {
        field.name for field in fields(runtime_class)
    }:
        return True
    return member_name in _initialized_attributes(runtime_class)


def _initialized_attributes(runtime_class: Any) -> set[str]:
    """Return ``self`` attributes assigned by product-owned class implementations."""
    attributes: set[str] = set()
    for owner in runtime_class.__mro__:
        if owner is object or not owner.__module__.startswith(("qpane", "cutecanvas")):
            continue
        try:
            tree = ast.parse(textwrap.dedent(inspect.getsource(owner)))
        except (OSError, TypeError, IndentationError, SyntaxError):
            continue
        for node in ast.walk(tree):
            targets: tuple[ast.expr, ...] = ()
            if isinstance(node, ast.Assign):
                targets = tuple(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = (node.target,)
            for target in targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    attributes.add(target.attr)
    return attributes
