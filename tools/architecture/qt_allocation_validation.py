#    QPane + CuteCanvas + Ferrastra - Native graphics architecture tooling
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
"""Reject unchecked native storage allocation in retained rendering code."""

from __future__ import annotations

import ast
from pathlib import Path

from .model import Diagnostic

_RENDERING_ROOT = Path("packages/qpane/src/qpane/rendering")
_ALLOCATION_OWNER = _RENDERING_ROOT / "storage_allocation.py"


def validate_qt_allocation_safety(root: Path) -> list[Diagnostic]:
    """Return diagnostics for allocations that bypass the checked owner."""
    rendering_root = root / _RENDERING_ROOT
    if not rendering_root.is_dir():
        return []
    diagnostics: list[Diagnostic] = []
    for path in sorted(rendering_root.rglob("*.py")):
        relative = path.relative_to(root)
        if relative == _ALLOCATION_OWNER:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            diagnostic = _unchecked_qt_resource_diagnostic(node, relative)
            if diagnostic is None:
                continue
            diagnostics.append(diagnostic)
    return diagnostics


def _unchecked_qt_resource_diagnostic(
    node: ast.Call,
    relative: Path,
) -> Diagnostic | None:
    """Describe one direct native resource construction when unsafe."""
    if isinstance(node.func, ast.Name) and node.func.id == "QPainter":
        return Diagnostic(
            rule="QTALLOC002",
            path=relative.as_posix(),
            line=node.lineno,
            message=(
                "Route QPainter activation through rendering.storage_allocation "
                "so inactive native painters cannot publish incomplete frames."
            ),
        )
    if not _is_unchecked_allocation(node):
        return None
    return Diagnostic(
        rule="QTALLOC001",
        path=relative.as_posix(),
        line=node.lineno,
        message=(
            "Route size-based QImage/QPixmap allocation through "
            "rendering.storage_allocation so null native storage cannot be "
            "published as a frame."
        ),
    )


def _is_unchecked_allocation(node: ast.Call) -> bool:
    """Return whether one call creates new sized Qt storage directly."""
    if isinstance(node.func, ast.Name) and node.func.id == "QImage":
        return len(node.args) >= 2
    if isinstance(node.func, ast.Name) and node.func.id == "QPixmap":
        if not node.args:
            return False
        first = node.args[0]
        return isinstance(first, (ast.Call, ast.Constant)) or len(node.args) >= 2
    return (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "QPixmap"
        and node.func.attr == "fromImage"
    )


__all__ = ["validate_qt_allocation_safety"]
