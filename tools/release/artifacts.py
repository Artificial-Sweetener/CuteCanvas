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
"""Seal and verify release artifacts against one immutable release plan."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .artifact_validation import validate_artifacts
from .plan import PlannedArtifact, ReleasePlan, ReleasePlanError
from .products import PRODUCTS, format_version


def seal_release_plan(plan: ReleasePlan, distribution_root: Path) -> ReleasePlan:
    """Validate every planned distribution and attach its exact file hashes."""
    if not plan.candidate_sha:
        raise ReleasePlanError("artifacts cannot be sealed before candidate commits")
    if plan.artifacts:
        raise ReleasePlanError("release plan is already sealed")
    artifacts: list[PlannedArtifact] = []
    for planned in plan.products:
        distribution = distribution_root / planned.name
        requirements = tuple(item.requirement for item in planned.dependencies)
        errors = validate_artifacts(
            PRODUCTS[planned.name],
            format_version(planned.version),
            distribution,
            requirements,
        )
        if errors:
            detail = "\n".join(f"- {error}" for error in errors)
            raise ReleasePlanError(
                f"{planned.name} artifact validation failed:\n{detail}"
            )
        files = tuple(
            sorted(
                (
                    *distribution.glob(f"{planned.name}-*.whl"),
                    *distribution.glob(f"{planned.name}-*.tar.gz"),
                ),
                key=lambda path: path.name,
            )
        )
        artifacts.extend(
            PlannedArtifact(planned.name, path.name, _sha256(path)) for path in files
        )
    return plan.with_artifacts(tuple(artifacts))


def verify_release_artifacts(
    plan: ReleasePlan,
    distribution_root: Path,
    product_name: str | None = None,
) -> None:
    """Require downloaded files and metadata to match a sealed plan exactly."""
    if not plan.sealed:
        raise ReleasePlanError("publication requires a sealed release plan")
    selected = plan.products if product_name is None else (plan.product(product_name),)
    for product in selected:
        distribution = distribution_root / product.name
        expected = {
            item.filename: item.sha256
            for item in plan.artifacts
            if item.product == product.name
        }
        actual_paths = tuple(
            sorted(
                (
                    *distribution.glob(f"{product.name}-*.whl"),
                    *distribution.glob(f"{product.name}-*.tar.gz"),
                ),
                key=lambda path: path.name,
            )
        )
        if {path.name for path in actual_paths} != set(expected):
            raise ReleasePlanError(
                f"{product.name} artifact filenames do not match sealed plan"
            )
        for path in actual_paths:
            digest = _sha256(path)
            if digest != expected[path.name]:
                raise ReleasePlanError(
                    f"{path.name} hash {digest} does not match sealed plan"
                )
        errors = validate_artifacts(
            PRODUCTS[product.name],
            format_version(product.version),
            distribution,
            tuple(item.requirement for item in product.dependencies),
        )
        if errors:
            raise ReleasePlanError(
                f"{product.name} metadata drifted after sealing: {'; '.join(errors)}"
            )


def _sha256(path: Path) -> str:
    """Return the lowercase SHA-256 digest of one distribution file."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
