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
"""Own release-candidate materialization before irreversible publication."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from .plan import (
    PlannedDependency,
    ReleasePlan,
    ReleasePlanError,
    create_release_plan,
    save_release_plan,
)
from .products import PRODUCTS, StableVersion, format_version, parse_stable_version

_REQUIREMENT_LINE = re.compile(r'^(?P<indent>\s*)"(?P<value>[^"]+)",(?P<suffix>\s*)$')


def prepare_candidate(root: Path, source_sha: str, output: Path) -> ReleasePlan:
    """Plan and materialize local release commits without pushing final tags."""
    _require_git_state(root, source_sha)
    current_versions = {name: _current_version(root, name) for name in PRODUCTS}
    direct_versions = {
        name: _direct_version(root, name, current_versions[name]) for name in PRODUCTS
    }
    current_requirements = {
        name: read_product_requirements(root / product.package_path / "pyproject.toml")
        for name, product in PRODUCTS.items()
    }
    plan = create_release_plan(
        source_sha,
        current_versions,
        direct_versions,
        current_requirements,
    )
    if not plan.products:
        save_release_plan(plan, output)
        return plan

    commits: dict[str, str] = {}
    for planned in plan.products:
        definition = PRODUCTS[planned.name]
        manifest = root / definition.package_path / "pyproject.toml"
        synchronize_requirements(manifest, planned.dependencies)
        arguments = [
            sys.executable,
            "-m",
            "semantic_release",
            "--config",
            str(manifest.relative_to(root)),
            "version",
            "--no-tag",
            "--no-push",
            "--no-vcs-release",
            "--skip-build",
        ]
        if not planned.direct:
            arguments.append("--patch")
        run_release_command(arguments, cwd=root)
        commit_sha = _git(root, "rev-parse", "HEAD")
        run_release_command(["git", "tag", planned.tag, commit_sha], cwd=root)
        actual_version = _semantic_version(
            root,
            manifest.relative_to(root),
            "--print-last-released",
        )
        if actual_version != planned.version:
            raise ReleasePlanError(
                f"{planned.name} materialized {format_version(actual_version)}, "
                f"expected {format_version(planned.version)}"
            )
        commits[planned.name] = commit_sha

    candidate_sha = _git(root, "rev-parse", "HEAD")
    if _git(root, "status", "--porcelain"):
        raise ReleasePlanError("release candidate left uncommitted files")
    materialized = plan.with_candidate(candidate_sha, commits)
    save_release_plan(materialized, output)
    return materialized


def read_product_requirements(manifest: Path) -> dict[str, str]:
    """Return canonical cross-product specifiers from one project manifest."""
    requirements: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = _REQUIREMENT_LINE.fullmatch(line)
        if match is None:
            continue
        try:
            requirement = Requirement(match.group("value"))
        except InvalidRequirement:
            continue
        name = canonicalize_name(requirement.name)
        if name not in PRODUCTS:
            continue
        if name in requirements:
            raise ReleasePlanError(f"{manifest} declares {name} more than once")
        if requirement.extras or requirement.marker is not None or requirement.url:
            raise ReleasePlanError(
                f"{manifest} must declare {name} as one plain version range"
            )
        requirements[name] = match.group("value")[len(requirement.name) :]
    return requirements


def synchronize_requirements(
    manifest: Path,
    dependencies: Sequence[PlannedDependency],
) -> None:
    """Replace each planned dependency exactly once while preserving TOML layout."""
    lines = manifest.read_text(encoding="utf-8").splitlines()
    remaining = {canonicalize_name(item.name): item for item in dependencies}
    counts = {name: 0 for name in remaining}
    updated: list[str] = []
    for line in lines:
        match = _REQUIREMENT_LINE.fullmatch(line)
        if match is None:
            updated.append(line)
            continue
        requirement = _requirement_or_none(match.group("value"))
        if requirement is None:
            updated.append(line)
            continue
        name = canonicalize_name(requirement.name)
        dependency = remaining.get(name)
        if dependency is None:
            updated.append(line)
            continue
        if requirement.extras or requirement.marker is not None or requirement.url:
            raise ReleasePlanError(
                f"{manifest} must declare {name} as one plain version range"
            )
        counts[name] += 1
        updated.append(
            f'{match.group("indent")}"{dependency.requirement}",'
            f'{match.group("suffix")}'
        )
    invalid = [name for name, count in counts.items() if count != 1]
    if invalid:
        raise ReleasePlanError(
            f"{manifest} must declare each planned dependency exactly once: {invalid}"
        )
    manifest.write_text("\n".join(updated) + "\n", encoding="utf-8", newline="\n")
    actual = read_product_requirements(manifest)
    for dependency in dependencies:
        if actual.get(dependency.name) != dependency.specifier:
            raise ReleasePlanError(
                f"{manifest} did not materialize {dependency.requirement}"
            )


def finalize_candidate(root: Path, plan: ReleasePlan, remote: str = "origin") -> None:
    """Atomically fast-forward main and create the plan's final product tags."""
    if not plan.candidate_sha or not plan.products:
        raise ReleasePlanError("only a materialized nonempty plan can be finalized")
    remote_main = _git(root, "ls-remote", remote, "refs/heads/main").split()[0]
    if remote_main != plan.source_sha:
        raise ReleasePlanError(
            f"remote main moved from {plan.source_sha} to {remote_main}; refusing stale plan"
        )
    for product in plan.products:
        actual_commit = _git(root, "rev-parse", product.commit_sha)
        if actual_commit != product.commit_sha:
            raise ReleasePlanError(f"missing candidate commit for {product.name}")
        run_release_command(["git", "tag", product.tag, product.commit_sha], cwd=root)
    refspecs = [f"{plan.candidate_sha}:refs/heads/main"]
    refspecs.extend(f"refs/tags/{product.tag}" for product in plan.products)
    run_release_command(["git", "push", "--atomic", remote, *refspecs], cwd=root)


