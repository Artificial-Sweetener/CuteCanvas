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
"""Expose Ferrastra's typed package boundary."""

from __future__ import annotations

from importlib.metadata import version

from ._native import package_version as _native_package_version

__all__ = ["__version__"]

__version__ = version("ferrastra")

if _native_package_version() != __version__:
    raise ImportError(
        "Ferrastra Python and native package versions differ: "
        f"python={__version__!r}, native={_native_package_version()!r}"
    )
