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
"""Build strict synthetic repository state for architecture checker tests."""

from __future__ import annotations

from pathlib import Path

from tools.architecture.model import (
    ArchitecturePolicy,
    PythonDependencyPolicy,
    PythonLayerPolicy,
    PythonProductPolicy,
    PythonProtectedRootPolicy,
    RustCratePolicy,
    StructureCategoryPolicy,
    StructurePolicy,
)


def write(path: Path, source: str) -> None:
    """Write one UTF-8 fixture after creating its parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def policy(
    *,
    soft_lines: int = 20,
    hard_lines: int = 30,
    categories: tuple[StructureCategoryPolicy, ...] = (),
) -> ArchitecturePolicy:
    """Return a compact policy containing every enforcement family."""
    return ArchitecturePolicy(
        structure=StructurePolicy(
            soft_lines=soft_lines,
            hard_lines=hard_lines,
            forbidden_names=frozenset({"utils"}),
        ),
        python_products=tuple(
            _product(name) for name in ("ferrastra", "qpane", "cutecanvas")
        ),
        structure_categories=categories,
        python_dependencies=(
            PythonDependencyPolicy(
                "qpane",
                "ferrastra",
                ("packages/qpane/src/qpane/ferrastra/**",),
                ("ferrastra",),
            ),
        ),
        python_protected_roots=(
            PythonProtectedRootPolicy(
                Path("packages/ferrastra/src/ferrastra"),
                "ferrastra",
                True,
                True,
                ("PySide6", "qpane", "cutecanvas"),
            ),
        ),
        python_layers=(
            PythonLayerPolicy("ferrastra-public", "ferrastra", ("ferrastra._native",)),
        ),
        rust_crates=(
            RustCratePolicy("ferrastra-core", "ferrastra", frozenset(), False),
            RustCratePolicy(
                "ferrastra-python",
                "ferrastra",
                frozenset({"ferrastra-core"}),
                True,
            ),
        ),
    )


def empty_state(root: Path) -> None:
    """Create all required empty product-local state snapshots."""
    for name in ("ferrastra", "qpane", "cutecanvas"):
        package = root / "packages" / name
        write(
            package / "ARCHITECTURE_DEBT.toml",
            f'schema_version = 1\nproduct = "{name}"\ndebts = []\n',
        )
        write(
            package / "ARCHITECTURE_WAIVERS.toml",
            f'schema_version = 1\nproduct = "{name}"\nwaivers = []\n',
        )
        write(package / "src" / name / "__init__.py", '"""Own the product."""\n')


def debt_document(source_path: str, fingerprint: str, identifier: str) -> str:
    """Return one valid current QPane debt document."""
    return (
        'schema_version = 1\nproduct = "qpane"\n[[debts]]\n'
        f'id = "{identifier}"\nowner = "QPane"\n'
        f'paths = ["{source_path}"]\nfingerprint = "{fingerprint}"\n'
        f'issue = "chore:{identifier}"\nreview_by = 2030-01-01\n'
        'responsibilities = ["state", "presentation"]\n'
        'next_extraction = "Extract presentation."\n'
    )


def _product(name: str) -> PythonProductPolicy:
    """Return one synthetic product with required local registries."""
    package = Path("packages") / name
    return PythonProductPolicy(
        name,
        package / "src" / name,
        package / "ARCHITECTURE_DEBT.toml",
        package / "ARCHITECTURE_WAIVERS.toml",
    )
