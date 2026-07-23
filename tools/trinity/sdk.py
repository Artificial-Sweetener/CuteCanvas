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
"""Validate QPane's typed advanced integration SDK namespaces."""

from __future__ import annotations

import importlib
from types import ModuleType

from .model import ProductContract
from .stubs import StubContract, parse_stub_contract


def validate_sdk(product: ProductContract) -> tuple[set[str], list[str]]:
    """Return documented SDK symbols and typed namespace violations."""
    if product.package != "qpane":
        return set(), []
    sdk_source = product.source / "sdk"
    package_stub = sdk_source / "__init__.pyi"
    package_module = importlib.import_module("qpane.sdk")
    errors = _validate_module_contract(
        "qpane.sdk",
        package_module,
        parse_stub_contract(package_stub),
    )
    symbols: set[str] = set()
    for stub in sorted(sdk_source.glob("*.pyi")):
        if stub == package_stub:
            continue
        module_name = f"qpane.sdk.{stub.stem}"
        contract = parse_stub_contract(stub)
        module = importlib.import_module(module_name)
        errors.extend(_validate_module_contract(module_name, module, contract))
        symbols.update(contract.top_level)
        symbols.update(contract.members)
    return symbols, errors


def _validate_module_contract(
    label: str,
    module: ModuleType,
    contract: StubContract,
) -> list[str]:
    """Return export and availability differences for one SDK namespace."""
    declared = set(contract.top_level)
    runtime = getattr(module, "__all__", None)
    if not isinstance(runtime, (list, tuple)) or not all(
        isinstance(name, str) for name in runtime
    ):
        return [f"{label}: __all__ must be a sequence of strings"]
    exported = set(runtime)
    errors = [
        f"{label}: exported symbol {name!r} is absent from its stub"
        for name in sorted(exported - declared)
    ]
    errors.extend(
        f"{label}: stub symbol {name!r} is not exported"
        for name in sorted(declared - exported)
    )
    errors.extend(
        f"{label}: exported symbol {name!r} is unavailable at runtime"
        for name in sorted(exported)
        if not hasattr(module, name)
    )
    return errors
