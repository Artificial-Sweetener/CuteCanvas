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
"""Characterize Ferrastra's behavior-neutral Stage 0 package boundary."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import ast
from pathlib import Path

import ferrastra
from ferrastra import _native


def test_native_and_python_package_versions_match() -> None:
    """Keep the wheel metadata and embedded native version identical."""
    assert ferrastra.__version__ == _native.package_version()


def test_public_surface_contains_only_package_identity() -> None:
    """Keep graphics behavior out of the Stage 0 package."""
    assert ferrastra.__all__ == ["__version__"]


def test_typed_contract_matches_runtime_exports() -> None:
    """Keep the authoritative Python contract aligned with the runtime facade."""
    contract = Path(__file__).parents[1] / "src/ferrastra/ferrastra.pyi"

    assert _declared_names(contract) == set(ferrastra.__all__)


def test_native_stub_matches_generated_extension_surface() -> None:
    """Keep the checked-in native stub aligned with the generated PyO3 module."""
    contract = Path(__file__).parents[1] / "src/ferrastra/_native.pyi"
    native_public = {name for name in dir(_native) if not name.startswith("_")}

    assert _declared_names(contract) == native_public


def _declared_names(path: Path) -> set[str]:
    """Return top-level values and callables declared by a stub contract."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            names.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names
