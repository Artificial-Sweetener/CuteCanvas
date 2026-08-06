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

"""Resolve the monorepo boundary for package-owned subprocess tests."""

from __future__ import annotations

from pathlib import Path


def package_root() -> Path:
    """Return the CuteCanvas Python package project root."""
    return Path(__file__).resolve().parents[2]


def repository_root() -> Path:
    """Return the nearest parent containing the workspace package roots."""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "Cargo.toml").is_file() and (
            candidate / "packages" / "cutecanvas"
        ).is_dir():
            return candidate
    raise RuntimeError("CuteCanvas tests could not locate the repository root")
