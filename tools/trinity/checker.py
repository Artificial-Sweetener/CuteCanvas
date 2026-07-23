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
"""Orchestrate every independently owned Public API Trinity pillar."""

from __future__ import annotations

import sys
from pathlib import Path

from .boundaries import validate_boundaries
from .configuration import validate_configuration
from .demo import validate_demo
from .documentation import validate_documentation
from .implementation import validate_implementation
from .model import ProductContract, repository_products
from .provisioning import validate_demo_provisioning
from .sdk import validate_sdk
from .stubs import parse_stub_contract


def validate_product(product: ProductContract) -> list[str]:
    """Return all contract, implementation, docs, config, and demo violations."""
    contract = parse_stub_contract(product.stub)
    exports, errors = validate_implementation(product, contract)
    sdk_symbols, sdk_errors = validate_sdk(product)
    errors.extend(sdk_errors)
    documented = set(contract.members) | exports | sdk_symbols
    errors.extend(validate_documentation(product, documented))
    errors.extend(validate_configuration(product))
    errors.extend(validate_demo(product))
    return errors


def validate_repository(root: Path) -> list[str]:
    """Return every independently attributable repository Trinity violation."""
    products = repository_products(root)
    sys.path[:0] = [str(product.source.parent) for product in products]
    errors: list[str] = []
    for product in products:
        errors.extend(validate_product(product))
    errors.extend(validate_boundaries(root, products))
    errors.extend(validate_demo_provisioning(root))
    return errors


def run(root: Path) -> None:
    """Print actionable errors and fail unless every product pillar agrees."""
    errors = validate_repository(root)
    if errors:
        print(f"FAILED: Found {len(errors)} Public API Trinity violations.")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)
    print("SUCCESS: QPane and CuteCanvas independently satisfy Public API Trinity.")
