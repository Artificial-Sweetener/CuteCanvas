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
"""Prove exact-plan publication order and idempotent partial recovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.release import publication
from tools.release.plan import (
    PlannedArtifact,
    ReleasePlan,
    ReleasePlanError,
    create_release_plan,
)
from tools.release.pypi import PublicationState, planned_publication_state


def test_pypi_partial_state_resumes_only_matching_planned_files() -> None:
    """Recognize exact partial uploads without accepting altered bytes."""
    expected = {"one.whl": "a" * 64, "source.tar.gz": "b" * 64}

    def partial(_url: str) -> dict[str, object]:
        """Expose one exact uploaded file from a two-file release."""
        return {"urls": [_file("one.whl", "a" * 64)]}

    assert (
        planned_publication_state("qpane", "3.0.2", expected, loader=partial)
        is PublicationState.PARTIAL
    )

    def altered(_url: str) -> dict[str, object]:
        """Expose a same-name file whose immutable bytes differ."""
        return {"urls": [_file("one.whl", "c" * 64)]}

    with pytest.raises(RuntimeError, match="hashes disagree"):
        planned_publication_state("qpane", "3.0.2", expected, loader=altered)


def test_downstream_admission_requires_complete_planned_upstream(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Refuse out-of-order publication even when downstream bytes are valid."""
    plan = _sealed_plan()
    monkeypatch.setattr(publication, "verify_release_artifacts", _accept_artifacts)

    def loader(url: str) -> dict[str, object]:
        """Expose Ferrastra but leave the planned QPane release partial."""
        if "/ferrastra/1.0.0/" in url:
            return {"urls": [_file("ferrastra.whl", "f" * 64)]}
        if "/qpane/3.0.2/" in url:
            return {"urls": [_file("qpane-3.0.2.whl", "d" * 64)]}
        return {"urls": []}

    with pytest.raises(ReleasePlanError, match="before planned upstream qpane"):
        publication.admit_publication(
            plan,
            "cutecanvas",
            tmp_path,
            "c" * 40,
            loader=loader,
        )


def test_publication_recovery_rejects_a_different_tag_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Bind manual recovery to the same candidate lineage as the release plan."""
    monkeypatch.setattr(publication, "verify_release_artifacts", _accept_artifacts)
    with pytest.raises(ReleasePlanError, match="tag resolves"):
        publication.admit_publication(
            _sealed_plan(),
            "qpane",
            tmp_path,
            "9" * 40,
            loader=lambda _url: {"urls": []},
        )


def _accept_artifacts(
    plan: ReleasePlan,
    distribution_root: Path,
    product_name: str | None = None,
) -> None:
    """Stand in for artifact verification after preserving its typed contract."""
    del plan, distribution_root, product_name


def _sealed_plan() -> ReleasePlan:
    """Return a two-product plan with deterministic candidate hashes."""
    plan = create_release_plan(
        "a" * 40,
        {
            "ferrastra": (1, 0, 0),
            "qpane": (3, 0, 1),
            "cutecanvas": (1, 0, 2),
        },
        {"ferrastra": None, "qpane": (3, 0, 2), "cutecanvas": None},
        {
            "qpane": {"ferrastra": ">=1.0.0,<2.0.0"},
            "cutecanvas": {
                "ferrastra": ">=1.0.0,<2.0.0",
                "qpane": ">=3.0.0,<4.0.0",
            },
        },
    ).with_candidate(
        "c" * 40,
        {"qpane": "b" * 40, "cutecanvas": "c" * 40},
    )
    return plan.with_artifacts(
        (
            PlannedArtifact("qpane", "qpane-3.0.2.whl", "d" * 64),
            PlannedArtifact("qpane", "qpane-3.0.2.tar.gz", "e" * 64),
            PlannedArtifact("cutecanvas", "cutecanvas-1.0.3.whl", "1" * 64),
            PlannedArtifact("cutecanvas", "cutecanvas-1.0.3.tar.gz", "2" * 64),
        )
    )


def _file(filename: str, sha256: str) -> dict[str, object]:
    """Return one PyPI JSON file record."""
    return {"filename": filename, "digests": {"sha256": sha256}}
