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

"""Load and validate product-owned test policy snapshots."""

from __future__ import annotations

import fnmatch
from functools import cache
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib

from tools.testing.model import (
    ContractSubscription,
    PublicBoundary,
    TestArea,
    TestPolicy,
)

_POLICY_PATHS = (
    "packages/qpane/TEST_POLICY.toml",
    "packages/cutecanvas/TEST_POLICY.toml",
    "packages/ferrastra/TEST_POLICY.toml",
    "tools/testing/TEST_POLICY.toml",
)
_REQUIRED_PLATFORMS = {"windows-x64", "macos-arm64", "linux-x64"}


class PolicyError(ValueError):
    """Report an invalid or incomplete current-state test policy."""


def path_matches_pattern(path: str, pattern: str) -> bool:
    """Match one repository-anchored glob with platform-neutral separators."""
    path_parts = tuple(path.replace("\\", "/").strip("/").split("/"))
    pattern_parts = tuple(pattern.replace("\\", "/").strip("/").split("/"))

    @cache
    def matches(path_index: int, pattern_index: int) -> bool:
        """Match path segments while giving ``**`` recursive semantics."""
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        active_pattern = pattern_parts[pattern_index]
        if active_pattern == "**":
            return matches(path_index, pattern_index + 1) or (
                path_index < len(path_parts) and matches(path_index + 1, pattern_index)
            )
        return (
            path_index < len(path_parts)
            and fnmatch.fnmatchcase(path_parts[path_index], active_pattern)
            and matches(path_index + 1, pattern_index + 1)
        )

    return matches(0, 0)


def repository_root() -> Path:
    """Return the repository root that owns this test runner."""
    return Path(__file__).resolve().parents[2]


def load_policies(root: Path | None = None) -> dict[str, TestPolicy]:
    """Load every authoritative product and repository test policy."""
    active_root = (root or repository_root()).resolve()
    policies = tuple(load_policy_file(active_root / path) for path in _POLICY_PATHS)
    by_product = {policy.product: policy for policy in policies}
    if len(by_product) != len(policies):
        raise PolicyError("test policy product names must be unique")
    _validate_subscriptions(by_product)
    return by_product


def load_policy_file(path: Path) -> TestPolicy:
    """Parse and validate one policy file."""
    if not path.is_file():
        raise PolicyError(f"required test policy is missing: {path}")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1:
        raise PolicyError(f"{path}: schema must be 1")
    product = _required_text(data, "product", path)
    test_root = _required_text(data, "test_root", path)
    platforms = _required_text_list(data, "platforms", path)
    missing_platforms = _REQUIRED_PLATFORMS - set(platforms)
    if missing_platforms:
        raise PolicyError(
            f"{path}: platforms omit required targets {sorted(missing_platforms)}"
        )
    if len(set(platforms)) != len(platforms):
        raise PolicyError(f"{path}: platforms must not repeat targets")
    areas = tuple(_parse_area(item, path) for item in data.get("areas", ()))
    boundaries = tuple(
        PublicBoundary(
            name=_required_text(item, "name", path),
            area=_required_text(item, "area", path),
        )
        for item in data.get("boundaries", ())
    )
    subscriptions = tuple(
        ContractSubscription(
            owner=_required_text(item, "owner", path),
            boundary=_required_text(item, "boundary", path),
            groups=_required_text_list(item, "groups", path),
        )
        for item in data.get("subscriptions", ())
    )
    if not areas:
        raise PolicyError(f"{path}: policy must declare at least one area")
    area_names = tuple(area.name for area in areas)
    if len(set(area_names)) != len(area_names):
        raise PolicyError(f"{path}: area names must be unique")
    for boundary in boundaries:
        if boundary.area not in area_names:
            raise PolicyError(
                f"{path}: boundary {boundary.name!r} names unknown area "
                f"{boundary.area!r}"
            )
    return TestPolicy(
        product=product,
        path=path,
        test_root=test_root,
        platforms=platforms,
        areas=areas,
        boundaries=boundaries,
        subscriptions=subscriptions,
    )


def _parse_area(data: dict[str, Any], path: Path) -> TestArea:
    """Parse one nonempty behavior area."""
    case_isolated_proofs = (
        _required_text_list(data, "case_isolated_proofs", path)
        if "case_isolated_proofs" in data
        else ()
    )
    serial_ci_proofs = (
        _required_text_list(data, "serial_ci_proofs", path)
        if "serial_ci_proofs" in data
        else ()
    )
    area = TestArea(
        name=_required_text(data, "name", path),
        sources=_required_text_list(data, "sources", path),
        proofs=_required_text_list(data, "proofs", path),
        case_isolated_proofs=case_isolated_proofs,
        serial_ci_proofs=serial_ci_proofs,
    )
    if not area.proofs:
        raise PolicyError(f"{path}: area {area.name!r} must require proof")
    if len(set(area.proofs)) != len(area.proofs):
        raise PolicyError(f"{path}: area {area.name!r} repeats a proof kind")
    if len(set(area.case_isolated_proofs)) != len(area.case_isolated_proofs):
        raise PolicyError(f"{path}: area {area.name!r} repeats case isolation")
    unknown_isolation = set(area.case_isolated_proofs) - set(area.proofs)
    if unknown_isolation:
        raise PolicyError(
            f"{path}: area {area.name!r} isolates unknown proof kinds "
            f"{sorted(unknown_isolation)}"
        )
    if len(set(area.serial_ci_proofs)) != len(area.serial_ci_proofs):
        raise PolicyError(f"{path}: area {area.name!r} repeats CI serialization")
    unknown_serialization = set(area.serial_ci_proofs) - set(area.proofs)
    if unknown_serialization:
        raise PolicyError(
            f"{path}: area {area.name!r} serializes unknown proof kinds "
            f"{sorted(unknown_serialization)}"
        )
    redundant_serialization = set(area.serial_ci_proofs) & set(
        area.case_isolated_proofs
    )
    if redundant_serialization:
        raise PolicyError(
            f"{path}: area {area.name!r} gives case-isolated proofs redundant "
            f"CI serialization {sorted(redundant_serialization)}"
        )
    return area


def _validate_subscriptions(policies: dict[str, TestPolicy]) -> None:
    """Require every subscription to resolve to owned boundaries and groups."""
    for consumer in policies.values():
        for subscription in consumer.subscriptions:
            owner = policies.get(subscription.owner)
            if owner is None:
                raise PolicyError(
                    f"{consumer.path}: subscription owner "
                    f"{subscription.owner!r} does not exist"
                )
            if not owner.boundary_areas(subscription.boundary):
                raise PolicyError(
                    f"{consumer.path}: {subscription.owner}."
                    f"{subscription.boundary} is not a declared boundary"
                )
            available = {f"{group.area}/{group.proof}" for group in consumer.groups()}
            unknown = set(subscription.groups) - available
            if unknown:
                raise PolicyError(
                    f"{consumer.path}: subscription names unknown consumer "
                    f"groups {sorted(unknown)}"
                )


def _required_text(data: dict[str, Any], key: str, path: Path) -> str:
    """Return one nonblank string field."""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PolicyError(f"{path}: {key} must be a nonblank string")
    return value.strip()


def _required_text_list(
    data: dict[str, Any],
    key: str,
    path: Path,
) -> tuple[str, ...]:
    """Return one string-list field without accepting implicit coercion."""
    value = data.get(key)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise PolicyError(f"{path}: {key} must be a list of nonblank strings")
    return tuple(item.strip() for item in value)
