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
"""Characterize the declarative Ferrastra architecture enforcement."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from tools.architecture.model import (
    ArchitecturePolicy,
    Diagnostic,
    PythonDependencyPolicy,
    PythonLayerPolicy,
    PythonProductPolicy,
    PythonProtectedRootPolicy,
    RustCratePolicy,
    StructurePolicy,
)
from tools.architecture.python_validation import validate_python
from tools.architecture.rust_validation import validate_rust
from tools.architecture.waivers import apply_waivers


def _write(path: Path, source: str) -> None:
    """Write one UTF-8 fixture after creating its parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _policy(*, soft_lines: int = 20, hard_lines: int = 30) -> ArchitecturePolicy:
    """Return a compact policy containing every Stage 0 enforcement family."""
    return ArchitecturePolicy(
        structure=StructurePolicy(
            soft_lines=soft_lines,
            hard_lines=hard_lines,
            forbidden_names=frozenset({"utils"}),
        ),
        python_products=(
            PythonProductPolicy("ferrastra", Path("python/ferrastra")),
            PythonProductPolicy("qpane", Path("python/qpane")),
            PythonProductPolicy("cutecanvas", Path("python/cutecanvas")),
        ),
        python_dependencies=(
            PythonDependencyPolicy(
                "qpane",
                "ferrastra",
                ("python/qpane/ferrastra/**",),
                ("ferrastra",),
            ),
        ),
        python_protected_roots=(
            PythonProtectedRootPolicy(
                Path("python/ferrastra"),
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
            RustCratePolicy("ferrastra-core", frozenset(), False),
            RustCratePolicy("ferrastra-python", frozenset({"ferrastra-core"}), True),
        ),
    )


def test_python_policy_reports_each_protected_boundary_rule(tmp_path: Path) -> None:
    """Python product, layer, resource, cycle, and structure rules stay active."""
    _write(tmp_path / "python/qpane/api.py", "import cutecanvas\n")
    _write(tmp_path / "python/qpane/wrong.py", "import ferrastra._private\n")
    _write(
        tmp_path / "python/ferrastra/__init__.py",
        '"""Own the public boundary."""\n'
        "import importlib\n"
        "import ferrastra.internal\n"
        "from concurrent.futures import ThreadPoolExecutor\n"
        "import PySide6\n"
        "LOADER = importlib.import_module('decimal')\n"
        "POOL = ThreadPoolExecutor()\n",
    )
    _write(tmp_path / "python/ferrastra/internal.py", "from . import cycle\n")
    _write(
        tmp_path / "python/ferrastra/cycle.py",
        '"""Own a cycle fixture."""\nfrom . import internal\n',
    )
    _write(
        tmp_path / "python/ferrastra/utils.py",
        '"""Own a naming fixture."""\nVALUE = 1\n',
    )

    rules = {item.rule for item in validate_python(tmp_path, _policy())}

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


def test_python_policy_distinguishes_soft_and_hard_file_limits(tmp_path: Path) -> None:
    """The structural ceiling warns before the absolute source-size gate fails."""
    lines = '"""Own a line-count fixture."""\n' + "\n".join(
        f"VALUE_{index} = {index}" for index in range(6)
    )
    _write(tmp_path / "python/ferrastra/size.py", lines)

    soft = validate_python(tmp_path, _policy(soft_lines=4, hard_lines=20))
    hard = validate_python(tmp_path, _policy(soft_lines=2, hard_lines=4))

    assert any(item.rule == "STRUCT002" and item.severity == "warning" for item in soft)
    assert any(item.rule == "STRUCT003" and item.severity == "error" for item in hard)


def test_rust_policy_reports_dependency_source_and_operation_rules(
    tmp_path: Path,
) -> None:
    """Rust ownership, isolation, safety, scheduling, and contract rules stay active."""
    _write(
        tmp_path / "crates/ferrastra-core/Cargo.toml",
        '[package]\nname = "ferrastra-core"\nversion = "0.1.0"\n'
        '[dependencies]\nferrastra-python = "0.1"\npyo3 = "0.29"\nqt6 = "0.1"\nqpane = "0.1"\n',
    )
    _write(
        tmp_path / "crates/ferrastra-core/src/lib.rs",
        "unsafe fn unchecked() {}\n"
        "fn leak() { let _ = QImage; rayon::spawn(|| {}); let _ = pyo3::Python::attach; }\n"
        "impl Operation for Example {}\n",
    )
    _write(
        tmp_path / "crates/ferrastra-python/Cargo.toml",
        '[package]\nname = "ferrastra-python"\nversion = "0.1.0"\n'
        '[dependencies]\nferrastra-core = "0.1"\n',
    )
    _write(
        tmp_path / "crates/ferrastra-python/src/lib.rs",
        "//! Responsibility: expose the Python boundary.\n//! Does not own: engine semantics.\n",
    )
    _write(
        tmp_path / "crates/unowned/Cargo.toml",
        '[package]\nname = "ferrastra-unowned"\nversion = "0.1.0"\n',
    )

    rules = {item.rule for item in validate_rust(tmp_path, _policy())}

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


def test_waivers_require_active_exact_and_used_ownership(tmp_path: Path) -> None:
    """Only active, matching waivers suppress architecture diagnostics."""
    waiver_path = tmp_path / "ARCHITECTURE_WAIVERS.toml"
    _write(
        waiver_path,
        "schema_version = 1\n"
        "[[waivers]]\n"
        'id = "owned-exception"\nrule = "PY006"\npath = "python/ferrastra/api.py"\n'
        'owner = "graphics-team"\nreason = "bounded transition"\n'
        'issue = "FERRASTRA-1"\nexpires = 2030-01-01\n',
    )
    diagnostic = Diagnostic("PY006", "python/ferrastra/api.py", "fixture")

    assert apply_waivers([diagnostic], waiver_path, today=date(2029, 1, 1)) == []
    assert {
        item.rule for item in apply_waivers([], waiver_path, today=date(2029, 1, 1))
    } == {"WAIVER002"}
    assert {
        item.rule for item in apply_waivers([], waiver_path, today=date(2031, 1, 1))
    } == {"WAIVER001"}
