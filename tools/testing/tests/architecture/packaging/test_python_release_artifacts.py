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
"""Prove exact public metadata and ownership checks for Python artifacts."""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from tools.release.artifact_validation import validate_artifacts
from tools.release.artifacts import seal_release_plan, verify_release_artifacts
from tools.release.candidate import read_product_requirements
from tools.release.plan import ReleasePlanError, create_release_plan
from tools.release.products import PRODUCTS
from tools.testing.policy import repository_root

_REPOSITORY = "https://github.com/Artificial-Sweetener/CuteCanvas"
_ROOT = repository_root()


def test_release_artifacts_accept_exact_metadata_and_package_contents(
    tmp_path: Path,
) -> None:
    """Accept the canonical guide in matching CuteCanvas artifacts."""
    description = (_ROOT / "README.md").read_text(encoding="utf-8")
    _write_artifacts(tmp_path, description=description)
    assert validate_artifacts(PRODUCTS["cutecanvas"], "1.0.0", tmp_path) == ()


def test_release_artifacts_reject_relative_readme_links_and_wrong_dependencies(
    tmp_path: Path,
) -> None:
    """Reject relative README links and an incompatible QPane requirement."""
    _write_artifacts(
        tmp_path,
        description=f"[Repository]({_REPOSITORY}) [Docs](docs/index.md)",
        requirements=_requirements_with_replacement(
            "cutecanvas",
            dependency="qpane",
            replacement="qpane<0",
        ),
    )
    errors = validate_artifacts(PRODUCTS["cutecanvas"], "1.0.0", tmp_path)
    assert "package README contains a relative Markdown link" in errors
    assert (
        f"CuteCanvas must require exactly {_requirement('cutecanvas', 'qpane')}"
        in errors
    )


def test_release_artifacts_reject_incompatible_ferrastra_dependency(
    tmp_path: Path,
) -> None:
    """Reject a Ferrastra dependency outside the planned compatibility line."""
    _write_artifacts(
        tmp_path,
        description=f"[Repository]({_REPOSITORY})",
        requirements=_requirements_with_replacement(
            "cutecanvas",
            dependency="ferrastra",
            replacement="ferrastra<0",
        ),
    )
    errors = validate_artifacts(PRODUCTS["cutecanvas"], "1.0.0", tmp_path)
    assert (
        f"CuteCanvas must require exactly {_requirement('cutecanvas', 'ferrastra')}"
        in errors
    )


def test_qpane_artifacts_reject_incompatible_ferrastra_dependency(
    tmp_path: Path,
) -> None:
    """Reject a QPane wheel that cannot resolve against stable Ferrastra."""
    _write_artifacts(
        tmp_path,
        product="qpane",
        description=f"[Repository]({_REPOSITORY})",
        requirements=("ferrastra<0",),
    )
    errors = validate_artifacts(PRODUCTS["qpane"], "1.0.0", tmp_path)
    assert f"QPane must require exactly {_requirement('qpane', 'ferrastra')}" in errors


def test_release_artifacts_reject_sibling_package_contents(tmp_path: Path) -> None:
    """Prevent a CuteCanvas wheel from accidentally containing QPane source."""
    _write_artifacts(tmp_path, description=f"[Repository]({_REPOSITORY})")
    wheel = next(tmp_path.glob("cutecanvas-*.whl"))
    with zipfile.ZipFile(wheel, mode="a") as archive:
        archive.writestr("qpane/__init__.py", "")
    errors = validate_artifacts(PRODUCTS["cutecanvas"], "1.0.0", tmp_path)
    assert "wheel contains unexpected top-level paths: ['qpane']" in errors


def test_ferrastra_release_requires_exact_native_platform_artifacts(
    tmp_path: Path,
) -> None:
    """Accept one metadata-consistent wheel per supported native platform."""
    description = f"[Repository]({_REPOSITORY})"
    _write_ferrastra_artifacts(tmp_path, description=description)
    assert validate_artifacts(PRODUCTS["ferrastra"], "1.0.0", tmp_path) == ()


def test_ferrastra_release_rejects_incomplete_platform_coverage(
    tmp_path: Path,
) -> None:
    """Reject a native release when any supported platform wheel is absent."""
    _write_ferrastra_artifacts(tmp_path, description=f"[Repository]({_REPOSITORY})")
    next(tmp_path.glob("ferrastra-*-win_amd64.whl")).unlink()
    errors = validate_artifacts(PRODUCTS["ferrastra"], "1.0.0", tmp_path)
    assert "expected 3 ferrastra wheel(s), found 2" in errors
    assert "expected one ferrastra windows-x64 wheel, found 0" in errors


