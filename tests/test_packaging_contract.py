# QPane - High-performance Qt image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Verify that distributions advertise and ship QPane's public typing contract."""

from __future__ import annotations

import ast
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_typing_marker_is_declared_as_package_data() -> None:
    """Require built distributions to include the PEP 561 typing marker."""

    pyproject = tomllib.loads((_PROJECT_ROOT / "pyproject.toml").read_text("utf-8"))

    assert pyproject["tool"]["setuptools"]["package-data"]["qpane"] == [
        "*.pyi",
        "py.typed",
    ]


def test_typing_marker_exists_beside_public_stubs() -> None:
    """Keep the marker and public stub together in the importable package."""

    package_root = _PROJECT_ROOT / "qpane"

    assert (package_root / "py.typed").is_file()
    assert (package_root / "qpane.pyi").is_file()


def test_examples_are_not_installed_as_package_modules() -> None:
    """Keep repository tutorials out of the importable wheel package."""

    pyproject = tomllib.loads((_PROJECT_ROOT / "pyproject.toml").read_text("utf-8"))
    include_patterns = pyproject["tool"]["setuptools"]["packages"]["find"]["include"]

    assert include_patterns == ["qpane", "qpane.*"]


def test_runtime_dependencies_include_typing_extensions() -> None:
    """Declare the compatibility types imported by production modules."""

    pyproject = tomllib.loads((_PROJECT_ROOT / "pyproject.toml").read_text("utf-8"))

    assert "typing-extensions>=4.0" in pyproject["project"]["dependencies"]


def test_runtime_source_and_dependencies_do_not_require_opencv() -> None:
    """Keep mask processing on the existing Qt and NumPy runtime stack."""
    pyproject = tomllib.loads((_PROJECT_ROOT / "pyproject.toml").read_text("utf-8"))
    dependency_groups = [
        pyproject["project"]["dependencies"],
        *pyproject["project"]["optional-dependencies"].values(),
    ]
    declared = {
        dependency.lower() for group in dependency_groups for dependency in group
    }
    imported_roots: set[str] = set()
    for path in (_PROJECT_ROOT / "qpane").rglob("*.py"):
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(
                    alias.name.split(".", 1)[0] for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])

    assert all("opencv" not in dependency for dependency in declared)
    assert "cv2" not in imported_roots
