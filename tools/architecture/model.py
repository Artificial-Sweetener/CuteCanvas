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
"""Define immutable architecture policy and diagnostic values."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """Describe one actionable architecture finding."""

    rule: str
    path: str
    message: str
    line: int = 1
    severity: str = "error"

    def render(self) -> str:
        """Return a stable path-oriented diagnostic."""
        return f"{self.path}:{self.line}: {self.severity} {self.rule}: {self.message}"


@dataclass(frozen=True, slots=True)
class StructurePolicy:
    """Define repository structural limits."""

    soft_lines: int
    hard_lines: int
    forbidden_names: frozenset[str]


@dataclass(frozen=True, slots=True)
class PythonProductPolicy:
    """Identify one independently owned Python product tree."""

    name: str
    root: Path


@dataclass(frozen=True, slots=True)
class PythonDependencyPolicy:
    """Define one permitted cross-product Python dependency."""

    source: str
    target: str
    allowed_paths: tuple[str, ...]
    allowed_modules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PythonProtectedRootPolicy:
    """Define strict rules for an Ferrastra or adapter source root."""

    path: Path
    product: str
    require_responsibility: bool
    detect_cycles: bool
    forbidden_imports: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PythonLayerPolicy:
    """Define allowed internal imports for one Python layer."""

    name: str
    module_prefix: str
    allowed_internal: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RustCratePolicy:
    """Define one Ferrastra crate's internal dependency allowlist."""

    name: str
    allowed_internal: frozenset[str]
    python_boundary: bool


@dataclass(frozen=True, slots=True)
class ArchitecturePolicy:
    """Aggregate every declarative Stage 0 architecture rule."""

    structure: StructurePolicy
    python_products: tuple[PythonProductPolicy, ...]
    python_dependencies: tuple[PythonDependencyPolicy, ...]
    python_protected_roots: tuple[PythonProtectedRootPolicy, ...]
    python_layers: tuple[PythonLayerPolicy, ...]
    rust_crates: tuple[RustCratePolicy, ...]
