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
"""Parse product-local architecture state as strict current snapshots."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any, cast

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 only
    import tomli as tomllib

from .model import (
    ArchitectureDebt,
    ArchitectureWaiver,
    Diagnostic,
    ProductArchitectureState,
    PythonProductPolicy,
)

_DEBT_KEYS = {
    "id",
    "owner",
    "paths",
    "fingerprint",
    "issue",
    "review_by",
    "responsibilities",
    "next_extraction",
}
_WAIVER_KEYS = {
    "id",
    "owner",
    "rule",
    "path",
    "kind",
    "justification",
    "issue",
    "review_by",
    "max_lines",
    "next_limit",
    "debt",
}


def load_product_state(
    root: Path,
    product: PythonProductPolicy,
) -> tuple[ProductArchitectureState | None, list[Diagnostic]]:
    """Load one product's debt and waiver registries without leaking errors."""
    try:
        debts = _load_debts(root / product.debt_registry, product.name)
        waivers = _load_waivers(root / product.waiver_registry, product.name)
    except (OSError, TypeError, ValueError) as exc:
        return None, [
            Diagnostic(
                "STATE001",
                f"packages/{product.name}",
                f"invalid architecture state: {exc}",
            )
        ]
    return ProductArchitectureState(product.name, debts, waivers), []


def _load_debts(path: Path, product: str) -> tuple[ArchitectureDebt, ...]:
    """Parse one strict debt snapshot document."""
    data = _document(path, product, "debts")
    items = _tables(data, "debts")
    debts = tuple(_parse_debt(item, product, index) for index, item in enumerate(items))
    _unique_ids((item.identifier for item in debts), path)
    return debts


def _load_waivers(path: Path, product: str) -> tuple[ArchitectureWaiver, ...]:
    """Parse one strict waiver snapshot document."""
    data = _document(path, product, "waivers")
    items = _tables(data, "waivers")
    waivers = tuple(
        _parse_waiver(item, product, index) for index, item in enumerate(items)
    )
    _unique_ids((item.identifier for item in waivers), path)
    return waivers


def _document(path: Path, product: str, collection: str) -> dict[str, Any]:
    """Read and validate one registry document envelope."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    expected = {"schema_version", "product", collection}
    unknown = set(data) - expected
    if unknown:
        raise ValueError(f"{path} contains unsupported fields {sorted(unknown)}")
    if data.get("schema_version") != 1:
        raise ValueError(f"{path} must declare schema_version = 1")
    if data.get("product") != product:
        raise ValueError(f"{path} must declare product = {product!r}")
    return data


def _parse_debt(
    data: dict[str, Any],
    product: str,
    index: int,
) -> ArchitectureDebt:
    """Parse one debt record containing only current mixed-ownership facts."""
    _exact_keys(data, _DEBT_KEYS, f"debt {index}")
    responsibilities = _strings(data, "responsibilities")
    if len(responsibilities) < 2:
        raise ValueError(f"debt {index} must name at least two mixed responsibilities")
    return ArchitectureDebt(
        identifier=_string(data, "id"),
        product=product,
        owner=_string(data, "owner"),
        paths=_strings(data, "paths"),
        fingerprint=_string(data, "fingerprint"),
        issue=_string(data, "issue"),
        review_by=_date(data, "review_by"),
        responsibilities=responsibilities,
        next_extraction=_string(data, "next_extraction"),
    )


def _parse_waiver(
    data: dict[str, Any],
    product: str,
    index: int,
) -> ArchitectureWaiver:
    """Parse one exact, bounded architecture exception."""
    required = _WAIVER_KEYS - {"next_limit", "debt"}
    kind = _string(data, "kind")
    if kind == "remediation":
        required |= {"next_limit", "debt"}
    elif kind != "structural":
        raise ValueError(f"waiver {index} kind must be structural or remediation")
    _exact_keys(data, required, f"waiver {index}")
    return ArchitectureWaiver(
        identifier=_string(data, "id"),
        product=product,
        owner=_string(data, "owner"),
        rule=_string(data, "rule"),
        path=_string(data, "path"),
        kind=kind,
        justification=_string(data, "justification"),
        issue=_string(data, "issue"),
        review_by=_date(data, "review_by"),
        max_lines=_integer(data, "max_lines"),
        next_limit=_integer(data, "next_limit") if kind == "remediation" else None,
        debt=_string(data, "debt") if kind == "remediation" else None,
    )


def _exact_keys(data: dict[str, Any], expected: set[str], label: str) -> None:
    """Reject missing fields and history-shaped surplus fields."""
    missing = expected - set(data)
    unknown = set(data) - expected
    if missing or unknown:
        raise ValueError(
            f"{label} fields differ: missing={sorted(missing)}, unsupported={sorted(unknown)}"
        )


def _tables(data: dict[str, Any], key: str) -> tuple[dict[str, Any], ...]:
    """Return a validated registry array."""
    value = data.get(key, [])
    if not isinstance(value, list):
        raise TypeError(f"{key} must be an array of tables")
    items = cast(list[object], value)
    if not all(isinstance(item, dict) for item in items):
        raise TypeError(f"{key} must be an array of tables")
    return tuple(cast(dict[str, Any], item) for item in items)


def _string(data: dict[str, Any], key: str) -> str:
    """Return one required nonempty string."""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a nonempty string")
    return value


def _strings(data: dict[str, Any], key: str) -> tuple[str, ...]:
    """Return one required nonempty array of unique strings."""
    value = data.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{key} must be a nonempty string array")
    items = cast(list[object], value)
    if not all(isinstance(item, str) and item.strip() for item in items):
        raise ValueError(f"{key} must contain nonempty strings")
    strings = tuple(cast(list[str], items))
    if len(strings) != len(set(strings)):
        raise ValueError(f"{key} must not contain duplicates")
    return strings


def _integer(data: dict[str, Any], key: str) -> int:
    """Return one required positive integer."""
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{key} must be a positive integer")
    return value


def _date(data: dict[str, Any], key: str) -> date:
    """Return one required TOML date."""
    value = data.get(key)
    if not isinstance(value, date):
        raise TypeError(f"{key} must be an ISO date")
    return value


def _unique_ids(identifiers: Iterable[str], path: Path) -> None:
    """Reject duplicate record identifiers within one registry."""
    values = tuple(identifiers)
    if len(values) != len(set(values)):
        raise ValueError(f"{path} record ids must be unique")
