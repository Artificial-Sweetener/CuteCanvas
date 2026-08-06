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

"""Prove exact, monotonic, platform-neutral test selection."""

from __future__ import annotations

import pytest

from tools.testing.changes import parse_name_only_z, parse_porcelain_z
from tools.testing.model import TestPolicy as _TestPolicy
from tools.testing.policy import load_policies, repository_root
from tools.testing.selection import SelectionError, select_changed_paths


@pytest.fixture(scope="module")
def policies() -> dict[str, _TestPolicy]:
    """Load the authoritative policies once for selector contract tests."""
    return load_policies(repository_root())


def test_qpane_rendering_change_selects_owner_and_consumer_contracts(
    policies: dict[str, _TestPolicy],
) -> None:
    """Fan out a public rendering change to CuteCanvas-owned subscriptions."""
    selection = select_changed_paths(
        ("packages/qpane/src/qpane/rendering/renderer.py",),
        policies,
    )
    groups = {(group.product, group.area, group.proof) for group in selection.groups}

    assert ("qpane", "rendering", "contract") in groups
    assert ("qpane", "rendering", "integration") in groups
    assert ("qpane", "rendering", "qt") in groups
    assert ("cutecanvas", "rendering", "contract") in groups
    assert ("cutecanvas", "rendering", "integration") in groups


def test_windows_and_posix_paths_select_identical_proof(
    policies: dict[str, _TestPolicy],
) -> None:
    """Normalize supported-platform separators before policy matching."""
    posix = select_changed_paths(
        ("packages/cutecanvas/src/cutecanvas/painting/engine.py",),
        policies,
    )
    windows = select_changed_paths(
        (r"packages\cutecanvas\src\cutecanvas\painting\engine.py",),
        policies,
    )
    assert windows.groups == posix.groups


def test_adding_changed_paths_only_expands_selection(
    policies: dict[str, _TestPolicy],
) -> None:
    """Keep selector results monotonic under a larger changed-path set."""
    first_path = "packages/cutecanvas/src/cutecanvas/selection/state.py"
    first = select_changed_paths((first_path,), policies)
    expanded = select_changed_paths(
        (first_path, "packages/qpane/src/qpane/cache/coordinator.py"),
        policies,
    )
    assert first.groups <= expanded.groups


def test_unknown_runtime_path_fails_with_corrective_action(
    policies: dict[str, _TestPolicy],
) -> None:
    """Never silently select zero tests for an unmapped runtime change."""
    with pytest.raises(SelectionError, match="Identify its product"):
        select_changed_paths(("new_runtime/owner.py",), policies)


def test_document_change_selects_focused_artifact_validation(
    policies: dict[str, _TestPolicy],
) -> None:
    """Keep documentation-only work out of full runtime suites."""
    selection = select_changed_paths(("docs/guide.md",), policies)
    assert selection.groups == frozenset()
    assert selection.validate_artifacts


def test_ferrastra_static_analysis_config_selects_architecture_proof(
    policies: dict[str, _TestPolicy],
) -> None:
    """Keep native static-analysis configuration inside enforced ownership."""
    selection = select_changed_paths(("pyright-ferrastraconfig.json",), policies)

    groups = {(group.product, group.area, group.proof) for group in selection.groups}
    assert ("repository", "architecture", "contract") in groups


def test_removed_root_architecture_state_selects_governance_proof(
    policies: dict[str, _TestPolicy],
) -> None:
    """Deleting or reintroducing root catch-all state never bypasses proof."""
    selection = select_changed_paths(("ARCHITECTURE_WAIVERS.toml",), policies)

    groups = {(group.product, group.area, group.proof) for group in selection.groups}
    assert ("repository", "architecture", "contract") in groups


def test_commit_selection_expands_each_affected_product_completely(
    policies: dict[str, _TestPolicy],
) -> None:
    """Turn one focused runtime impact into its product's complete commit gate."""
    selection = select_changed_paths(
        ("packages/qpane/src/qpane/cache/coordinator.py",),
        policies,
        commit=True,
    )

    assert selection.groups == policies["qpane"].groups()


def test_document_only_commit_remains_artifact_focused(
    policies: dict[str, _TestPolicy],
) -> None:
    """Do not turn documentation-only staged work into a runtime suite."""
    selection = select_changed_paths(("docs/guide.md",), policies, commit=True)

    assert selection.groups == frozenset()
    assert selection.validate_artifacts


def test_synthetic_git_diffs_preserve_all_changed_paths() -> None:
    """Parse staged and worktree NUL output without losing renamed origins."""
    assert parse_name_only_z("one.py\0two.rs\0") == ("one.py", "two.rs")
    assert parse_porcelain_z(" M one.py\0R  new.py\0old.py\0") == (
        "new.py",
        "old.py",
        "one.py",
    )
