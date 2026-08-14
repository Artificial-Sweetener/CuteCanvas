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
"""Prove each product owns an independent semantic-release configuration."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

import pytest

from tools.testing.policy import repository_root

_ROOT = repository_root()


def _semantic_release_configuration(product: str) -> dict[str, Any]:
    """Load one product's semantic-release configuration."""
    package_file = Path("packages") / product / "pyproject.toml"
    return tomllib.loads((_ROOT / package_file).read_text("utf-8"))["tool"][
        "semantic_release"
    ]


@pytest.mark.parametrize("product", ["ferrastra", "qpane", "cutecanvas"])
def test_product_semantic_release_configuration_is_independent(product: str) -> None:
    """Filter commits and tags through one product's own release history."""
    configuration = _semantic_release_configuration(product)
    assert configuration["commit_parser"] == "conventional-monorepo"
    assert configuration["tag_format"] == f"{product}-v{{version}}"
    assert configuration["version_variables"] == []
    parser = configuration["commit_parser_options"]
    assert f"packages/{product}" in parser["path_filters"]
    assert parser["scope_prefix"] == product
    assert configuration["changelog"]["mode"] == "update"
    assert (
        configuration["changelog"]["default_templates"]["changelog_file"]
        == "CHANGELOG.md"
    )


def test_dynamic_python_versions_remain_tag_owned() -> None:
    """Let setuptools-scm derive Python package versions from PSR tags."""
    for product in ("qpane", "cutecanvas"):
        configuration = _semantic_release_configuration(product)
        assert configuration["version_toml"] == []


def test_ferrastra_release_updates_cargo_version_and_lock_together() -> None:
    """Keep stable native package and resolved workspace versions synchronized."""
    configuration = _semantic_release_configuration("ferrastra")
    assert configuration["allow_zero_version"] is False
    assert set(configuration["commit_parser_options"]["path_filters"]) == {
        "packages/ferrastra",
        "crates",
        "Cargo.toml",
        "Cargo.lock",
        "rust-toolchain.toml",
    }
    assert configuration["version_toml"] == [
        "../../Cargo.toml:workspace.package.version"
    ]
    assert "Cargo.lock" in configuration["assets"]
    assert "cargo check --workspace --all-features" in configuration["build_command"]
