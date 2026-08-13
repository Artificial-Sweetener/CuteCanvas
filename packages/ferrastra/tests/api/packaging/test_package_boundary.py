#    Ferrastra - CPU-first native graphics product engine
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
"""Verify Ferrastra's independent wheel metadata and platform contract."""

from __future__ import annotations

import sys
from typing import Any

from ferrastra_test_support.paths import package_root

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


def _metadata() -> dict[str, Any]:
    """Load Ferrastra's authoritative build metadata."""
    return tomllib.loads((package_root() / "pyproject.toml").read_text("utf-8"))


def test_ferrastra_declares_an_independent_maturin_wheel() -> None:
    """Keep Ferrastra native, dependency-free, and independently packageable."""
    metadata = _metadata()

    assert metadata["build-system"] == {
        "requires": ["maturin==1.14.1"],
        "build-backend": "maturin",
    }
    assert metadata["project"]["dependencies"] == []
    assert metadata["tool"]["maturin"]["module-name"] == "ferrastra._native"
    source = package_root() / "src/ferrastra"
    assert (source / "py.typed").is_file()
    assert (source / "ferrastra.pyi").is_file()
    assert (source / "_native.pyi").is_file()


def test_ferrastra_declares_the_supported_platform_and_python_matrix() -> None:
    """Keep published metadata aligned with the native CI contract."""
    metadata = _metadata()
    classifiers = set(metadata["project"]["classifiers"])

    assert metadata["project"]["requires-python"] == ">=3.10,<3.15"
    assert {
        "Operating System :: Microsoft :: Windows",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        "Programming Language :: Python :: Implementation :: CPython",
    } <= classifiers
