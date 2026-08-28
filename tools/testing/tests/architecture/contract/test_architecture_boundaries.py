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
"""Prove repository-wide dependency, structure, and product routing rules."""

from __future__ import annotations

from pathlib import Path

from tools.architecture.model import StructureCategoryPolicy
from tools.architecture.policy_validation import validate_policy_ownership
from tools.architecture.python_validation import validate_python
from tools.architecture.qt_allocation_validation import validate_qt_allocation_safety
from tools.architecture.rust_validation import validate_rust
from tools.architecture.structure_validation import validate_python_structure
from tools.testing.tests.architecture.contract.architecture_governance_support import (
    empty_state,
    policy,
    write,
)


def test_python_policy_reports_each_protected_boundary_rule(tmp_path: Path) -> None:
    """Python dependency, layer, resource, cycle, and naming rules stay active."""
    write(tmp_path / "packages/qpane/src/qpane/api.py", "import cutecanvas\n")
    write(tmp_path / "packages/qpane/src/qpane/wrong.py", "import ferrastra._private\n")
    write(
        tmp_path / "packages/ferrastra/src/ferrastra/__init__.py",
        '"""Own the public boundary."""\n'
        "import importlib\nimport ferrastra.internal\nimport PySide6\n"
        "from concurrent.futures import ThreadPoolExecutor\n"
        "LOADER = importlib.import_module('decimal')\nPOOL = ThreadPoolExecutor()\n",
    )
    write(
        tmp_path / "packages/ferrastra/src/ferrastra/internal.py",
        "from . import cycle\n",
    )
    write(
        tmp_path / "packages/ferrastra/src/ferrastra/cycle.py",
        '"""Own a cycle fixture."""\nfrom . import internal\n',
    )
    write(
        tmp_path / "packages/ferrastra/src/ferrastra/utils.py",
        '"""Own a naming fixture."""\nVALUE = 1\n',
    )

    rules = {item.rule for item in validate_python(tmp_path, policy())}

    assert {
        "PY001",
        "PY002",
        "PY003",
        "PY004",
        "PY005",
        "PY006",
        "PY007",
        "PY008",
        "PY009",
        "STRUCT001",
    } <= rules


def test_retained_rendering_rejects_unchecked_native_storage_allocation(
    tmp_path: Path,
) -> None:
    """Direct frame-sized Qt allocation must fail the repository architecture gate."""
    unsafe = tmp_path / "packages/qpane/src/qpane/rendering/unsafe_surface.py"
    write(
        unsafe,
        "from PySide6.QtCore import QSize\n"
        "from PySide6.QtGui import QImage\n"
        "IMAGE = QImage(QSize(100, 100), QImage.Format_ARGB32)\n",
    )

    diagnostics = validate_qt_allocation_safety(tmp_path)

    assert [(item.rule, item.path, item.line) for item in diagnostics] == [
        (
            "QTALLOC001",
            "packages/qpane/src/qpane/rendering/unsafe_surface.py",
            3,
        )
    ]


def test_retained_rendering_accepts_the_checked_allocation_owner(
    tmp_path: Path,
) -> None:
    """The single checked owner may construct Qt storage for validation and retry."""
    owner = tmp_path / "packages/qpane/src/qpane/rendering/storage_allocation.py"
    write(
        owner,
        "from PySide6.QtCore import QSize\n"
        "from PySide6.QtGui import QImage\n"
        "IMAGE = QImage(QSize(100, 100), QImage.Format_ARGB32)\n",
    )

    assert validate_qt_allocation_safety(tmp_path) == []


def test_retained_rendering_rejects_unchecked_native_painter_activation(
    tmp_path: Path,
) -> None:
    """Direct painter activation must fail because Qt can return an inactive painter."""
    unsafe = tmp_path / "packages/qpane/src/qpane/rendering/unsafe_painter.py"
    write(
        unsafe,
        "from PySide6.QtGui import QPainter\nPAINTER = QPainter(object())\n",
    )

    diagnostics = validate_qt_allocation_safety(tmp_path)

    assert [(item.rule, item.path, item.line) for item in diagnostics] == [
        (
            "QTALLOC002",
            "packages/qpane/src/qpane/rendering/unsafe_painter.py",
            2,
        )
    ]


