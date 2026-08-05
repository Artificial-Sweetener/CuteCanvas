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
"""Product paths and typed values shared by Trinity validators."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProductContract:
    """Describe one independently published product's Trinity pillars."""

    package: str
    facade_class: str
    root: Path
    stub_name: str
    demo_paths: tuple[Path, ...]
    config_class: str | None

    @property
    def source(self) -> Path:
        """Return the importable package directory."""
        return self.root / "src" / self.package

    @property
    def stub(self) -> Path:
        """Return the authoritative public stub."""
        return self.source / self.stub_name

    @property
    def docs(self) -> Path:
        """Return the product-owned narrative documentation directory."""
        return self.root / "docs"

    @property
    def readme(self) -> Path:
        """Return the product-owned README."""
        return self.root / "README.md"

    @property
    def api_reference(self) -> Path:
        """Return the product's API reference document."""
        return self.docs / "api-reference.md"

    @property
    def guides(self) -> tuple[Path, ...]:
        """Return README and non-reference guides in deterministic order."""
        docs = tuple(
            sorted(
                path for path in self.docs.glob("*.md") if path != self.api_reference
            )
        )
        return (self.readme, *docs)


def repository_products(root: Path) -> tuple[ProductContract, ...]:
    """Return every independently published product contract."""
    return (
        ProductContract(
            package="ferrastra",
            facade_class="Ferrastra",
            root=root / "packages/ferrastra",
            stub_name="ferrastra.pyi",
            demo_paths=(root / "examples/ferrastra_demo.py",),
            config_class=None,
        ),
        ProductContract(
            package="qpane",
            facade_class="QPane",
            root=root / "packages/qpane",
            stub_name="qpane.pyi",
            demo_paths=(
                root / "examples/qpane_demo.py",
                root / "examples/qpane_demonstration",
            ),
            config_class="Config",
        ),
        ProductContract(
            package="cutecanvas",
            facade_class="CuteCanvas",
            root=root / "packages/cutecanvas",
            stub_name="cutecanvas.pyi",
            demo_paths=(
                root / "examples/cutecanvas_demo.py",
                root / "examples/demonstration",
            ),
            config_class="Config",
        ),
    )
