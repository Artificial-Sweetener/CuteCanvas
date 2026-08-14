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
"""Protect automatic independent product releases from the main branch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from tools.release.orchestration import (
    PublicationError,
    PublicationRun,
    confirm_verified_orchestrator,
    dispatch_publication_waterfall,
    release_tags_from_environment,
)
from tools.testing.policy import repository_root


class _ActionsGateway:
    """Provide deterministic GitHub Actions state to release-policy tests."""

    def __init__(
        self,
        outcomes: Mapping[str, str] | None = None,
        workflow_run: Mapping[str, Any] | None = None,
        workflow_jobs: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        """Create a fake gateway with publication and orchestrator outcomes."""
        self.dispatched: list[tuple[str, str]] = []
        self._outcomes = dict(outcomes or {})
        self._workflow_run = dict(workflow_run or {})
        self._workflow_jobs = tuple(workflow_jobs)

    def dispatch_publication(self, tag: str, orchestrator_run_id: str) -> None:
        """Record one publication dispatch."""
        self.dispatched.append((tag, orchestrator_run_id))

    def publication_runs(self, tag: str) -> tuple[PublicationRun, ...]:
        """Return a completed run only after its tag is dispatched."""
        dispatch_index = next(
            (
                index
                for index, (candidate, _run_id) in enumerate(self.dispatched, start=1)
                if candidate == tag
            ),
            None,
        )
        if dispatch_index is None:
            return ()
        orchestrator_run_id = next(
            run_id for candidate, run_id in self.dispatched if candidate == tag
        )
        conclusion = self._outcomes.get(tag, "success")
        return (
            PublicationRun(
                run_id=dispatch_index,
                display_title=f"Publish {tag} from release {orchestrator_run_id}",
                status="completed",
                conclusion=conclusion,
                url=f"https://example.invalid/runs/{dispatch_index}",
            ),
        )

    def workflow_run(self, run_id: int) -> Mapping[str, Any]:
        """Return configured orchestrator metadata."""
        return self._workflow_run

    def workflow_jobs(self, run_id: int) -> Sequence[Mapping[str, Any]]:
        """Return configured orchestrator jobs."""
        return self._workflow_jobs


def test_main_push_versions_the_complete_waterfall_before_publication() -> None:
    """Version every downstream product before publishing the first artifact."""
    workflow = (repository_root() / ".github/workflows/release.yml").read_text("utf-8")
    assert "branches: [main]" in workflow
    assert "uses: ./.github/workflows/verify.yml" in workflow

    ferrastra = workflow.index("  version-ferrastra:")
    qpane = workflow.index("  version-qpane:")
    cutecanvas = workflow.index("  version-cutecanvas:")
    publisher = workflow.index("  publish-waterfall:")
    assert ferrastra < qpane < cutecanvas < publisher
    assert workflow.count("uses: ./.github/workflows/version-product.yml") == 3
    assert "uses: ./.github/workflows/publish.yml" not in workflow
    assert "python tools/release_publications.py dispatch" in workflow[publisher:]
    assert 'legacy_anchor: "v2.1.1"' in workflow
    assert 'first_bump: "minor"' not in workflow
    assert workflow.count('first_bump: "major"') == 3


def test_release_admits_ferrastras_stable_initial_publication() -> None:
    """Publish Ferrastra 1.0.0 through the verified product waterfall."""
    release = (repository_root() / ".github/workflows/release.yml").read_text("utf-8")
    ferrastra = release[
        release.index("  version-ferrastra:") : release.index("  version-qpane:")
    ]
    qpane = release[
        release.index("  version-qpane:") : release.index("  version-cutecanvas:")
    ]
    cutecanvas = release[
        release.index("  version-cutecanvas:") : release.index("  publish-waterfall:")
    ]
    version = (repository_root() / ".github/workflows/version-product.yml").read_text(
        "utf-8"
    )

    assert "release_initial: true" in ferrastra
    assert "release_initial: true" in qpane
    assert "release_initial: true" in cutecanvas
    assert "release_initial:" in version
    assert "if: steps.lineage.outputs.enabled == 'true'" in version


def test_upstream_releases_force_downstream_patch_waterfalls() -> None:
    """Cascade Ferrastra through QPane and every QPane release through CuteCanvas."""
    workflow = (repository_root() / ".github/workflows/release.yml").read_text("utf-8")
    qpane = workflow[workflow.index("  version-qpane:") :]
    cutecanvas = workflow[workflow.index("  version-cutecanvas:") :]
    assert "cascade_patch:" in qpane
    assert "needs.version-ferrastra.outputs.released == 'true'" in qpane
    assert "cascade_patch:" in cutecanvas
    assert "needs.version-qpane.outputs.released == 'true'" in cutecanvas


def test_waterfall_versions_only_the_verified_release_lineage() -> None:
    """Pass each release commit to the next product instead of rereading moving main."""
    workflow = (repository_root() / ".github/workflows/release.yml").read_text("utf-8")
    assert "expected_head: ${{ github.sha }}" in workflow
    assert "expected_head: ${{ needs.version-ferrastra.outputs.head_sha }}" in workflow
    assert "expected_head: ${{ needs.version-qpane.outputs.head_sha }}" in workflow


def test_version_workflow_uses_python_semantic_release_to_push_product_tags() -> None:
    """Keep semantic version calculation, release commits, and tags in PSR."""
    workflow = (repository_root() / ".github/workflows/version-product.yml").read_text(
        "utf-8"
    )
    assert 'PYTHON_SEMANTIC_RELEASE_VERSION: "10.6.1"' in workflow
    assert "working-directory: packages/${{ inputs.product }}" in workflow
    assert "python -m semantic_release -v version" in workflow
    assert "--no-vcs-release" in workflow
    assert 'remote_tags="$(git ls-remote --tags origin' in workflow
    assert "released=" in workflow
    assert "release_tag=" in workflow
    assert "EXPECTED_HEAD" in workflow
    assert 'test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"' in workflow
    assert "head_sha=" in workflow


def test_cascade_patch_never_downgrades_a_larger_product_release() -> None:
    """Force a patch only when semantic-release finds no direct product release."""
    workflow = (repository_root() / ".github/workflows/version-product.yml").read_text(
        "utf-8"
    )
    assert "cascade_patch:" in workflow
    assert "DIRECT_VERSION" in workflow
    assert "LAST_RELEASED_VERSION" in workflow
    assert 'if [ "$DIRECT_VERSION" = "$LAST_RELEASED_VERSION" ]' in workflow
    assert 'arguments+=("--patch")' in workflow


def test_release_verification_installs_the_exact_workspace_python_stack() -> None:
    """Prove CuteCanvas against the QPane wheel from the release source tree."""
    workflow = (repository_root() / ".github/workflows/verify.yml").read_text("utf-8")
    wheel_job = workflow.index("  python-wheels:")
    gate = workflow.index("  gate:")
    assert wheel_job < gate
    assert "python tools/verify_python_wheels.py" in workflow[wheel_job:gate]
    assert "- python-wheels" in workflow[gate:]
    assert "PYTHON_WHEELS_RESULT" in workflow[gate:]


def test_publish_workflow_validates_before_trusted_publication() -> None:
    """Require tag, index, artifact, and Markdown proof before PyPI upload."""
    workflow = (repository_root() / ".github/workflows/publish.yml").read_text("utf-8")
    admission = workflow.index("python tools/check_python_release.py")
    build = workflow.index(
        'python -m build "packages/${{ needs.select.outputs.package }}"'
    )
    artifact = workflow.index("python -m tools.verify_python_release_artifacts")
    publish = workflow.index("pypa/gh-action-pypi-publish@release/v1")
    assert admission < build < artifact < publish
    assert '"readme-renderer[md]==${{ env.README_RENDERER_VERSION }}"' in workflow
    assert "python -m twine check --strict" in workflow
    assert "  validate-distribution:" in workflow
    assert "needs.validate-distribution.result == 'success'" in workflow
    assert (
        'python -m tools.check_ferrastra_release_tag "${{ env.RELEASE_TAG }}" '
        "--check-pypi"
    ) in workflow
    assert "skip-existing: false" in workflow


def test_waterfall_dispatches_the_trusted_publisher_as_a_top_level_workflow() -> None:
    """Keep PyPI attestations bound to publish.yml for automatic releases."""
    release = (repository_root() / ".github/workflows/release.yml").read_text("utf-8")
    publish = (repository_root() / ".github/workflows/publish.yml").read_text("utf-8")

    assert "actions: write" in release
    assert "uses: ./.github/workflows/publish.yml" not in release
    assert "python tools/release_publications.py dispatch" in release
    assert "workflow_call:" not in publish
    assert "workflow_dispatch:" in publish
    assert "orchestrator_run_id:" in publish
    assert "from release ${{ inputs.orchestrator_run_id || 'direct' }}" in publish
    assert "RELEASE_TAG: ${{ inputs.release_tag || github.ref_name }}" in publish
    assert "ref: ${{ env.RELEASE_TAG }}" in publish
    assert "tags:" in publish


def test_orchestrated_publish_requires_active_release_gate() -> None:
    """Reject caller claims that are not backed by the running release gate."""
    workflow = (repository_root() / ".github/workflows/publish.yml").read_text("utf-8")
    assert "if: inputs.orchestrator_run_id == ''" in workflow
    assert "if: inputs.orchestrator_run_id != ''" in workflow
    assert "python tools/release_publications.py verify" in workflow
    assert "actions: read" in workflow


def test_release_plan_preserves_dependency_order_and_product_identity() -> None:
    """Translate version outputs into the exact Ferrastra-to-CuteCanvas waterfall."""
    environment = {
        "FERRASTRA_RELEASED": "true",
        "FERRASTRA_RELEASE_TAG": "ferrastra-v1.0.0",
        "QPANE_RELEASED": "true",
        "QPANE_RELEASE_TAG": "qpane-v3.0.1",
        "CUTECANVAS_RELEASED": "true",
        "CUTECANVAS_RELEASE_TAG": "cutecanvas-v1.0.2",
    }
    assert release_tags_from_environment(environment) == (
        "ferrastra-v1.0.0",
        "qpane-v3.0.1",
        "cutecanvas-v1.0.2",
    )

    environment["QPANE_RELEASE_TAG"] = "cutecanvas-v1.0.2"
    with pytest.raises(PublicationError, match="selected cutecanvas, expected qpane"):
        release_tags_from_environment(environment)


def test_publication_waterfall_waits_and_stops_on_the_first_failure() -> None:
    """Never publish a downstream product after an upstream publication fails."""
    gateway = _ActionsGateway(outcomes={"qpane-v3.0.1": "failure"})
    tags = ("ferrastra-v1.0.0", "qpane-v3.0.1", "cutecanvas-v1.0.2")

    with pytest.raises(
        PublicationError,
        match=r"qpane-v3\.0\.1 completed with 'failure'",
    ):
        dispatch_publication_waterfall(
            gateway,
            tags,
            orchestrator_run_id="12345",
            pause=lambda _seconds: None,
        )

    assert gateway.dispatched == [
        ("ferrastra-v1.0.0", "12345"),
        ("qpane-v3.0.1", "12345"),
    ]


def test_verified_orchestrator_must_be_this_active_release_run() -> None:
    """Admit duplicate-verification bypass only for a successful release gate."""
    run = {
        "path": ".github/workflows/release.yml",
        "status": "in_progress",
        "repository": {"full_name": "Artificial-Sweetener/CuteCanvas"},
    }
    jobs = ({"name": "verify / Gate", "status": "completed", "conclusion": "success"},)
    gateway = _ActionsGateway(workflow_run=run, workflow_jobs=jobs)
    confirm_verified_orchestrator(
        gateway,
        run_id=12345,
        repository="Artificial-Sweetener/CuteCanvas",
    )

    run["status"] = "completed"
    with pytest.raises(PublicationError, match="must be in_progress"):
        confirm_verified_orchestrator(
            _ActionsGateway(workflow_run=run, workflow_jobs=jobs),
            run_id=12345,
            repository="Artificial-Sweetener/CuteCanvas",
        )


def test_publish_builds_survive_the_intentionally_skipped_verification_job() -> None:
    """Let verified waterfall calls build after their local verify job is skipped."""
    workflow = (repository_root() / ".github/workflows/publish.yml").read_text("utf-8")
    python_build = workflow[
        workflow.index("  build-python:") : workflow.index("  build-ferrastra:")
    ]
    ferrastra_build = workflow[
        workflow.index("  build-ferrastra:") : workflow.index("  publish:")
    ]
    for build in (python_build, ferrastra_build):
        assert "always()" in build
        assert "needs.select.result == 'success'" in build


def test_publish_workflow_creates_package_scoped_release_notes_after_pypi() -> None:
    """Create one product release only after its immutable upload succeeds."""
    workflow = (repository_root() / ".github/workflows/publish.yml").read_text("utf-8")
    release_job = workflow.index("  release-product:")
    assert workflow.index("      - publish", release_job) > release_job
    assert "always()" in workflow[release_job:]
    assert "needs.publish.result == 'success'" in workflow[release_job:]
    assert "python tools/generate_release_notes.py" in workflow[release_job:]
    assert 'gh release create "$RELEASE_TAG" --verify-tag' in workflow
    assert "needs.select.outputs.package != 'ferrastra'" not in workflow[release_job:]
