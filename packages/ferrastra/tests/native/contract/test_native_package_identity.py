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

"""Characterize the Stage 0 native extension's package identity contract."""

from __future__ import annotations

from importlib import import_module

import ferrastra
from ferrastra_test_support.contracts import declared_names
from ferrastra_test_support.paths import package_root

_native = import_module("ferrastra._native")


def test_native_and_python_package_versions_match() -> None:
    """Keep wheel metadata and the embedded native version identical."""
    assert ferrastra.__version__ == _native.package_version()


def test_native_stub_matches_generated_extension_surface() -> None:
    """Keep the native stub aligned with the generated PyO3 module."""
    contract = package_root() / "src/ferrastra/_native.pyi"
    native_public = {name for name in dir(_native) if not name.startswith("_")}

    assert declared_names(contract) == native_public
