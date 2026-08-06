#    CuteCanvas - High-performance layered image editor
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
"""Verify CuteCanvas's independently published distribution contract."""

from __future__ import annotations

import ast
import importlib
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from cutecanvas_test_support.repository import package_root


def _metadata() -> dict[str, Any]:
    """Load CuteCanvas's authoritative build metadata."""
    return tomllib.loads((package_root() / "pyproject.toml").read_text("utf-8"))


def test_cutecanvas_typing_contract_is_packaged_beside_the_facade() -> None:
    """Ship CuteCanvas's PEP 561 marker and authoritative root stub."""
    metadata = _metadata()
    assert metadata["tool"]["setuptools"]["package-data"]["cutecanvas"] == [
        "*.pyi",
        "py.typed",
    ]
    source = package_root() / "src/cutecanvas"
    assert (source / "py.typed").is_file()
    assert (source / "cutecanvas.pyi").is_file()


def test_cutecanvas_reports_its_distribution_version() -> None:
    """Keep the editor version independent from QPane's release version."""
    facade = importlib.import_module("cutecanvas")
    version_module = importlib.import_module("cutecanvas._version")
    assert facade.__version__ == version_module.version


def test_cutecanvas_wheel_discovers_only_cutecanvas_packages() -> None:
    """Keep examples and sibling products out of the CuteCanvas wheel."""
    patterns = _metadata()["tool"]["setuptools"]["packages"]["find"]["include"]
    assert patterns == ["cutecanvas", "cutecanvas.*"]


def test_cutecanvas_declares_a_bounded_qpane_dependency() -> None:
    """State the compatible QPane release series explicitly."""
    dependencies = _metadata()["project"]["dependencies"]
    assert "qpane>=0.1.0,<0.2.0" in dependencies


def test_cutecanvas_versions_use_the_cutecanvas_release_tag_namespace() -> None:
    """Version CuteCanvas only from product-prefixed release tags."""
    metadata = _metadata()
    assert metadata["tool"]["setuptools_scm"]["tag"]["regex"] == (
        "^cutecanvas-v(?P<version>.+)$"
    )
    scm = metadata["tool"]["setuptools_scm"]
    assert "--match cutecanvas-v" in scm["scm"]["git"]["describe_command"]
    assert "write_to" not in scm


def test_cutecanvas_declares_every_imported_runtime_distribution() -> None:
    """Keep isolated installs independent of incidental transitive packages."""
    dependencies = {
        str(item).split(">", 1)[0].lower()
        for item in _metadata()["project"]["dependencies"]
    }
    assert {"qpane", "pyside6", "numpy", "typing-extensions"} <= dependencies


def test_cutecanvas_runtime_does_not_require_opencv() -> None:
    """Keep CuteCanvas on the Qt and NumPy image-processing stack."""
    metadata = _metadata()
    project = metadata["project"]
    dependency_groups = [
        project["dependencies"],
        *project.get("optional-dependencies", {}).values(),
    ]
    dependencies = {str(item).lower() for group in dependency_groups for item in group}
    imported_roots: set[str] = set()
    for path in (package_root() / "src/cutecanvas").rglob("*.py"):
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(
                    alias.name.split(".", 1)[0] for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
    assert all("opencv" not in dependency for dependency in dependencies)
    assert "cv2" not in imported_roots
