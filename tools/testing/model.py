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

"""Typed current-state model for repository test policies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, order=True)
class TestGroup:
    """Identify one product-owned behavioral area and proof kind."""

    product: str
    area: str
    proof: str


@dataclass(frozen=True)
class TestArea:
    """Map production paths to the proof kinds owned by one behavior area."""

    name: str
    sources: tuple[str, ...]
    proofs: tuple[str, ...]
    case_isolated_proofs: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublicBoundary:
    """Name a public contract and its authoritative behavior area."""

    name: str
    area: str


@dataclass(frozen=True)
class ContractSubscription:
    """Record consumer-owned proof required by an external public boundary."""

    owner: str
    boundary: str
    groups: tuple[str, ...]


@dataclass(frozen=True)
class TestPolicy:
    """Describe one product's current test ownership and required proof."""

    product: str
    path: Path
    test_root: str
    platforms: tuple[str, ...]
    areas: tuple[TestArea, ...]
    boundaries: tuple[PublicBoundary, ...]
    subscriptions: tuple[ContractSubscription, ...]

    def groups(self) -> frozenset[TestGroup]:
        """Return every test group declared by this policy."""
        return frozenset(
            TestGroup(self.product, area.name, proof)
            for area in self.areas
            for proof in area.proofs
        )

    def area(self, name: str) -> TestArea:
        """Return one declared area or raise with product context."""
        for area in self.areas:
            if area.name == name:
                return area
        raise KeyError(f"{self.product} has no test area {name!r}")

    def boundary_areas(self, boundary: str) -> frozenset[str]:
        """Return authoritative areas exposed by a named public boundary."""
        return frozenset(item.area for item in self.boundaries if item.name == boundary)


@dataclass(frozen=True)
class SelectionReason:
    """Explain why a changed path requires one test group."""

    changed_path: str
    rule: str
    group: TestGroup


@dataclass(frozen=True)
class TestSelection:
    """Contain selected groups, their reasons, and artifact-only validation."""

    groups: frozenset[TestGroup]
    reasons: tuple[SelectionReason, ...]
    validate_artifacts: bool = False
