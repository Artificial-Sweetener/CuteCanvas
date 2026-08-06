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

"""Select policy-required proof from repository-relative changed paths."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePosixPath

from tools.testing.model import (
    SelectionReason,
    TestGroup,
    TestPolicy,
    TestSelection,
)
from tools.testing.policy import path_matches_pattern

_ARTIFACT_SUFFIXES = {".md", ".rst", ".txt"}


class SelectionError(ValueError):
    """Explain why changed work cannot be mapped to authoritative proof."""


def normalize_path(path: str) -> str:
    """Normalize supported-platform paths to repository-relative POSIX form."""
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return str(PurePosixPath(normalized))


def select_changed_paths(
    paths: Iterable[str],
    policies: dict[str, TestPolicy],
    *,
    commit: bool = False,
) -> TestSelection:
    """Return the monotonic policy selection for the supplied changed paths."""
    reasons: set[SelectionReason] = set()
    validate_artifacts = False
    for raw_path in paths:
        path = normalize_path(raw_path)
        path_reasons, artifact_only = _select_path(path, policies)
        reasons.update(path_reasons)
        validate_artifacts = validate_artifacts or artifact_only
    groups = frozenset(reason.group for reason in reasons)
    if commit:
        affected = {group.product for group in groups}
        groups = frozenset(
            group for product in affected for group in policies[product].groups()
        )
        reasons.update(
            SelectionReason("<staged>", "complete affected product gate", group)
            for group in groups
            if group not in {reason.group for reason in reasons}
        )
    return TestSelection(
        groups=groups,
        reasons=tuple(sorted(reasons, key=_reason_key)),
        validate_artifacts=validate_artifacts,
    )


def _select_path(
    path: str,
    policies: dict[str, TestPolicy],
) -> tuple[set[SelectionReason], bool]:
    """Select proof for one path or fail with a corrective ownership decision."""
    if path.startswith("tests/"):
        return (
            {
                SelectionReason(
                    path,
                    "removed root product-test path requires conservative proof",
                    group,
                )
                for policy in policies.values()
                for group in policy.groups()
            },
            False,
        )
    if path.startswith("examples/"):
        return (
            {
                SelectionReason(
                    path,
                    "removed root product example requires conservative proof",
                    group,
                )
                for policy in policies.values()
                if policy.product != "repository"
                for group in policy.groups()
            },
            False,
        )
    test_matches = _test_path_matches(path, policies)
    if test_matches:
        if len(test_matches) != 1:
            raise SelectionError(_ambiguous_message(path, test_matches))
        product, area, proof = next(iter(test_matches))
        group = TestGroup(product, area, proof)
        return {SelectionReason(path, "changed owned test", group)}, False
    test_owner = _test_infrastructure_owner(path, policies)
    if test_owner is not None:
        return {
            SelectionReason(
                path,
                "changed package test fixture, support, or removed flat test",
                group,
            )
            for group in test_owner.groups()
        }, False
    policy_matches = [
        policy for policy in policies.values() if path == _relative_policy_path(policy)
    ]
    if policy_matches:
        policy = policy_matches[0]
        return {
            SelectionReason(path, "changed product test policy", group)
            for group in policy.groups()
        }, False
    source_matches = _source_matches(path, policies)
    if source_matches:
        if len(source_matches) != 1:
            raise SelectionError(_ambiguous_message(path, source_matches))
        product, area_name = next(iter(source_matches))
        selected = {
            SelectionReason(
                path,
                f"{product}.{area_name} production ownership",
                group,
            )
            for group in _area_groups(policies[product], area_name)
        }
        selected.update(_subscriber_reasons(path, product, area_name, policies))
        return selected, False
    if PurePosixPath(path).suffix.lower() in _ARTIFACT_SUFFIXES:
        return set(), True
    raise SelectionError(
        f"{path}: no test policy owns this changed path. Identify its product "
        "and behavioral area, then update that product's TEST_POLICY.toml. "
        "A runtime change is not allowed to select zero tests."
    )


def _test_path_matches(
    path: str,
    policies: dict[str, TestPolicy],
) -> set[tuple[str, str, str]]:
    """Return declared groups whose physical test directory contains ``path``."""
    matches: set[tuple[str, str, str]] = set()
    for policy in policies.values():
        prefix = f"{policy.test_root.rstrip('/')}/"
        if not path.startswith(prefix):
            continue
        relative = path.removeprefix(prefix)
        parts = relative.split("/")
        if len(parts) >= 3:
            candidate = TestGroup(policy.product, parts[0], parts[1])
            if candidate in policy.groups():
                matches.add((candidate.product, candidate.area, candidate.proof))
    return matches


def _source_matches(
    path: str,
    policies: dict[str, TestPolicy],
) -> set[tuple[str, str]]:
    """Return every production area whose current patterns match ``path``."""
    return {
        (policy.product, area.name)
        for policy in policies.values()
        for area in policy.areas
        if any(path_matches_pattern(path, pattern) for pattern in area.sources)
    }


def _test_infrastructure_owner(
    path: str,
    policies: dict[str, TestPolicy],
) -> TestPolicy | None:
    """Return the sole package whose test tree contains an ungrouped path."""
    matches = [
        policy
        for policy in policies.values()
        if path == policy.test_root or path.startswith(f"{policy.test_root}/")
    ]
    if len(matches) > 1:
        raise SelectionError(_ambiguous_message(path, matches))
    return matches[0] if matches else None


def _area_groups(policy: TestPolicy, area_name: str) -> frozenset[TestGroup]:
    """Return all required proof for one authoritative behavior area."""
    area = policy.area(area_name)
    return frozenset(
        TestGroup(policy.product, area.name, proof) for proof in area.proofs
    )


def _subscriber_reasons(
    path: str,
    owner_product: str,
    owner_area: str,
    policies: dict[str, TestPolicy],
) -> set[SelectionReason]:
    """Select consumer-owned contract subscriptions for a changed boundary."""
    reasons: set[SelectionReason] = set()
    owner = policies[owner_product]
    exposed = {
        boundary.name for boundary in owner.boundaries if boundary.area == owner_area
    }
    for consumer in policies.values():
        for subscription in consumer.subscriptions:
            if (
                subscription.owner != owner_product
                or subscription.boundary not in exposed
            ):
                continue
            for group_path in subscription.groups:
                area, proof = group_path.split("/", maxsplit=1)
                reasons.add(
                    SelectionReason(
                        path,
                        f"{consumer.product} subscribes to "
                        f"{owner_product}.{subscription.boundary}",
                        TestGroup(consumer.product, area, proof),
                    )
                )
    return reasons


def _relative_policy_path(policy: TestPolicy) -> str:
    """Return one policy path relative to the repository root."""
    parts = policy.path.resolve().parts
    for marker in ("packages", "tools"):
        if marker in parts:
            return "/".join(parts[parts.index(marker) :])
    return policy.path.name


def _ambiguous_message(path: str, matches: object) -> str:
    """Explain an ambiguous mapping and the required policy correction."""
    return (
        f"{path}: multiple test-policy owners match: {sorted(matches)!r}. "
        "Assign exactly one authoritative product and behavioral area; use "
        "consumer subscriptions for downstream proof instead of overlapping sources."
    )


def _reason_key(reason: SelectionReason) -> tuple[str, str, str, str, str]:
    """Provide deterministic diagnostic ordering."""
    return (
        reason.changed_path,
        reason.group.product,
        reason.group.area,
        reason.group.proof,
        reason.rule,
    )
