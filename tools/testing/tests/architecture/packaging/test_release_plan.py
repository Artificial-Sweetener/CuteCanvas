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
"""Prove release planning, dependency policy, and immutable identity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from tools.release.candidate import synchronize_requirements
from tools.release.compatibility import (
    STABLE_MAJOR_PRERELEASE_MINOR,
    CompatibilityPolicy,
    UpperBoundPolicy,
)
from tools.release.plan import (
    PlannedDependency,
    ReleasePlan,
    ReleasePlanError,
    create_release_plan,
    load_release_plan,
    save_release_plan,
)

_SHA = "a" * 40
_CURRENT = {
    "ferrastra": (1, 2, 3),
    "qpane": (3, 4, 5),
    "cutecanvas": (1, 6, 7),
}
_REQUIREMENTS = {
    "qpane": {"ferrastra": ">=1.0.0,<2.0.0"},
    "cutecanvas": {
        "ferrastra": ">=1.0.0,<2.0.0",
        "qpane": ">=3.0.0,<4.0.0",
    },
}


@pytest.mark.parametrize("next_version", [(1, 2, 4), (1, 3, 0), (2, 0, 0)])
def test_ferrastra_release_replans_every_transitive_consumer(
    next_version: tuple[int, int, int],
) -> None:
    """Propagate every semantic bump through QPane and CuteCanvas metadata."""
    plan = _plan(ferrastra=next_version)
    assert [product.name for product in plan.products] == [
        "ferrastra",
        "qpane",
        "cutecanvas",
    ]
    qpane = plan.product("qpane")
    canvas = plan.product("cutecanvas")
    assert qpane.version == (3, 4, 6)
    assert canvas.version == (1, 6, 8)
    assert qpane.dependencies[0].version == next_version
    assert canvas.dependencies[0].version == next_version
    assert Version(".".join(map(str, next_version))) in SpecifierSet(
        qpane.dependencies[0].specifier
    )


@pytest.mark.parametrize("next_version", [(3, 4, 6), (3, 5, 0), (4, 0, 0)])
def test_qpane_release_replans_cutecanvas(
    next_version: tuple[int, int, int],
) -> None:
    """Propagate each QPane bump while leaving Ferrastra unpublished."""
    plan = _plan(qpane=next_version)
    assert [product.name for product in plan.products] == ["qpane", "cutecanvas"]
    dependency = plan.product("cutecanvas").dependencies[1]
    assert dependency.version == next_version
    assert dependency.specifier.startswith(f">={'.'.join(map(str, next_version))},")


def test_simultaneous_direct_releases_preserve_the_larger_versions() -> None:
    """Never downgrade a direct semantic release to a propagated patch."""
    plan = _plan(ferrastra=(2, 0, 0), qpane=(4, 0, 0), cutecanvas=(2, 0, 0))
    assert [product.version for product in plan.products] == [
        (2, 0, 0),
        (4, 0, 0),
        (2, 0, 0),
    ]
    assert all(product.direct for product in plan.products)


def test_downstream_only_release_retains_valid_upstream_ranges() -> None:
    """Avoid needless constraint churn when exact current releases remain admitted."""
    plan = _plan(cutecanvas=(1, 6, 8))
    dependencies = plan.product("cutecanvas").dependencies
    assert [item.specifier for item in dependencies] == [
        ">=1.0.0,<2.0.0",
        ">=3.0.0,<4.0.0",
    ]


def test_current_broken_ranges_are_replaced_from_exact_upstream_versions() -> None:
    """Make the published Ferrastra incompatibility impossible in a new plan."""
    requirements = {
        "qpane": {"ferrastra": ">=0.1.0,<0.2"},
        "cutecanvas": {
            "ferrastra": ">=0.1.0,<1.0.0",
            "qpane": ">=3.0.0,<4.0.0",
        },
    }
    plan = _plan(qpane=(3, 4, 6), cutecanvas=(1, 6, 8), requirements=requirements)
    assert plan.product("qpane").dependencies[0].specifier == ">=1.2.3,<2.0.0"
    assert plan.product("cutecanvas").dependencies[0].specifier == ">=1.2.3,<2.0.0"


def test_compatibility_policy_has_distinct_stable_and_pre_one_boundaries() -> None:
    """Prove edge policy is explicit rather than a hard-coded next-major rule."""
    assert STABLE_MAJOR_PRERELEASE_MINOR.specifier((1, 4, 2)) == ">=1.4.2,<2.0.0"
    assert STABLE_MAJOR_PRERELEASE_MINOR.specifier((0, 4, 2)) == ">=0.4.2,<0.5.0"
    narrow = CompatibilityPolicy(
        stable_upper_bound=UpperBoundPolicy.NEXT_MINOR,
        zero_upper_bound=UpperBoundPolicy.NEXT_MINOR,
    )
    assert narrow.specifier((3, 8, 1)) == ">=3.8.1,<3.9.0"


def test_release_closure_is_monotonic() -> None:
    """Adding a changed product can never remove required downstream releases."""
    qpane_only = {product.name for product in _plan(qpane=(3, 4, 6)).products}
    combined = {
        product.name for product in _plan(ferrastra=(1, 3, 0), qpane=(3, 4, 6)).products
    }
    assert qpane_only <= combined


@pytest.mark.parametrize("proposal", [(1, 2, 3), (1, 2, 2), (0, 9, 9)])
def test_direct_release_must_advance_the_published_version(
    proposal: tuple[int, int, int],
) -> None:
    """Reject equal or regressive semantic proposals before mutation."""
    with pytest.raises(ReleasePlanError, match="must advance"):
        _plan(ferrastra=proposal)


def test_release_inputs_must_cover_the_known_product_graph_exactly() -> None:
    """Fail closed when product discovery and planning inputs drift apart."""
    with pytest.raises(ReleasePlanError, match="exactly every product"):
        create_release_plan(
            _SHA,
            _CURRENT,
            {"ferrastra": None, "qpane": None},
            _REQUIREMENTS,
        )


def test_serialized_plan_rejects_identity_tampering(tmp_path: Path) -> None:
    """Bind recovery to the exact source, versions, and dependency decisions."""
    path = tmp_path / "release-plan.json"
    save_release_plan(_plan(qpane=(3, 4, 6)), path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["products"][0]["version"] = "9.9.9"
    payload["products"][0]["tag"] = "qpane-v9.9.9"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReleasePlanError, match="identity"):
        load_release_plan(path)


def test_manifest_materialization_requires_one_plain_dependency(tmp_path: Path) -> None:
    """Reject duplicate, marked, or otherwise ambiguous dependency ownership."""
    manifest = tmp_path / "pyproject.toml"
    manifest.write_text(
        '[project]\ndependencies = [\n  "ferrastra>=0.1",\n'
        "  \"ferrastra>=0.2; python_version > '3.10'\",\n]\n",
        encoding="utf-8",
    )
    dependency = PlannedDependency("ferrastra", (1, 0, 0), ">=1.0.0,<2.0.0")
    with pytest.raises(ReleasePlanError, match="plain version range"):
        synchronize_requirements(manifest, (dependency,))


def _plan(
    *,
    ferrastra: tuple[int, int, int] | None = None,
    qpane: tuple[int, int, int] | None = None,
    cutecanvas: tuple[int, int, int] | None = None,
    requirements: dict[str, dict[str, str]] | None = None,
) -> ReleasePlan:
    """Build a deterministic plan fixture from direct semantic proposals."""
    return create_release_plan(
        _SHA,
        _CURRENT,
        {"ferrastra": ferrastra, "qpane": qpane, "cutecanvas": cutecanvas},
        _REQUIREMENTS if requirements is None else requirements,
    )
