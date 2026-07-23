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
"""Verify independent QPane and CuteCanvas distribution contracts."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PACKAGES = {
    "qpane": _PROJECT_ROOT / "packages/qpane",
    "cutecanvas": _PROJECT_ROOT / "packages/cutecanvas",
}


def _metadata(package: str) -> dict[str, object]:
    """Load one package's independent build metadata."""
    return tomllib.loads((_PACKAGES[package] / "pyproject.toml").read_text("utf-8"))


def test_typing_contracts_are_packaged_beside_each_facade() -> None:
    """Ship a PEP 561 marker and stub from each independent wheel root."""
    for package, root in _PACKAGES.items():
        metadata = _metadata(package)
        assert metadata["tool"]["setuptools"]["package-data"][package] == [
            "*.pyi",
            "py.typed",
        ]
        source = root / "src" / package
        assert (source / "py.typed").is_file()
        assert (source / f"{package}.pyi").is_file()


def test_each_package_reports_its_own_distribution_version() -> None:
    """CuteCanvas must not inherit QPane's independently released version."""
    for package in _PACKAGES:
        facade = importlib.import_module(package)
        version_module = importlib.import_module(f"{package}._version")
        assert facade.__version__ == version_module.version


def test_each_wheel_discovers_only_its_own_package() -> None:
    """Keep examples and the sibling product out of each distribution."""
    for package in _PACKAGES:
        metadata = _metadata(package)
        patterns = metadata["tool"]["setuptools"]["packages"]["find"]["include"]
        assert patterns == [package, f"{package}.*"]


def test_cutecanvas_depends_on_qpane_in_one_direction() -> None:
    """Declare the editor-to-renderer dependency without a reverse edge."""
    qpane_dependencies = _metadata("qpane")["project"]["dependencies"]
    canvas_dependencies = _metadata("cutecanvas")["project"]["dependencies"]
    assert not any(
        str(item).lower().startswith("cutecanvas") for item in qpane_dependencies
    )
    assert any(str(item).lower().startswith("qpane>=") for item in canvas_dependencies)


def test_package_versions_use_independent_release_tag_namespaces() -> None:
    """A product tag must version only the distribution it publishes."""
    assert _metadata("qpane")["tool"]["setuptools_scm"]["tag"]["regex"] == (
        "^qpane-v(?P<version>.+)$"
    )
    assert _metadata("cutecanvas")["tool"]["setuptools_scm"]["tag"]["regex"] == (
        "^cutecanvas-v(?P<version>.+)$"
    )
    for package in _PACKAGES:
        command = _metadata(package)["tool"]["setuptools_scm"]["scm"]["git"][
            "describe_command"
        ]
        assert f"--match {package}-v" in command
        assert "write_to" not in _metadata(package)["tool"]["setuptools_scm"]


def test_cutecanvas_declares_a_bounded_qpane_compatibility_range() -> None:
    """Independent editor releases must state the renderer series they support."""
    dependencies = _metadata("cutecanvas")["project"]["dependencies"]
    assert "qpane>=0.1.0,<0.2.0" in dependencies


def test_each_distribution_declares_the_runtime_packages_it_imports() -> None:
    """Keep isolated installs independent of incidental transitive dependencies."""
    qpane_dependencies = {
        str(item).split(">", 1)[0].lower()
        for item in _metadata("qpane")["project"]["dependencies"]
    }
    canvas_dependencies = {
        str(item).split(">", 1)[0].lower()
        for item in _metadata("cutecanvas")["project"]["dependencies"]
    }

    assert {"pyside6", "numpy", "psutil", "typing-extensions"} <= qpane_dependencies
    assert {"qpane", "pyside6", "numpy", "typing-extensions"} <= canvas_dependencies


def test_repository_bootstrap_installs_both_editable_packages() -> None:
    """Keep the root setup path aligned with the two package roots."""
    development_requirements = (
        (_PROJECT_ROOT / "requirements-dev.txt").read_text("utf-8").splitlines()
    )
    root_requirements = (
        (_PROJECT_ROOT / "requirements.txt").read_text("utf-8").splitlines()
    )
    setup_source = (_PROJECT_ROOT / "tools/setup_dev.py").read_text("utf-8")

    assert "-e ./packages/qpane" in development_requirements
    assert "-e ./packages/cutecanvas" in development_requirements
    assert "-r requirements-dev.txt" in root_requirements
    assert 'repo_root / "requirements-dev.txt"' in setup_source


def test_runtime_source_and_dependencies_do_not_require_opencv() -> None:
    """Keep both products on the Qt and NumPy image-processing stack."""
    declared: set[str] = set()
    imported_roots: set[str] = set()
    for package, root in _PACKAGES.items():
        metadata = _metadata(package)
        project = metadata["project"]
        groups = [
            project["dependencies"],
            *project.get("optional-dependencies", {}).values(),
        ]
        declared.update(str(item).lower() for group in groups for item in group)
        for path in (root / "src" / package).rglob("*.py"):
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
