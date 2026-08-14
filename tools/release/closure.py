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
"""Prove complete release dependency closure in one offline pip transaction."""

from __future__ import annotations

import shutil
import subprocess
import sys
import venv
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from .artifact_validation import read_wheel_metadata
from .artifacts import verify_release_artifacts
from .plan import ReleasePlan, ReleasePlanError
from .products import PRODUCTS, format_version


def verify_offline_closure(
    plan: ReleasePlan,
    distribution_root: Path,
    workspace: Path,
) -> None:
    """Resolve and install the sealed stack offline in one clean environment."""
    verify_release_artifacts(plan, distribution_root)
    if workspace.exists():
        raise ReleasePlanError(f"closure workspace already exists: {workspace}")
    wheelhouse = workspace / "wheelhouse"
    wheelhouse.mkdir(parents=True)
    for product in plan.products:
        for wheel in (distribution_root / product.name).glob(f"{product.name}-*.whl"):
            shutil.copy2(wheel, wheelhouse / wheel.name)

    planned_names = {product.name for product in plan.products}
    index_requirements = list(_third_party_requirements(plan, distribution_root))
    for product in plan.products:
        for dependency in product.dependencies:
            if dependency.name not in planned_names:
                index_requirements.append(
                    f"{dependency.name}=={format_version(dependency.version)}"
                )
    if index_requirements:
        _run(
            sys.executable,
            "-m",
            "pip",
            "download",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--dest",
            str(wheelhouse),
            *sorted(set(index_requirements)),
        )

    environment = workspace / "consumer"
    venv.EnvBuilder(with_pip=True).create(environment)
    interpreter = _environment_python(environment)
    requested = plan.products[-1]
    _run(
        str(interpreter),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-index",
        "--find-links",
        str(wheelhouse),
        f"{requested.name}=={format_version(requested.version)}",
    )
    _run(
        str(interpreter),
        "-c",
        _import_assertion(plan, environment),
    )


def _third_party_requirements(
    plan: ReleasePlan,
    distribution_root: Path,
) -> tuple[str, ...]:
    """Return external requirements declared by the planned product wheels."""
    product_names = {canonicalize_name(name) for name in PRODUCTS}
    requirements: set[str] = set()
    for product in plan.products:
        wheels = tuple((distribution_root / product.name).glob(f"{product.name}-*.whl"))
        if not wheels:
            raise ReleasePlanError(f"{product.name} has no wheel for closure proof")
        metadata = read_wheel_metadata(wheels[0])
        for value in metadata.requirements:
            requirement = Requirement(value)
            if canonicalize_name(requirement.name) not in product_names:
                requirements.add(str(requirement))
    return tuple(sorted(requirements))


def _import_assertion(plan: ReleasePlan, environment: Path) -> str:
    """Return an isolated import assertion for every product in the stack."""
    packages = {product.name for product in plan.products}
    packages.update(
        dependency.name
        for product in plan.products
        for dependency in product.dependencies
    )
    return "\n".join(
        (
            "from pathlib import Path",
            "import importlib",
            f"root = Path({str(environment)!r}).resolve()",
            f"names = {sorted(packages)!r}",
            "for name in names:",
            "    module = importlib.import_module(name)",
            "    assert Path(module.__file__).resolve().is_relative_to(root)",
        )
    )


def _environment_python(environment: Path) -> Path:
    """Return the interpreter inside a platform-native virtual environment."""
    if sys.platform == "win32":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def _run(*arguments: str) -> None:
    """Run one required resolver operation without invoking a shell."""
    subprocess.run(arguments, check=True)
