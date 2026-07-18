#!/usr/bin/env python3
#    QPane - High-performance PySide6 image viewer
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

"""Verify that qpane.py follows the defined code organization and API visibility rules.

Ensures that public methods defined in qpane.pyi are located above the internal
implementation banner in qpane.py, and that internal methods are below it.
"""

import ast
import sys
from pathlib import Path

LAYOUT_GUIDELINES = """
# Code Organization Guide

This repository follows a consistent layout to keep modules readable and predictable. Use the ordering below when adding or refactoring classes, modules, or scripts.

- **Module preamble**: Start with a concise module docstring, then imports grouped as stdlib -> third-party -> local. Keep TYPE_CHECKING imports isolated and initialize the module logger (e.g., `logger = logging.getLogger(__name__)`).
- **Public surface first**: Place public constants, enums, signals/events, and simple static helpers near the top so callers see the API before the internals.
- **Facade/proxy accessors**: Group thin accessors that expose key collaborators (view/presenter/catalog equivalents, managers, registries) together so ownership boundaries stay clear and pre-init guards live in one place.
- **Construction and wiring**: Cluster the constructor and core setup helpers next. Build foundational collaborators first, then optional/feature-specific wiring. Keep normalization/default-selection helpers adjacent to where they are used.
- **Configuration and diagnostics**: Follow setup with configuration applicators, diagnostics collectors, and status/overlay creation helpers. These functions should reapply config and refresh dependent services.
- **Registration/attachment utilities**: Keep registration and attach/detach helpers together (tools, overlays, cursors, services, autosave, etc.). These should be slim pass-throughs that preserve single ownership of state.
- **Domain-focused operations**: Organize feature logic in cohesive blocks (e.g., catalog-like operations, mask-like workflows, viewport/navigation helpers). Within each block, prefer the sequence: read/query helpers -> mutating operations -> async/prefetch helpers.
- **State persistence and view adjustments**: Place pan/zoom or analogous state persistence helpers near the operations that rely on them to keep flow obvious.
- **Rendering/processing entry points**: Keep core "apply/set" entry points (like setting content, allocating buffers, or marking dirty regions) grouped and close to related helpers.
- **Geometry/utility helpers**: Follow with geometry/coordinate conversions or other utility helpers that support rendering or interaction.
- **Event handlers last**: Finish with UI/event plumbing (paint, resize, wheel/mouse/key/enter/leave/show handlers). Handlers should delegate to the interaction layer/delegates rather than owning logic directly.

General style notes:

- Favor expressive names and focused functions so the code explains itself; inline comments should only clarify non-obvious behaviour.
- Keep docstrings concise and in present tense; add Args/Returns/Raises only when signatures are not self-evident.
- Route interactive state through the appropriate delegate/interaction layer; obtain rendering/caching/catalog collaborators via their exposed facades rather than directly reaching into private attributes.
- Group related helpers tightly and avoid scattering lifecycle hooks across the file. If you add a new domain block, keep its accessors, mutators, and lifecycle utilities together.
"""


def get_public_methods(pyi_path: Path) -> set[str]:
    """Extract method names defined in the QPane class within the .pyi file."""
    if not pyi_path.exists():
        print(f"Error: Stub file not found at {pyi_path}")
        sys.exit(1)
    try:
        tree = ast.parse(pyi_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError) as e:
        print(f"Error parsing {pyi_path}: {e}")
        sys.exit(1)
    public_methods = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "QPane":
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    public_methods.add(item.name)
                # Handle decorated properties
                if isinstance(item, ast.FunctionDef):
                    for decorator in item.decorator_list:
                        if (
                            isinstance(decorator, ast.Name)
                            and decorator.id == "property"
                        ):
                            public_methods.add(item.name)
    return public_methods


def get_implementation_details(py_path: Path) -> tuple[int, dict[str, int]]:
    """Find the banner line and map method names to line numbers in the .py file."""
    if not py_path.exists():
        print(f"Error: Source file not found at {py_path}")
        sys.exit(1)
    content = py_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    banner_line = -1
    for i, line in enumerate(lines):
        if "# Internal Implementation" in line:
            banner_line = i + 1
            break
    if banner_line == -1:
        print(f"Error: Could not find '# Internal Implementation' banner in {py_path}")
        sys.exit(1)
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        print(f"Error parsing {py_path}: {e}")
        sys.exit(1)
    method_lines = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "QPane":
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_lines[item.name] = item.lineno
    return banner_line, method_lines


def main():
    root = Path(__file__).resolve().parent.parent
    pyi_path = root / "qpane" / "qpane.pyi"
    py_path = root / "qpane" / "qpane.py"
    public_methods = get_public_methods(pyi_path)
    banner_line, method_lines = get_implementation_details(py_path)
    hidden_public_api = []
    leaking_internal_api = []
    for name, lineno in method_lines.items():
        is_public = name in public_methods
        is_above_banner = lineno < banner_line
        if is_public and not is_above_banner:
            hidden_public_api.append((name, lineno))
        elif not is_public and is_above_banner:
            # Optional: Ignore dunder methods if they aren't in pyi?
            # For now, we flag everything to be strict as requested.
            leaking_internal_api.append((name, lineno))
    if not hidden_public_api and not leaking_internal_api:
        print("SUCCESS: QPane API organization matches the contract.")
        sys.exit(0)
    print(f"\n[FAIL] API Organization Violation in {py_path.relative_to(root)}")
    if hidden_public_api:
        print("\nVIOLATION: Hidden Public API")
        print("----------------------------")
        print(
            "The following methods are defined in qpane.pyi (Public Contract) but are located"
        )
        print("BELOW the 'Internal Implementation' banner in qpane.py:")
        print()
        for name, lineno in sorted(hidden_public_api, key=lambda x: x[1]):
            print(f"  - {name} (Line {lineno})")
        print(
            "\nFIX: Move these methods UP, above the 'Internal Implementation' banner."
        )
        print("     Public API methods must be visible at the top of the file.")
    if leaking_internal_api:
        print("\nVIOLATION: Leaking Internal API")
        print("-------------------------------")
        print(
            "The following methods are NOT in qpane.pyi but are located ABOVE the banner:"
        )
        print()
        for name, lineno in sorted(leaking_internal_api, key=lambda x: x[1]):
            print(f"  - {name} (Line {lineno})")
        print("\nFIX:")
        print(
            "  1. If this IS public: Add it to qpane.pyi to declare it as part of the contract."
        )
        print(
            "  2. If this IS internal: Move it DOWN, below the 'Internal Implementation' banner."
        )
    print("\n" + "=" * 60)
    print("REFERENCE: LAYOUT GUIDELINES")
    print("=" * 60)
    print(LAYOUT_GUIDELINES)
    print("=" * 60)
    sys.exit(1)


if __name__ == "__main__":
    main()
