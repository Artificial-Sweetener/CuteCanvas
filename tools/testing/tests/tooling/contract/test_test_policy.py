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

"""Prove that current test-policy snapshots enforce physical ownership."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.testing.inventory import (
    InventoryError,
    validate_import_direction,
    validate_inventory,
    validate_root_runtime_ownership,
)
from tools.testing.model import TestArea as _TestArea
from tools.testing.model import TestPolicy as _TestPolicy
from tools.testing.policy import (
    PolicyError,
    load_policies,
    load_policy_file,
    path_matches_pattern,
    repository_root,
)


def test_repository_inventory_matches_every_product_policy() -> None:
    """Require complete source mapping and package-owned test placement."""
    root = repository_root()
    validate_inventory(root, load_policies(root))


def test_cutecanvas_rendering_abuse_is_case_isolated() -> None:
    """Keep native Qt lifetime storms out of shared xdist workers."""
    policy = load_policies(repository_root())["cutecanvas"]
    rendering = next(area for area in policy.areas if area.name == "rendering")
    assert "abuse" in rendering.case_isolated_proofs


def test_recursive_patterns_are_anchored_to_the_repository() -> None:
    """Keep similarly named nested directories from stealing ownership."""
    assert path_matches_pattern("tools/testing/cli.py", "tools/**")
    assert path_matches_pattern(
        "packages/cutecanvas/src/cutecanvas/painting/tools/brush.py",
        "packages/cutecanvas/src/cutecanvas/painting/**",
    )
    assert not path_matches_pattern(
        "packages/cutecanvas/src/cutecanvas/tools/brush.py",
        "tools/**",
    )


def test_policy_rejects_repeated_behavior_areas(tmp_path: Path) -> None:
    """Prove that an invalid policy cannot create ambiguous current facts."""
    policy_path = tmp_path / "TEST_POLICY.toml"
    policy_path.write_text(
        """
schema = 1
product = "invalid"
test_root = "tests"
platforms = ["windows-x64", "macos-arm64", "linux-x64"]
[[areas]]
name = "api"
sources = ["src/**"]
proofs = ["contract"]
[[areas]]
name = "api"
sources = ["other/**"]
proofs = ["integration"]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(PolicyError, match="area names must be unique"):
        load_policy_file(policy_path)


def test_policy_rejects_an_incomplete_platform_matrix(tmp_path: Path) -> None:
    """Prove every package policy retains the minimum supported targets."""
    policy_path = tmp_path / "TEST_POLICY.toml"
    policy_path.write_text(
        """
schema = 1
product = "invalid"
test_root = "tests"
platforms = ["windows-x64"]
[[areas]]
name = "api"
sources = ["src/**"]
proofs = ["contract"]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(PolicyError, match="omit required targets"):
        load_policy_file(policy_path)


def test_policy_rejects_case_isolation_for_an_unknown_proof(tmp_path: Path) -> None:
    """Strong process isolation must name a proof owned by the same area."""
    policy_path = tmp_path / "TEST_POLICY.toml"
    policy_path.write_text(
        """
schema = 1
product = "invalid"
test_root = "tests"
platforms = ["windows-x64", "macos-arm64", "linux-x64"]
[[areas]]
name = "api"
sources = ["src/**"]
proofs = ["contract"]
case_isolated_proofs = ["abuse"]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(PolicyError, match="isolates unknown proof kinds"):
        load_policy_file(policy_path)


@pytest.mark.parametrize("legacy_directory", ["tests", "examples"])
def test_root_runtime_ownership_rejects_python_artifacts(
    tmp_path: Path,
    legacy_directory: str,
) -> None:
    """Prove stale root tests, fixtures, and product examples cannot return."""
    directory = tmp_path / legacy_directory
    directory.mkdir()
    (directory / "runtime_fixture.py").write_text("value = 1\n", encoding="utf-8")

    with pytest.raises(InventoryError, match=r"repository-root|product examples"):
        validate_root_runtime_ownership(tmp_path)


@pytest.mark.parametrize(
    "generated_directory",
    ["examples/venv-core", "examples/__pycache__", "tests/.venv"],
)
def test_root_runtime_ownership_ignores_generated_python_environments(
    tmp_path: Path,
    generated_directory: str,
) -> None:
    """Keep ignored environments and caches outside the product-example inventory."""
    directory = tmp_path / generated_directory
    directory.mkdir(parents=True)
    (directory / "generated.py").write_text("value = 1\n", encoding="utf-8")

    validate_root_runtime_ownership(tmp_path)


def test_import_checker_rejects_downstream_test_dependency(tmp_path: Path) -> None:
    """Prove QPane test support cannot acquire a CuteCanvas dependency."""
    qpane_root = tmp_path / "qpane-tests"
    qpane_root.mkdir()
    (qpane_root / "fixture.py").write_text(
        "from cutecanvas import CuteCanvas\n",
        encoding="utf-8",
    )
    ferrastra_root = tmp_path / "ferrastra-tests"
    ferrastra_root.mkdir()
    policies = {
        "qpane": _minimal_policy("qpane", qpane_root, tmp_path),
        "ferrastra": _minimal_policy("ferrastra", ferrastra_root, tmp_path),
    }

    with pytest.raises(InventoryError, match="forbidden downstream owners"):
        validate_import_direction(tmp_path, policies)


def _minimal_policy(product: str, test_root: Path, root: Path) -> _TestPolicy:
    """Return a compact policy value for one deliberately invalid fixture."""
    return _TestPolicy(
        product=product,
        path=root / f"{product}.toml",
        test_root=test_root.relative_to(root).as_posix(),
        platforms=("windows-x64",),
        areas=(_TestArea("api", (f"{product}/**",), ("contract",)),),
        boundaries=(),
        subscriptions=(),
    )
