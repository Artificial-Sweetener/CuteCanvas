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
"""Validate product-local debt and waiver snapshots against current source."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from .model import (
    ArchitectureDebt,
    ArchitecturePolicy,
    ArchitectureWaiver,
    Diagnostic,
    ProductArchitectureState,
)
from .policy_validation import owner_for_path, path_is_exact, validate_policy_ownership
from .registry import load_product_state
from .source_metrics import production_line_count, source_fingerprint


def validate_architecture_state(
    root: Path,
    policy: ArchitecturePolicy,
    *,
    today: date | None = None,
) -> tuple[tuple[ProductArchitectureState, ...], list[Diagnostic]]:
    """Load and validate all product state against current source facts."""
    current_date = today or datetime.now(timezone.utc).date()
    diagnostics = validate_policy_ownership(root, policy)
    states: list[ProductArchitectureState] = []
    for product in policy.python_products:
        state, load_diagnostics = load_product_state(root, product)
        diagnostics.extend(load_diagnostics)
        if state is not None:
            states.append(state)
    diagnostics.extend(_validate_unique_record_ids(states))
    diagnostics.extend(_validate_records(root, policy, states, current_date))
    return tuple(states), diagnostics


def _validate_unique_record_ids(
    states: list[ProductArchitectureState],
) -> list[Diagnostic]:
    """Reject IDs reused across products or record kinds."""
    identifiers = [
        record.identifier
        for state in states
        for record in (*state.debts, *state.waivers)
    ]
    duplicates = sorted(
        identifier for identifier, count in Counter(identifiers).items() if count > 1
    )
    return [
        Diagnostic(
            "STATE002",
            "ARCHITECTURE_POLICY.toml",
            f"architecture record id {identifier} is not globally unique",
        )
        for identifier in duplicates
    ]


def _validate_records(
    root: Path,
    policy: ArchitecturePolicy,
    states: list[ProductArchitectureState],
    today: date,
) -> list[Diagnostic]:
    """Validate exact paths, fingerprints, deadlines, bounds, and links."""
    diagnostics: list[Diagnostic] = []
    debts = {debt.identifier: debt for state in states for debt in state.debts}
    debt_paths: Counter[str] = Counter(
        path for debt in debts.values() for path in debt.paths
    )
    for debt in debts.values():
        registry = _debt_registry_path(debt.product)
        valid_paths = True
        for path in debt.paths:
            path_valid = _validate_record_path(
                root,
                policy,
                debt.product,
                path,
                registry,
                debt.identifier,
                diagnostics,
            )
            valid_paths = valid_paths and path_valid
            if debt_paths[path] > 1:
                diagnostics.append(
                    Diagnostic(
                        "DEBT001",
                        registry,
                        f"source path {path} appears in multiple debt records",
                    )
                )
        if debt.review_by < today:
            diagnostics.append(
                Diagnostic(
                    "DEBT002",
                    registry,
                    f"debt {debt.identifier} review deadline expired on {debt.review_by.isoformat()}",
                )
            )
        if valid_paths:
            actual = source_fingerprint(root, debt.paths)
            if actual != debt.fingerprint:
                diagnostics.append(
                    Diagnostic(
                        "DEBT003",
                        registry,
                        f"debt {debt.identifier} no longer matches assessed source. Reassess only current facts: replace its responsibilities, paths, next extraction, and fingerprint; tighten any remediation limit; or delete resolved debt and its linked waiver. Do not append review or improvement history.",
                    )
                )
    for state in states:
        for waiver in state.waivers:
            diagnostics.extend(_validate_waiver(root, policy, waiver, debts, today))
    return diagnostics


def _validate_waiver(
    root: Path,
    policy: ArchitecturePolicy,
    waiver: ArchitectureWaiver,
    debts: dict[str, ArchitectureDebt],
    today: date,
) -> list[Diagnostic]:
    """Validate one waiver's exact ownership, deadline, cap, and debt link."""
    diagnostics: list[Diagnostic] = []
    registry = _waiver_registry_path(waiver.product)
    valid_path = _validate_record_path(
        root,
        policy,
        waiver.product,
        waiver.path,
        registry,
        waiver.identifier,
        diagnostics,
    )
    if waiver.review_by < today:
        diagnostics.append(
            Diagnostic(
                "WAIVER001",
                registry,
                f"waiver {waiver.identifier} review deadline expired on {waiver.review_by.isoformat()}",
            )
        )
    if valid_path:
        lines = production_line_count(root / waiver.path)
        if lines > waiver.max_lines:
            diagnostics.append(
                Diagnostic(
                    "WAIVER002",
                    registry,
                    f"waiver {waiver.identifier} caps {waiver.path} at {waiver.max_lines} lines but current source has {lines}",
                )
            )
        if waiver.kind == "remediation" and lines != waiver.max_lines:
            diagnostics.append(
                Diagnostic(
                    "WAIVER003",
                    registry,
                    f"remediation waiver {waiver.identifier} must tighten max_lines to the current {lines} lines",
                )
            )
    if waiver.kind == "remediation":
        debt = debts.get(waiver.debt or "")
        if (
            debt is None
            or debt.product != waiver.product
            or waiver.path not in debt.paths
        ):
            diagnostics.append(
                Diagnostic(
                    "WAIVER004",
                    registry,
                    f"remediation waiver {waiver.identifier} must link debt for the same product and exact path",
                )
            )
        if waiver.next_limit is None or waiver.next_limit >= waiver.max_lines:
            diagnostics.append(
                Diagnostic(
                    "WAIVER005",
                    registry,
                    f"remediation waiver {waiver.identifier} next_limit must be lower than max_lines and follow from its debt extraction",
                )
            )
    return diagnostics


def _validate_record_path(
    root: Path,
    policy: ArchitecturePolicy,
    product: str,
    path: str,
    registry: str,
    identifier: str,
    diagnostics: list[Diagnostic],
) -> bool:
    """Validate one exact current source path and append actionable failures."""
    exact = path_is_exact(path)
    exists = (root / path).is_file() if exact else False
    owned = owner_for_path(policy, path) == product if exact else False
    if not exact or not exists or not owned:
        diagnostics.append(
            Diagnostic(
                "STATE003",
                registry,
                f"record {identifier} path {path!r} must be one existing exact source file owned by {product}",
            )
        )
    return exact and exists and owned


def _debt_registry_path(product: str) -> str:
    """Return the required debt registry path for a product."""
    return f"packages/{product}/ARCHITECTURE_DEBT.toml"


def _waiver_registry_path(product: str) -> str:
    """Return the required waiver registry path for a product."""
    return f"packages/{product}/ARCHITECTURE_WAIVERS.toml"
