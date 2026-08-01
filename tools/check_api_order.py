#!/usr/bin/env python3
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
"""Verify that both package facades implement their typed method contracts."""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FacadeContract:
    """Describe one public facade and the focused classes implementing it."""

    name: str
    stub: Path
    sources: tuple[Path, ...]
    implementation_classes: frozenset[str]


def contracted_methods(stub: Path, class_name: str) -> set[str]:
    """Return all methods declared on one public facade class."""
    tree = ast.parse(stub.read_text(encoding="utf-8"), filename=str(stub))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                member.name
                for member in node.body
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    raise ValueError(f"{stub} does not declare class {class_name}")


def implemented_methods(contract: FacadeContract) -> set[str]:
    """Return methods implemented by the facade and its focused API mixins."""
    methods: set[str] = set()
    for source in contract.sources:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in tree.body:
            if (
                isinstance(node, ast.ClassDef)
                and node.name in contract.implementation_classes
            ):
                methods.update(
                    member.name
                    for member in node.body
                    if isinstance(
                        member,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                )
    return methods


def _contracts(root: Path) -> tuple[FacadeContract, ...]:
    """Build the two monorepo facade contracts."""
    cutecanvas_root = root / "packages/cutecanvas/src/cutecanvas"
    return (
        FacadeContract(
            "QPane",
            root / "packages/qpane/src/qpane/qpane.pyi",
            (root / "packages/qpane/src/qpane/viewer.py",),
            frozenset({"QPane"}),
        ),
        FacadeContract(
            "CuteCanvas",
            cutecanvas_root / "cutecanvas.pyi",
            (
                cutecanvas_root / "canvas.py",
                *tuple(sorted((cutecanvas_root / "facade").glob("*_api.py"))),
                cutecanvas_root / "runtime/accessors.py",
            ),
            frozenset(
                {
                    "CuteCanvas",
                    "ComparisonApiMixin",
                    "CompositionApiMixin",
                    "ConfigurationApiMixin",
                    "CoverageApiMixin",
                    "DiagnosticsApiMixin",
                    "EditorPolicyApiMixin",
                    "EffectApiMixin",
                    "EmbeddedImageExportApiMixin",
                    "OutboundDragApiMixin",
                    "ProjectionApiMixin",
                    "MaskApiMixin",
                    "PlacedAssetApiMixin",
                    "ResourceApiMixin",
                    "VectorApiMixin",
                    "RasterApiMixin",
                    "SnappingApiMixin",
                    "InteractionApiMixin",
                    "LayerApiMixin",
                    "ViewApiMixin",
                    "ViewportApiMixin",
                    "CanvasAccessorsMixin",
                }
            ),
        ),
    )


def main() -> None:
    """Fail when either public stub advertises an unimplemented method."""
    root = Path(__file__).resolve().parent.parent
    errors: list[str] = []
    for contract in _contracts(root):
        declared = contracted_methods(contract.stub, contract.name)
        missing = declared - implemented_methods(contract)
        errors.extend(
            f"{contract.name}: {method!r} has no facade implementation"
            for method in sorted(missing)
        )
    if errors:
        print("FAILED: Facade API contracts are incomplete.")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)
    print("SUCCESS: QPane and CuteCanvas facades match their contracts.")


if __name__ == "__main__":
    main()
