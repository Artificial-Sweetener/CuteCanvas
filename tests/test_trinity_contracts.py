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
"""Characterize the per-package Public API Trinity safeguards."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

from tools.trinity.boundaries import _forbidden_imports, _private_dependency_imports
from tools.trinity.configuration import _compare_mapping
from tools.trinity.demo import validate_demo
from tools.trinity.model import ProductContract
from tools.trinity.provisioning import _compare_tier_extras
from tools.trinity.sdk import _validate_module_contract
from tools.trinity.stubs import StubContract, parse_stub_contract


def _product(root: Path, *, package: str = "qpane") -> ProductContract:
    """Create a focused product contract for static validation tests."""
    return ProductContract(
        package=package,
        facade_class="QPane",
        root=root,
        stub_name="qpane.pyi",
        demo_paths=(root / "demo",),
        config_class="Config",
    )


def test_stub_contract_includes_members_values_and_explicit_reexports(
    tmp_path: Path,
) -> None:
    """Typed members cannot disappear behind top-level-only validation."""
    stub = tmp_path / "contract.pyi"
    stub.write_text(
        "from .types import PublicType as PublicType\n"
        "class QPane:\n"
        "    changed: object\n"
        "    def render(self) -> None: ...\n",
        encoding="utf-8",
    )

    contract = parse_stub_contract(stub)

    assert contract.top_level == {"PublicType", "QPane"}
    assert contract.members == {"QPane.changed", "QPane.render"}


def test_demo_private_package_import_fails(tmp_path: Path) -> None:
    """Tutorials must not bypass a package facade through private modules."""
    demo = tmp_path / "demo"
    demo.mkdir(parents=True)
    (demo / "example.py").write_text(
        '"""Teach a deliberately invalid private package import."""\n'
        "from qpane.rendering import RenderScene\n",
        encoding="utf-8",
    )

    errors = validate_demo(_product(tmp_path))

    assert any("bypasses the qpane facade" in error for error in errors)


def test_reverse_product_dependency_fails(tmp_path: Path) -> None:
    """QPane source must never import the CuteCanvas editor package."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "bad.py").write_text("import cutecanvas\n", encoding="utf-8")

    errors = _forbidden_imports(source, "cutecanvas")

    assert any("imports forbidden package cutecanvas" in error for error in errors)


def test_dependency_submodule_import_fails(tmp_path: Path) -> None:
    """CuteCanvas cannot couple itself to QPane's private module layout."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "bad.py").write_text(
        "from qpane.scene.model import SceneDescriptor\n",
        encoding="utf-8",
    )

    errors = _private_dependency_imports(source, "qpane")

    assert any(
        "bypasses the supported qpane facade or SDK" in error for error in errors
    )


def test_dependency_sdk_import_passes(tmp_path: Path) -> None:
    """CuteCanvas may consume QPane through its explicit integration SDK."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "good.py").write_text(
        "from qpane.sdk.scene import SceneDescriptor\n",
        encoding="utf-8",
    )

    assert _private_dependency_imports(source, "qpane") == []


def test_sdk_runtime_export_missing_from_stub_fails() -> None:
    """An SDK namespace cannot grow outside its typed contract."""
    module = ModuleType("qpane.sdk.example")
    module.__all__ = ("Declared", "Undeclared")
    module.Declared = object()
    module.Undeclared = object()
    contract = StubContract(frozenset({"Declared"}), frozenset())

    errors = _validate_module_contract(module.__name__, module, contract)

    assert errors == [
        "qpane.sdk.example: exported symbol 'Undeclared' is absent from its stub"
    ]


def test_documented_configuration_value_mismatch_fails() -> None:
    """A complete-looking configuration example cannot lie about defaults."""
    errors = _compare_mapping(
        "root",
        {"cache": {"mode": "hard", "budget_mb": 2048}},
        {"cache": {"mode": "auto", "budget_mb": None}},
    )

    assert errors == [
        "value mismatch at root.cache.mode: docs='hard', actual='auto'",
        "value mismatch at root.cache.budget_mb: docs=2048, actual=None",
    ]


def test_demo_tiers_cannot_reference_removed_package_extras() -> None:
    """Trinity rejects stale bootstrap extras and optional ordinary masks."""
    errors = _compare_tier_extras(
        {"cutecanvas": "mask", "cutecanvas-sam": "full"},
        {"sam"},
    )

    assert errors == [
        "demo tier 'cutecanvas' requests unknown CuteCanvas extra 'mask'",
        "demo tier 'cutecanvas-sam' requests unknown CuteCanvas extra 'full'",
        "the standard CuteCanvas demo must use the normal install",
        "the SAM-enabled CuteCanvas demo must request the 'sam' extra",
    ]
