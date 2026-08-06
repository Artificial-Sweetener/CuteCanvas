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
"""Prove product-local debt, waivers, fingerprints, and staged reconciliation."""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

from tools.architecture.checker import validate_repository
from tools.architecture.model import Diagnostic
from tools.architecture.snapshot import repository_snapshot
from tools.architecture.source_metrics import source_fingerprint
from tools.architecture.state_validation import validate_architecture_state
from tools.architecture.structure_validation import validate_python_structure
from tools.architecture.waiver_application import apply_architecture_waivers
from tools.testing.policy import repository_root
from tools.testing.tests.architecture.contract.architecture_governance_support import (
    debt_document,
    empty_state,
    policy,
    write,
)


def test_debt_fingerprint_and_linked_waiver_are_current_snapshots(
    tmp_path: Path,
) -> None:
    """Current mixed debt uses exact source identity and a bounded linked waiver."""
    empty_state(tmp_path)
    source_path = "packages/qpane/src/qpane/large.py"
    write(
        tmp_path / source_path,
        "\n".join(f"VALUE_{index} = {index}" for index in range(8)),
    )
    fingerprint = source_fingerprint(tmp_path, (source_path,))
    write(
        tmp_path / "packages/qpane/ARCHITECTURE_DEBT.toml",
        debt_document(source_path, fingerprint, "QPANE-ARCH-001"),
    )
    write(
        tmp_path / "packages/qpane/ARCHITECTURE_WAIVERS.toml",
        'schema_version = 1\nproduct = "qpane"\n'
        "[[waivers]]\n"
        'id = "QPANE-WAIVER-001"\nowner = "QPane API"\nrule = "STRUCT003"\n'
        f'path = "{source_path}"\nkind = "remediation"\n'
        'justification = "Existing mixed ownership is queued for extraction."\n'
        'issue = "chore:QPANE-WAIVER-001"\n'
        "review_by = 2030-01-01\nmax_lines = 8\nnext_limit = 4\n"
        'debt = "QPANE-ARCH-001"\n',
    )

    active_policy = policy(soft_lines=4, hard_lines=6)
    states, state_diagnostics = validate_architecture_state(
        tmp_path,
        active_policy,
        today=date(2029, 1, 1),
    )
    source_diagnostics = validate_python_structure(tmp_path, active_policy)

    assert state_diagnostics == []
    assert (
        apply_architecture_waivers(
            source_diagnostics,
            states,
            today=date(2029, 1, 1),
        )
        == []
    )


def test_registry_rejects_history_fields(tmp_path: Path) -> None:
    """Registry state cannot combine its current snapshot with a ledger."""
    empty_state(tmp_path)
    source_path = "packages/qpane/src/qpane/mixed.py"
    write(tmp_path / source_path, "VALUE = 1\n")
    content = debt_document(source_path, "sha256:stale", "QPANE-ARCH-002")
    write(
        tmp_path / "packages/qpane/ARCHITECTURE_DEBT.toml",
        f"{content}previous_lines = 900\n",
    )

    states, diagnostics = validate_architecture_state(
        tmp_path,
        policy(),
        today=date(2029, 1, 1),
    )

    assert not any(state.product == "qpane" for state in states)
    assert any(item.rule == "STATE001" for item in diagnostics)
    assert any("unsupported" in item.message for item in diagnostics)


def test_expired_and_stale_debt_facts_fail(tmp_path: Path) -> None:
    """A debt snapshot must match current source and retain an active review date."""
    empty_state(tmp_path)
    source_path = "packages/qpane/src/qpane/mixed.py"
    write(tmp_path / source_path, "VALUE = 1\n")
    document = debt_document(source_path, "sha256:stale", "QPANE-ARCH-003")
    write(
        tmp_path / "packages/qpane/ARCHITECTURE_DEBT.toml",
        document.replace("2030-01-01", "2028-01-01"),
    )

    _, diagnostics = validate_architecture_state(
        tmp_path,
        policy(),
        today=date(2029, 1, 1),
    )

    assert {"DEBT002", "DEBT003"} <= {item.rule for item in diagnostics}