def test_sealed_plan_rejects_any_post_validation_artifact_change(
    tmp_path: Path,
) -> None:
    """Bind publication and recovery to the exact prevalidated bytes."""
    plan = create_release_plan(
        "a" * 40,
        {
            "ferrastra": (1, 0, 0),
            "qpane": (3, 0, 1),
            "cutecanvas": (1, 0, 2),
        },
        {"ferrastra": None, "qpane": (3, 0, 2), "cutecanvas": None},
        {
            "qpane": {"ferrastra": ">=1.0.0,<2.0.0"},
            "cutecanvas": {
                "ferrastra": ">=1.0.0,<2.0.0",
                "qpane": ">=3.0.0,<4.0.0",
            },
        },
    ).with_candidate(
        "d" * 40,
        {"qpane": "b" * 40, "cutecanvas": "c" * 40},
    )
    qpane = tmp_path / "qpane"
    canvas = tmp_path / "cutecanvas"
    qpane.mkdir()
    canvas.mkdir()
    _write_artifacts(
        qpane,
        product="qpane",
        version="3.0.2",
        description=f"[Repository]({_REPOSITORY})",
        requirements=("ferrastra>=1.0.0,<2.0.0",),
    )
    _write_artifacts(
        canvas,
        version="1.0.3",
        description=f"[Repository]({_REPOSITORY})",
        requirements=(
            "ferrastra>=1.0.0,<2.0.0",
            "qpane>=3.0.2,<4.0.0",
        ),
    )
    sealed = seal_release_plan(plan, tmp_path)
    verify_release_artifacts(sealed, tmp_path)

    wheel = next(canvas.glob("cutecanvas-*.whl"))
    with wheel.open("ab") as output:
        output.write(b"tampered")
    with pytest.raises(ReleasePlanError, match="hash"):
        verify_release_artifacts(sealed, tmp_path)


def _write_artifacts(
    directory: Path,
    *,
    description: str,
    product: str = "cutecanvas",
    version: str = "1.0.0",
    requirements: tuple[str, ...] | None = None,
) -> None:
    """Write one minimal synthetic Python product distribution."""
    if requirements is None:
        requirements = _requirements(product)
    serialized_requirements = "".join(
        f"Requires-Dist: {requirement}\n" for requirement in requirements
    )
    metadata = (
        "Metadata-Version: 2.4\n"
        f"Name: {product}\n"
        f"Version: {version}\n"
        "Description-Content-Type: text/markdown\n"
        f"Project-URL: Repository, {_REPOSITORY}\n"
        f"{serialized_requirements}"
        "\n"
        f"{description}\n"
    ).encode()
    wheel = directory / f"{product}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr(f"{product}/__init__.py", "")
        archive.writestr(f"{product}-{version}.dist-info/METADATA", metadata)
    source = directory / f"{product}-{version}.tar.gz"
    with tarfile.open(source, mode="w:gz") as archive:
        info = tarfile.TarInfo(f"{product}-{version}/PKG-INFO")
        info.size = len(metadata)
        archive.addfile(info, io.BytesIO(metadata))
        duplicate = tarfile.TarInfo(
            f"{product}-{version}/src/{product}.egg-info/PKG-INFO"
        )
        duplicate.size = len(metadata)
        archive.addfile(duplicate, io.BytesIO(metadata))


def _requirements(product: str) -> tuple[str, ...]:
    """Return ordered cross-product requirements from the current manifest."""
    definition = PRODUCTS[product]
    specifiers = read_product_requirements(
        _ROOT / definition.package_path / "pyproject.toml"
    )
    return tuple(
        f"{dependency.name}{specifiers[dependency.name]}"
        for dependency in definition.dependencies
    )


def _requirement(product: str, dependency: str) -> str:
    """Return one current cross-product requirement by dependency name."""
    matching = tuple(
        requirement
        for requirement in _requirements(product)
        if requirement.startswith(dependency)
    )
    if len(matching) != 1:
        raise AssertionError(f"{product} must declare {dependency} exactly once")
    return matching[0]


def _requirements_with_replacement(
    product: str,
    *,
    dependency: str,
    replacement: str,
) -> tuple[str, ...]:
    """Replace one current dependency with a deliberately invalid requirement."""
    expected = _requirement(product, dependency)
    return tuple(
        replacement if requirement == expected else requirement
        for requirement in _requirements(product)
    )


def _write_ferrastra_artifacts(directory: Path, *, description: str) -> None:
    """Write a complete synthetic Ferrastra native distribution set."""
    metadata = (
        "Metadata-Version: 2.4\n"
        "Name: ferrastra\n"
        "Version: 1.0.0\n"
        "Description-Content-Type: text/markdown\n"
        f"Project-URL: Repository, {_REPOSITORY}\n"
        "\n"
        f"{description}\n"
    ).encode()
    wheels = (
        "ferrastra-1.0.0-cp310-abi3-manylinux_2_35_x86_64.whl",
        "ferrastra-1.0.0-cp310-abi3-win_amd64.whl",
        "ferrastra-1.0.0-cp310-abi3-macosx_11_0_arm64.whl",
    )
    for name in wheels:
        with zipfile.ZipFile(directory / name, mode="w") as archive:
            archive.writestr("ferrastra/__init__.py", "")
            archive.writestr("ferrastra-1.0.0.dist-info/METADATA", metadata)
    source = directory / "ferrastra-1.0.0.tar.gz"
    with tarfile.open(source, mode="w:gz") as archive:
        info = tarfile.TarInfo("ferrastra-1.0.0/PKG-INFO")
        info.size = len(metadata)
        archive.addfile(info, io.BytesIO(metadata))