def test_global_size_policy_uses_judgment_first_diagnostics(tmp_path: Path) -> None:
    """All products receive the same size gate and ownership-first response."""
    for name in ("ferrastra", "qpane", "cutecanvas"):
        write(
            tmp_path / f"packages/{name}/src/{name}/large.py",
            "\n".join(f"VALUE_{index} = {index}" for index in range(7)),
        )
    diagnostics = validate_python_structure(
        tmp_path,
        policy(soft_lines=4, hard_lines=6),
    )

    assert {item.path.split("/")[1] for item in diagnostics} == {
        "ferrastra",
        "qpane",
        "cutecanvas",
    }
    assert all(item.rule == "STRUCT003" for item in diagnostics)
    assert all("First assess ownership" in item.message for item in diagnostics)
    assert all("adding behavior is prohibited" in item.message for item in diagnostics)
    assert all("genuinely warranted" in item.message for item in diagnostics)


def test_exact_contract_category_avoids_an_inapplicable_line_metric(
    tmp_path: Path,
) -> None:
    """A reviewed exact contract path is not treated as an implementation file."""
    path = Path("packages/qpane/src/qpane/qpane.pyi")
    write(tmp_path / path, "\n".join(f"value_{index}: int" for index in range(8)))
    category = StructureCategoryPolicy(
        "authoritative-contract",
        "qpane",
        path,
        "One complete public typed contract.",
    )

    assert (
        validate_python_structure(
            tmp_path,
            policy(soft_lines=2, hard_lines=4, categories=(category,)),
        )
        == []
    )


def test_rust_policy_reports_dependency_source_and_operation_rules(
    tmp_path: Path,
) -> None:
    """Rust ownership, isolation, safety, scheduling, and contracts stay active."""
    write(
        tmp_path / "crates/ferrastra-core/Cargo.toml",
        '[package]\nname = "ferrastra-core"\nversion = "0.1.0"\n'
        '[dependencies]\nferrastra-python = "0.1"\npyo3 = "0.29"\nqt6 = "0.1"\nqpane = "0.1"\n',
    )
    write(
        tmp_path / "crates/ferrastra-core/src/lib.rs",
        "unsafe fn unchecked() {}\n"
        "fn leak() { let _ = QImage; rayon::spawn(|| {}); let _ = pyo3::Python::attach; }\n"
        "impl Operation for Example {}\n",
    )
    write(
        tmp_path / "crates/ferrastra-python/Cargo.toml",
        '[package]\nname = "ferrastra-python"\nversion = "0.1.0"\n'
        '[dependencies]\nferrastra-core = "0.1"\n',
    )
    write(
        tmp_path / "crates/ferrastra-python/src/lib.rs",
        "//! Responsibility: expose the Python boundary.\n//! Does not own: engine semantics.\n",
    )
    write(
        tmp_path / "crates/unowned/Cargo.toml",
        '[package]\nname = "ferrastra-unowned"\nversion = "0.1.0"\n',
    )

    rules = {item.rule for item in validate_rust(tmp_path, policy())}

    assert {
        "RUST002",
        "RUST003",
        "RUST004",
        "RUST005",
        "RUST006",
        "RUST007",
        "RUST008",
        "RUST009",
        "RUST010",
        "RUST011",
        "RUST012",
        "RUST013",
    } <= rules


def test_policy_requires_product_local_state_and_exact_category_ownership(
    tmp_path: Path,
) -> None:
    """Root state and misowned category paths are rejected explicitly."""
    empty_state(tmp_path)
    write(tmp_path / "ARCHITECTURE_WAIVERS.toml", "schema_version = 1\n")
    wrong_path = Path("packages/qpane/src/qpane/contract.pyi")
    write(tmp_path / wrong_path, "value: int\n")
    category = StructureCategoryPolicy(
        "wrong-owner",
        "cutecanvas",
        wrong_path,
        "Deliberately invalid owner.",
    )

    rules = {
        item.rule
        for item in validate_policy_ownership(
            tmp_path,
            policy(categories=(category,)),
        )
    }

    assert {"POLICY002", "POLICY011"} <= rules