def test_exact_paths_and_same_product_remediation_links_are_required(
    tmp_path: Path,
) -> None:
    """Globs and unlinked or non-tightening remediation records are rejected."""
    empty_state(tmp_path)
    source_path = "packages/qpane/src/qpane/large.py"
    write(tmp_path / source_path, "ONE = 1\nTWO = 2\n")
    write(
        tmp_path / "packages/qpane/ARCHITECTURE_DEBT.toml",
        debt_document(
            "packages/qpane/src/qpane/*.py",
            "sha256:invalid",
            "QPANE-ARCH-004",
        ),
    )
    write(
        tmp_path / "packages/qpane/ARCHITECTURE_WAIVERS.toml",
        'schema_version = 1\nproduct = "qpane"\n[[waivers]]\n'
        'id = "QPANE-WAIVER-004"\nowner = "QPane"\nrule = "STRUCT003"\n'
        f'path = "{source_path}"\nkind = "remediation"\n'
        'justification = "Invalid linkage fixture."\n'
        'issue = "chore:QPANE-WAIVER-004"\nreview_by = 2030-01-01\n'
        'max_lines = 2\nnext_limit = 2\ndebt = "MISSING-DEBT"\n',
    )

    _, diagnostics = validate_architecture_state(
        tmp_path,
        policy(),
        today=date(2029, 1, 1),
    )

    rules = {item.rule for item in diagnostics}
    assert {"STATE003", "WAIVER004", "WAIVER005"} <= rules


def test_staged_snapshot_requires_debt_reconciliation(tmp_path: Path) -> None:
    """The staged source fingerprint wins over an updated unstaged registry."""
    empty_state(tmp_path)
    source_path = "packages/qpane/src/qpane/mixed.py"
    write(tmp_path / source_path, "STATE = 1\nPRESENTATION = 2\n")
    baseline = source_fingerprint(tmp_path, (source_path,))
    registry = tmp_path / "packages/qpane/ARCHITECTURE_DEBT.toml"
    write(registry, debt_document(source_path, baseline, "QPANE-ARCH-005"))
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    subprocess.run(("git", "add", "."), cwd=tmp_path, check=True)
    write(tmp_path / source_path, "STATE = 1\nPRESENTATION = 3\n")
    subprocess.run(("git", "add", source_path), cwd=tmp_path, check=True)
    current = source_fingerprint(tmp_path, (source_path,))
    write(registry, debt_document(source_path, current, "QPANE-ARCH-005"))

    with repository_snapshot(tmp_path, staged=True) as snapshot:
        _, diagnostics = validate_architecture_state(
            snapshot,
            policy(),
            today=date(2029, 1, 1),
        )

    assert any(item.rule == "DEBT003" for item in diagnostics)
    assert any(
        "Do not append review or improvement history" in item.message
        for item in diagnostics
    )


def test_source_fingerprint_is_stable_across_supported_platform_newlines(
    tmp_path: Path,
) -> None:
    """The same assessed source has one identity on Windows, macOS, and Linux."""
    source_path = "packages/qpane/src/qpane/mixed.py"
    path = tmp_path / source_path
    path.parent.mkdir(parents=True)
    path.write_bytes(b"STATE = 1\nPRESENTATION = 2\n")
    line_feed = source_fingerprint(tmp_path, (source_path,))
    path.write_bytes(b"STATE = 1\r\nPRESENTATION = 2\r\n")

    assert source_fingerprint(tmp_path, (source_path,)) == line_feed


def test_unused_and_expired_waivers_fail_instead_of_hiding_stale_state(
    tmp_path: Path,
) -> None:
    """Every waiver remains exact, current, active, and used."""
    empty_state(tmp_path)
    source_path = "packages/qpane/src/qpane/small.py"
    write(tmp_path / source_path, "VALUE = 1\n")
    write(
        tmp_path / "packages/qpane/ARCHITECTURE_WAIVERS.toml",
        'schema_version = 1\nproduct = "qpane"\n[[waivers]]\n'
        'id = "QPANE-WAIVER-005"\nowner = "QPane"\nrule = "STRUCT003"\n'
        f'path = "{source_path}"\nkind = "structural"\n'
        'justification = "Deliberately stale fixture."\n'
        'issue = "chore:QPANE-WAIVER-005"\nreview_by = 2028-01-01\n'
        "max_lines = 1\n",
    )

    states, state_diagnostics = validate_architecture_state(
        tmp_path,
        policy(),
        today=date(2029, 1, 1),
    )
    waiver_diagnostics = apply_architecture_waivers(
        [Diagnostic("STRUCT003", source_path, "fixture")],
        states,
        today=date(2029, 1, 1),
    )

    assert any(item.rule == "WAIVER001" for item in state_diagnostics)
    assert any(item.rule == "STRUCT003" for item in waiver_diagnostics)


def test_current_repository_has_no_unwaived_architecture_errors() -> None:
    """The checked-in baseline remains fully routed, current, and enforceable."""
    errors = [
        diagnostic
        for diagnostic in validate_repository(repository_root())
        if diagnostic.severity == "error"
    ]

    assert errors == []
