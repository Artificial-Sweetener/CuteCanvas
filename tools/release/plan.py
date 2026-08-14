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
"""Own the immutable, serializable release plan and dependency closure."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

from .products import PRODUCTS, StableVersion, format_version

_SCHEMA = 1


class ReleasePlanError(RuntimeError):
    """Report an invalid, stale, or internally inconsistent release plan."""


@dataclass(frozen=True)
class PlannedDependency:
    """Bind one downstream requirement to an exact upstream release."""

    name: str
    version: StableVersion
    specifier: str

    @property
    def requirement(self) -> str:
        """Return canonical dependency metadata."""
        return f"{self.name}{self.specifier}"


@dataclass(frozen=True)
class PlannedArtifact:
    """Identify one immutable distribution file in a sealed plan."""

    product: str
    filename: str
    sha256: str


@dataclass(frozen=True)
class PlannedProduct:
    """Describe one product release and its exact dependency inputs."""

    name: str
    current_version: StableVersion
    version: StableVersion
    direct: bool
    dependencies: tuple[PlannedDependency, ...]
    commit_sha: str = ""

    @property
    def tag(self) -> str:
        """Return the final product-prefixed tag."""
        return f"{PRODUCTS[self.name].tag_prefix}{format_version(self.version)}"


@dataclass(frozen=True)
class ReleasePlan:
    """Describe one recoverable release transaction rooted at one source SHA."""

    source_sha: str
    plan_id: str
    products: tuple[PlannedProduct, ...]
    candidate_sha: str = ""
    artifacts: tuple[PlannedArtifact, ...] = ()

    @property
    def sealed(self) -> bool:
        """Return whether immutable artifact hashes have been attached."""
        return bool(self.candidate_sha and self.artifacts)

    @property
    def recovery_id(self) -> str:
        """Return an identity binding candidate commits and sealed artifact hashes."""
        if not self.sealed:
            raise ReleasePlanError("recovery identity requires a sealed release plan")
        return hashlib.sha256(_canonical_json(_plan_payload(self))).hexdigest()[:32]

    def with_candidate(
        self,
        candidate_sha: str,
        commits: Mapping[str, str],
    ) -> ReleasePlan:
        """Return the materialized plan with exact per-product commits."""
        products = tuple(
            replace(product, commit_sha=commits[product.name])
            for product in self.products
        )
        candidate = replace(self, candidate_sha=candidate_sha, products=products)
        _validate_plan(candidate)
        return candidate

    def with_artifacts(
        self,
        artifacts: tuple[PlannedArtifact, ...],
    ) -> ReleasePlan:
        """Return a sealed plan containing sorted artifact hashes."""
        sealed = replace(
            self,
            artifacts=tuple(
                sorted(artifacts, key=lambda item: (item.product, item.filename))
            ),
        )
        _validate_plan(sealed)
        return sealed

    def product(self, name: str) -> PlannedProduct:
        """Return one planned product by canonical name."""
        for product in self.products:
            if product.name == name:
                return product
        raise ReleasePlanError(f"release plan does not contain {name!r}")

    def to_json(self) -> str:
        """Serialize the plan in a stable human-readable form."""
        return json.dumps(_plan_payload(self), indent=2, sort_keys=True) + "\n"


def create_release_plan(
    source_sha: str,
    current_versions: Mapping[str, StableVersion],
    direct_versions: Mapping[str, StableVersion | None],
    current_requirements: Mapping[str, Mapping[str, str]],
) -> ReleasePlan:
    """Compute the complete downstream release closure without side effects."""
    _validate_sha(source_sha, "source SHA")
    _validate_planning_inputs(
        current_versions,
        direct_versions,
        current_requirements,
    )
    selected = _release_closure(direct_versions)
    planned_versions = {
        name: (
            direct_versions[name]
            if direct_versions.get(name) is not None
            else _patch(current_versions[name])
        )
        for name in selected
    }
    products: list[PlannedProduct] = []
    for name, definition in PRODUCTS.items():
        if name not in selected:
            continue
        dependencies = tuple(
            _planned_dependency(
                dependency=dependency,
                selected=selected,
                planned_versions=planned_versions,
                current_versions=current_versions,
                current_specifier=current_requirements.get(name, {}).get(
                    dependency.name, ""
                ),
            )
            for dependency in definition.dependencies
        )
        products.append(
            PlannedProduct(
                name=name,
                current_version=current_versions[name],
                version=_required_version(planned_versions[name], name),
                direct=direct_versions.get(name) is not None,
                dependencies=dependencies,
            )
        )
    identity_payload = {
        "schema": _SCHEMA,
        "source_sha": source_sha,
        "products": [_product_payload(product) for product in products],
    }
    plan_id = hashlib.sha256(_canonical_json(identity_payload)).hexdigest()[:24]
    return ReleasePlan(source_sha=source_sha, plan_id=plan_id, products=tuple(products))


def load_release_plan(path: Path) -> ReleasePlan:
    """Load and validate one serialized release plan."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != _SCHEMA:
            raise ReleasePlanError("release plan has an unsupported schema")
        products = tuple(_load_product(item) for item in payload["products"])
        artifacts = tuple(_load_artifact(item) for item in payload["artifacts"])
        plan = ReleasePlan(
            source_sha=str(payload["source_sha"]),
            plan_id=str(payload["plan_id"]),
            products=products,
            candidate_sha=str(payload["candidate_sha"]),
            artifacts=artifacts,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ReleasePlanError(f"invalid release plan {path}: {error}") from error
    _validate_plan(plan)
    return plan


def save_release_plan(plan: ReleasePlan, path: Path) -> None:
    """Write one release plan atomically enough for a CI artifact boundary."""
    path.write_text(plan.to_json(), encoding="utf-8", newline="\n")


def _release_closure(
    direct_versions: Mapping[str, StableVersion | None],
) -> set[str]:
    """Return direct releases and every transitive downstream consumer."""
    selected = {
        name for name, version in direct_versions.items() if version is not None
    }
    changed = True
    while changed:
        before = len(selected)
        for name, product in PRODUCTS.items():
            if any(dependency.name in selected for dependency in product.dependencies):
                selected.add(name)
        changed = len(selected) != before
    return selected


def _validate_planning_inputs(
    current_versions: Mapping[str, StableVersion],
    direct_versions: Mapping[str, StableVersion | None],
    current_requirements: Mapping[str, Mapping[str, str]],
) -> None:
    """Reject incomplete, foreign, or non-advancing semantic proposals."""
    product_names = set(PRODUCTS)
    if set(current_versions) != product_names:
        raise ReleasePlanError("current versions must cover exactly every product")
    if set(direct_versions) != product_names:
        raise ReleasePlanError("direct versions must cover exactly every product")
    unknown_consumers = set(current_requirements) - product_names
    if unknown_consumers:
        raise ReleasePlanError(
            f"requirements contain unknown products: {sorted(unknown_consumers)}"
        )
    for name, current in current_versions.items():
        _validate_stable_version(current, f"current {name} version")
        proposal = direct_versions[name]
        if proposal is None:
            continue
        _validate_stable_version(proposal, f"direct {name} version")
        if proposal <= current:
            raise ReleasePlanError(
                f"direct {name} version must advance {format_version(current)}"
            )
    for consumer, requirements in current_requirements.items():
        allowed = {dependency.name for dependency in PRODUCTS[consumer].dependencies}
        unknown_dependencies = set(requirements) - allowed
        if unknown_dependencies:
            raise ReleasePlanError(
                f"{consumer} requirements contain non-product edges: "
                f"{sorted(unknown_dependencies)}"
            )


def _validate_stable_version(version: StableVersion, label: str) -> None:
    """Require a nonnegative three-component stable version tuple."""
    if (
        not isinstance(version, tuple)
        or len(version) != 3
        or any(not isinstance(part, int) or part < 0 for part in version)
    ):
        raise ReleasePlanError(f"{label} must be a stable three-component version")


def _planned_dependency(
    *,
    dependency: Any,
    selected: set[str],
    planned_versions: Mapping[str, StableVersion | None],
    current_versions: Mapping[str, StableVersion],
    current_specifier: str,
) -> PlannedDependency:
    """Resolve one edge against its exact planned or published upstream."""
    upstream = _required_version(
        (
            planned_versions[dependency.name]
            if dependency.name in selected
            else current_versions[dependency.name]
        ),
        dependency.name,
    )
    if dependency.name not in selected and _canonical_requirement_accepts(
        dependency.name,
        current_specifier,
        upstream,
    ):
        specifier = current_specifier
    else:
        specifier = dependency.policy.specifier(upstream)
    return PlannedDependency(dependency.name, upstream, specifier)


def _canonical_requirement_accepts(
    name: str,
    specifier: str,
    version: StableVersion,
) -> bool:
    """Return whether an existing plain requirement safely admits ``version``."""
    if not specifier:
        return False
    try:
        requirement = Requirement(f"{name}{specifier}")
    except InvalidRequirement:
        return False
    return (
        canonicalize_name(requirement.name) == canonicalize_name(name)
        and not requirement.extras
        and requirement.marker is None
        and requirement.url is None
        and version_in_specifier(specifier, version)
    )


def _patch(version: StableVersion) -> StableVersion:
    """Return the next patch version."""
    return (version[0], version[1], version[2] + 1)


def version_in_specifier(specifier: str, version: StableVersion) -> bool:
    """Return whether a canonical stable version satisfies ``specifier``."""
    return Version(format_version(version)) in SpecifierSet(specifier)


def _required_version(
    version: StableVersion | None,
    product: str,
) -> StableVersion:
    """Narrow an optional version after planning invariants are established."""
    if version is None:
        raise ReleasePlanError(f"release plan omitted a version for {product}")
    return version


def _plan_payload(plan: ReleasePlan) -> dict[str, Any]:
    """Return the stable serialized plan payload."""
    return {
        "schema": _SCHEMA,
        "source_sha": plan.source_sha,
        "plan_id": plan.plan_id,
        "candidate_sha": plan.candidate_sha,
        "products": [_product_payload(product) for product in plan.products],
        "artifacts": [
            {
                "product": artifact.product,
                "filename": artifact.filename,
                "sha256": artifact.sha256,
            }
            for artifact in plan.artifacts
        ],
    }


def _product_payload(product: PlannedProduct) -> dict[str, Any]:
    """Return the stable serialized product payload."""
    return {
        "name": product.name,
        "current_version": format_version(product.current_version),
        "version": format_version(product.version),
        "direct": product.direct,
        "tag": product.tag,
        "commit_sha": product.commit_sha,
        "dependencies": [
            {
                "name": dependency.name,
                "version": format_version(dependency.version),
                "specifier": dependency.specifier,
                "requirement": dependency.requirement,
            }
            for dependency in product.dependencies
        ],
    }


def _load_product(value: object) -> PlannedProduct:
    """Parse one product object from serialized plan data."""
    if not isinstance(value, dict):
        raise ReleasePlanError("planned product must be an object")
    name = str(value["name"])
    product = PlannedProduct(
        name=name,
        current_version=_parse_version(value["current_version"]),
        version=_parse_version(value["version"]),
        direct=bool(value["direct"]),
        commit_sha=str(value["commit_sha"]),
        dependencies=tuple(_load_dependency(item) for item in value["dependencies"]),
    )
    if value.get("tag") != product.tag:
        raise ReleasePlanError(f"release tag drift for {name}")
    return product


def _load_dependency(value: object) -> PlannedDependency:
    """Parse one dependency object from serialized plan data."""
    if not isinstance(value, dict):
        raise ReleasePlanError("planned dependency must be an object")
    dependency = PlannedDependency(
        name=str(value["name"]),
        version=_parse_version(value["version"]),
        specifier=str(value["specifier"]),
    )
    if value.get("requirement") != dependency.requirement:
        raise ReleasePlanError(f"dependency requirement drift for {dependency.name}")
    return dependency


def _load_artifact(value: object) -> PlannedArtifact:
    """Parse one artifact object from serialized plan data."""
    if not isinstance(value, dict):
        raise ReleasePlanError("planned artifact must be an object")
    return PlannedArtifact(
        product=str(value["product"]),
        filename=str(value["filename"]),
        sha256=str(value["sha256"]),
    )


def _parse_version(value: object) -> StableVersion:
    """Parse a stable version from serialized plan data."""
    from .products import parse_stable_version

    return parse_stable_version(str(value))


def _validate_plan(plan: ReleasePlan) -> None:
    """Reject identity, ordering, SHA, and artifact inconsistencies."""
    _validate_sha(plan.source_sha, "source SHA")
    if plan.candidate_sha:
        _validate_sha(plan.candidate_sha, "candidate SHA")
    expected_names = [
        name for name in PRODUCTS if name in {p.name for p in plan.products}
    ]
    if [product.name for product in plan.products] != expected_names:
        raise ReleasePlanError(
            "release products are duplicated, unknown, or out of order"
        )
    identity_payload = {
        "schema": _SCHEMA,
        "source_sha": plan.source_sha,
        "products": [
            _product_payload(replace(product, commit_sha=""))
            for product in plan.products
        ],
    }
    expected_id = hashlib.sha256(_canonical_json(identity_payload)).hexdigest()[:24]
    if plan.plan_id != expected_id:
        raise ReleasePlanError("release plan identity does not match its contents")
    for product in plan.products:
        if product.commit_sha:
            _validate_sha(product.commit_sha, f"{product.name} commit SHA")
    if plan.artifacts and not plan.candidate_sha:
        raise ReleasePlanError("sealed artifacts require a candidate SHA")
    if len({(item.product, item.filename) for item in plan.artifacts}) != len(
        plan.artifacts
    ):
        raise ReleasePlanError("release plan contains duplicate artifacts")
    planned_names = {product.name for product in plan.products}
    for artifact in plan.artifacts:
        if artifact.product not in planned_names:
            raise ReleasePlanError(f"artifact belongs to unplanned {artifact.product}")
        if Path(artifact.filename).name != artifact.filename:
            raise ReleasePlanError("artifact filename must not contain a path")
        if len(artifact.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in artifact.sha256
        ):
            raise ReleasePlanError(f"invalid SHA-256 for {artifact.filename}")


def _validate_sha(value: str, label: str) -> None:
    """Require a full lowercase Git object ID."""
    if len(value) != 40 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ReleasePlanError(f"{label} must be a full lowercase Git SHA")


def _canonical_json(value: object) -> bytes:
    """Return canonical JSON bytes used for release-plan identity."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
