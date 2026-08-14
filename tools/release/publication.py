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
"""Admit idempotent topological publication from one sealed release plan."""

from __future__ import annotations

from pathlib import Path

from .artifacts import verify_release_artifacts
from .plan import ReleasePlan, ReleasePlanError
from .products import format_version
from .pypi import (
    JsonLoader,
    PublicationState,
    load_pypi_json,
    planned_publication_state,
)


def admit_publication(
    plan: ReleasePlan,
    product_name: str,
    distribution_root: Path,
    commit_sha: str,
    *,
    loader: JsonLoader = load_pypi_json,
) -> PublicationState:
    """Validate source, bytes, order, and recoverable PyPI state for one product."""
    product = plan.product(product_name)
    if product.commit_sha != commit_sha:
        raise ReleasePlanError(
            f"{product_name} tag resolves to {commit_sha}, expected {product.commit_sha}"
        )
    verify_release_artifacts(plan, distribution_root, product_name)
    planned_names = {item.name for item in plan.products}
    for dependency in product.dependencies:
        if dependency.name not in planned_names:
            _require_existing_dependency(dependency.name, dependency.version, loader)
            continue
        upstream = plan.product(dependency.name)
        state = planned_publication_state(
            upstream.name,
            format_version(upstream.version),
            _artifact_hashes(plan, upstream.name),
            loader=loader,
        )
        if state is not PublicationState.COMPLETE:
            raise ReleasePlanError(
                f"{product_name} cannot publish before planned upstream "
                f"{upstream.name} is complete"
            )
    return planned_publication_state(
        product.name,
        format_version(product.version),
        _artifact_hashes(plan, product.name),
        loader=loader,
    )


def _require_existing_dependency(
    name: str,
    version: tuple[int, int, int],
    loader: JsonLoader,
) -> None:
    """Require one unplanned exact upstream version on the public index."""
    version_text = format_version(version)
    payload = loader(f"https://pypi.org/pypi/{name}/{version_text}/json")
    if not payload.get("urls"):
        raise ReleasePlanError(
            f"required upstream {name}=={version_text} is not published"
        )


def _artifact_hashes(plan: ReleasePlan, product: str) -> dict[str, str]:
    """Return exact sealed artifact hashes for one planned product."""
    values = {
        artifact.filename: artifact.sha256
        for artifact in plan.artifacts
        if artifact.product == product
    }
    if not values:
        raise ReleasePlanError(f"sealed plan has no artifacts for {product}")
    return values
