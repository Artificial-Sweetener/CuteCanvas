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

from tools.release.artifact_validation import validate_artifacts
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
    """Reject metadata that would render incorrectly or install against QPane 2."""
    _write_artifacts(
        tmp_path,
        description=f"[Repository]({_REPOSITORY}) [Docs](docs/index.md)",
        requirement="qpane>=2.0.0,<3.0.0",
    )
    errors = validate_artifacts(PRODUCTS["cutecanvas"], "1.0.0", tmp_path)
    assert "package README contains a relative Markdown link" in errors
    assert "CuteCanvas must require exactly qpane>=3.0.0,<4.0.0" in errors


def test_release_artifacts_reject_sibling_package_contents(tmp_path: Path) -> None:
    """Prevent a CuteCanvas wheel from accidentally containing QPane source."""
    _write_artifacts(tmp_path, description=f"[Repository]({_REPOSITORY})")
    wheel = next(tmp_path.glob("cutecanvas-*.whl"))
    with zipfile.ZipFile(wheel, mode="a") as archive:
        archive.writestr("qpane/__init__.py", "")
    errors = validate_artifacts(PRODUCTS["cutecanvas"], "1.0.0", tmp_path)
    assert "wheel contains unexpected top-level paths: ['qpane']" in errors


def _write_artifacts(
    directory: Path,
    *,
    description: str,
    requirement: str = "qpane>=3.0.0,<4.0.0",
) -> None:
    """Write a minimal synthetic CuteCanvas wheel and source distribution."""
    metadata = (
        "Metadata-Version: 2.4\n"
        "Name: cutecanvas\n"
        "Version: 1.0.0\n"
        "Description-Content-Type: text/markdown\n"
        f"Project-URL: Repository, {_REPOSITORY}\n"
        f"Requires-Dist: {requirement}\n"
        "\n"
        f"{description}\n"
    ).encode()
    wheel = directory / "cutecanvas-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr("cutecanvas/__init__.py", "")
        archive.writestr("cutecanvas-1.0.0.dist-info/METADATA", metadata)
    source = directory / "cutecanvas-1.0.0.tar.gz"
    with tarfile.open(source, mode="w:gz") as archive:
        info = tarfile.TarInfo("cutecanvas-1.0.0/PKG-INFO")
        info.size = len(metadata)
        archive.addfile(info, io.BytesIO(metadata))
        duplicate = tarfile.TarInfo("cutecanvas-1.0.0/src/cutecanvas.egg-info/PKG-INFO")
        duplicate.size = len(metadata)
        archive.addfile(duplicate, io.BytesIO(metadata))
