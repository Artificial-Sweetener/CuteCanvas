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
"""Parse complete public symbol contracts from package stub files."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StubContract:
    """Hold public top-level names and explicitly declared class members."""

    top_level: frozenset[str]
    members: frozenset[str]

    @property
    def documented_symbols(self) -> frozenset[str]:
        """Return every symbol requiring reference and guide coverage."""
        return self.top_level | self.members


def parse_stub_contract(path: Path) -> StubContract:
    """Parse public definitions, re-exports, values, and class members."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    top_level: set[str] = set()
    members: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and _is_public(node.name):
            top_level.add(node.name)
            members.update(_class_members(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_public(
            node.name
        ):
            top_level.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if _is_public(node.target.id):
                top_level.add(node.target.id)
        elif isinstance(node, ast.Assign):
            top_level.update(
                target.id
                for target in node.targets
                if isinstance(target, ast.Name) and _is_public(target.id)
            )
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            top_level.update(_explicit_reexports(node))
    return StubContract(frozenset(top_level), frozenset(members))


def _class_members(node: ast.ClassDef) -> set[str]:
    """Return public members explicitly declared by one stub class."""
    names: set[str] = set()
    for member in node.body:
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_public(member.name):
                names.add(f"{node.name}.{member.name}")
        elif isinstance(member, ast.AnnAssign) and isinstance(member.target, ast.Name):
            if _is_public(member.target.id):
                names.add(f"{node.name}.{member.target.id}")
        elif isinstance(member, ast.Assign):
            names.update(
                f"{node.name}.{target.id}"
                for target in member.targets
                if isinstance(target, ast.Name) and _is_public(target.id)
            )
    return names


def _explicit_reexports(node: ast.Import | ast.ImportFrom) -> set[str]:
    """Return imports whose explicit alias marks them as stub re-exports."""
    names: set[str] = set()
    for alias in node.names:
        exposed = alias.asname
        if exposed is not None and exposed == alias.name.rsplit(".", 1)[-1]:
            names.add(exposed)
    return names


def _is_public(name: str) -> bool:
    """Return whether a contract name is public."""
    return name == "__version__" or not name.startswith("_")
