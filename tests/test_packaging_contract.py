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

from pathlib import Path
import tomllib


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