def write_github_outputs(plan: ReleasePlan, path: Path) -> None:
    """Expose compact candidate facts to GitHub Actions jobs."""
    versions = {
        product.name: format_version(product.version) for product in plan.products
    }
    values = {
        "released": str(bool(plan.products)).lower(),
        "plan_id": plan.plan_id,
        "candidate_sha": plan.candidate_sha,
        "python_matrix": _json_list(
            product.name for product in plan.products if product.name != "ferrastra"
        ),
        "ferrastra_released": str("ferrastra" in versions).lower(),
        "ferrastra_version": versions.get("ferrastra", ""),
        "qpane_version": versions.get("qpane", ""),
        "cutecanvas_version": versions.get("cutecanvas", ""),
    }
    with path.open("a", encoding="utf-8", newline="\n") as output:
        for name, value in values.items():
            output.write(f"{name}={value}\n")


def _current_version(root: Path, name: str) -> StableVersion:
    """Return the latest product-prefixed stable tag version."""
    tag = _git(
        root,
        "tag",
        "--list",
        f"{PRODUCTS[name].tag_prefix}*",
        "--sort=-version:refname",
    ).splitlines()
    if not tag:
        raise ReleasePlanError(f"{name} has no established release tag")
    return parse_stable_version(tag[0].removeprefix(PRODUCTS[name].tag_prefix))


def _direct_version(
    root: Path,
    name: str,
    current: StableVersion,
) -> StableVersion | None:
    """Return the semantic-release proposal when it advances ``current``."""
    candidate = _semantic_version(
        root,
        PRODUCTS[name].package_path / "pyproject.toml",
        "--print",
    )
    return candidate if candidate != current else None


def _semantic_version(root: Path, configuration: Path, flag: str) -> StableVersion:
    """Read one exact version from Python Semantic Release."""
    output = run_release_command(
        [
            sys.executable,
            "-m",
            "semantic_release",
            "--config",
            str(configuration),
            "version",
            flag,
        ],
        cwd=root,
    )
    lines = output.splitlines()
    if not lines:
        raise ReleasePlanError(
            f"semantic-release produced no version for {configuration}"
        )
    return parse_stable_version(lines[-1].strip())


def _require_git_state(root: Path, source_sha: str) -> None:
    """Require the exact clean verified source before candidate mutation."""
    if _git(root, "rev-parse", "HEAD") != source_sha:
        raise ReleasePlanError(
            "checked-out HEAD does not match the requested source SHA"
        )
    if _git(root, "status", "--porcelain"):
        raise ReleasePlanError("release planning requires a clean worktree")


def _requirement_or_none(value: str) -> Requirement | None:
    """Parse one requirement or return ``None`` for unrelated invalid text."""
    try:
        return Requirement(value)
    except InvalidRequirement:
        return None


def _git(root: Path, *arguments: str) -> str:
    """Run Git and return stripped standard output."""
    return run_release_command(["git", *arguments], cwd=root).strip()


def run_release_command(arguments: Sequence[str], *, cwd: Path) -> str:
    """Run one required candidate command without invoking a shell."""
    command_environment = os.environ.copy()
    command_environment.pop("GITHUB_OUTPUT", None)
    try:
        completed = subprocess.run(
            list(arguments),
            cwd=cwd,
            env=command_environment,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        diagnostic = (error.stderr or error.stdout or "no command output").strip()
        command = " ".join(arguments)
        raise ReleasePlanError(
            f"release command failed with exit code {error.returncode}: "
            f"{command}\n{diagnostic}"
        ) from error
    return completed.stdout


def _json_list(values: Iterable[str]) -> str:
    """Serialize a compact JSON list for a GitHub Actions matrix."""
    return json.dumps(list(values), separators=(",", ":"))
