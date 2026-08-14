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
"""Protect the fast transactional release workflow and trusted publisher."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from tools.release.orchestration import (
    PublicationError,
    PublicationRun,
    confirm_verified_orchestrator,
    dispatch_publication_waterfall,
)
from tools.testing.policy import repository_root

_RECOVERY = "abcdef0123456789abcdef0123456789"


class _ActionsGateway:
    """Provide deterministic GitHub Actions state to release-policy tests."""

    def __init__(
        self,
        outcomes: Mapping[str, str] | None = None,
        workflow_run: Mapping[str, Any] | None = None,
        workflow_jobs: Sequence[Mapping[str, Any]] = (),
        workflow_artifacts: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        """Create a fake gateway with publication and orchestrator outcomes."""
        self.dispatched: list[tuple[str, str, str]] = []
        self._outcomes = dict(outcomes or {})
        self._workflow_run = dict(workflow_run or {})
        self._workflow_jobs = tuple(workflow_jobs)
        self._workflow_artifacts = tuple(workflow_artifacts)

    def dispatch_publication(
        self,
        tag: str,
        orchestrator_run_id: str,
        recovery_id: str,
    ) -> None:
        """Record one publication dispatch."""
        self.dispatched.append((tag, orchestrator_run_id, recovery_id))

    def publication_runs(self, tag: str) -> tuple[PublicationRun, ...]:
        """Return a completed run only after its tag is dispatched."""
        match = next(
            (
                (index, recovery)
                for index, (candidate, _run, recovery) in enumerate(
                    self.dispatched, start=1
                )
                if candidate == tag
            ),
            None,
        )
        if match is None:
            return ()
        run_id, recovery = match
        return (
            PublicationRun(
                run_id=run_id,
                display_title=f"Publish {tag} from {recovery}",
                status="completed",
                conclusion=self._outcomes.get(tag, "success"),
                url=f"https://example.invalid/runs/{run_id}",
            ),
        )

    def workflow_run(self, run_id: int) -> Mapping[str, Any]:
        """Return configured orchestrator metadata."""
        return self._workflow_run

    def workflow_jobs(self, run_id: int) -> Sequence[Mapping[str, Any]]:
        """Return configured orchestrator jobs."""
        return self._workflow_jobs

    def workflow_artifacts(self, run_id: int) -> Sequence[Mapping[str, Any]]:
        """Return configured orchestrator artifacts."""
        return self._workflow_artifacts


def test_main_release_builds_and_seals_before_atomic_finalization() -> None:
    """Keep every irreversible Git or PyPI action behind whole-stack proof."""
    workflow = _workflow("release.yml")
    prepare = workflow.index("  prepare:")
    verify = workflow.index("  verify:")
    python_build = workflow.index("  build-python:")
    native_build = workflow.index("  build-ferrastra:")
    gate = workflow.index("  candidate-gate:")
    finalize = workflow.index("  finalize:")
    publish = workflow.index("  publish-waterfall:")
    assert prepare < verify < python_build < native_build < gate < finalize < publish
    assert "python -m tools.manage_release_plan seal" in workflow[gate:finalize]
    assert "python -m tools.verify_release_closure" in workflow[gate:finalize]
    assert "python -m tools.manage_release_plan finalize" in workflow[finalize:publish]
    assert "git push --atomic" not in workflow
    assert "uses: ./.github/workflows/version-product.yml" not in workflow
    assert "cascade_patch" not in workflow


def test_candidate_lineage_is_exact_and_reversible() -> None:
    """Build from one source SHA without exposing final tags before validation."""
    workflow = _workflow("release.yml")
    prepare = workflow[workflow.index("  prepare:") : workflow.index("  verify:")]
    assert "ref: main" in prepare
    assert '--source-sha "${{ github.sha }}"' in prepare
    assert "release-candidate/${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}" in prepare
    assert 'git push origin "HEAD:refs/heads/$candidate_ref"' in prepare
    assert "refs/tags/" not in prepare
    assert "cleanup-candidate:" in workflow
    assert "git/refs/heads/${{ needs.prepare.outputs.candidate_ref }}" in workflow


def test_candidate_artifacts_build_in_parallel_and_are_reused() -> None:
    """Avoid serial rebuilds while binding every publisher to sealed bytes."""
    release = _workflow("release.yml")
    publish = _workflow("publish.yml")
    assert "matrix:\n        product:" in release
    assert "matrix:\n        include:" in release
    assert "needs: prepare" in release
    assert (
        "release-${{ needs.prepare.outputs.plan_id }}-${{ matrix.product }}" in release
    )
    assert "actions/download-artifact@v7" in publish
    assert "run-id: ${{ env.ORCHESTRATOR_RUN_ID }}" in publish
    assert "python -m build" not in publish
    assert "maturin build" not in publish


def test_release_closure_is_one_clean_offline_transaction() -> None:
    """Reject sequential installs or dependency-resolution bypasses."""
    verifier = (repository_root() / "tools/release/closure.py").read_text("utf-8")
    assert "venv.EnvBuilder(with_pip=True)" in verifier
    assert '"--no-index"' in verifier
    assert '"--find-links"' in verifier
    assert '"--no-deps"' not in verifier
    assert verifier.count('"pip",\n        "install"') == 1


def test_candidate_gate_provisions_linux_qt_runtime_before_import_proof() -> None:
    """Keep the clean candidate import proof runnable on a minimal Linux host."""
    workflow = _workflow("release.yml")
    gate = workflow[workflow.index("  candidate-gate:") : workflow.index("  finalize:")]
    install_runtime = gate.index(
        "sudo apt-get install --yes --no-install-recommends libegl1"
    )
    verify_closure = gate.index("python -m tools.verify_release_closure")
    assert install_runtime < verify_closure


def test_every_release_tool_invocation_has_its_pinned_runtime() -> None:
    """Provision plan dependencies before every local release-tool invocation."""
    invocation_pattern = re.compile(
        r"python[^\n]*(?:from tools\.release|"
        r"-m tools\.(?:admit_release_publication|manage_release_plan|prepare_release|"
        r"release_publications|verify_release_closure)|"
        r"tools/generate_release_notes\.py)"
    )
    job_pattern = re.compile(r"^  [a-z][a-z0-9-]+:\s*$", re.MULTILINE)
    install_runtime_pattern = re.compile(
        r'python -m pip install[^\n]*"packaging==\$\{\{ env\.PACKAGING_VERSION \}\}"'
    )
    for workflow_name in ("release.yml", "publish.yml"):
        workflow = _workflow(workflow_name)
        job_starts = tuple(match.start() for match in job_pattern.finditer(workflow))
        invocations = tuple(invocation_pattern.finditer(workflow))
        assert invocations
        for invocation in invocations:
            job_start = max(start for start in job_starts if start < invocation.start())
            job_prefix = workflow[job_start : invocation.start()]
            assert install_runtime_pattern.search(job_prefix), (
                f"{workflow_name}:{workflow.count(chr(10), 0, invocation.start()) + 1} "
                "invokes release tooling before installing its pinned runtime"
            )


def test_every_verify_checkout_fetches_product_version_tags() -> None:
    """Keep editable SCM versions compatible after synchronized releases."""
    workflow = _workflow("verify.yml")
    checkout_count = workflow.count("uses: actions/checkout@v6")
    assert checkout_count > 0
    assert workflow.count("fetch-depth: 0") == checkout_count
    assert workflow.count("fetch-tags: true") == checkout_count


def test_publisher_has_no_tag_or_unplanned_direct_entry_point() -> None:
    """Require all automatic and manual recovery runs to name one sealed plan."""
    workflow = _workflow("publish.yml")
    triggers = workflow[workflow.index("on:") : workflow.index("permissions:")]
    assert "workflow_dispatch:" in triggers
    assert "push:" not in triggers
    assert "orchestrator_run_id:" in triggers
    assert "recovery_id:" in triggers
    assert triggers.count("required: true") == 3
    assert "sealed-plan-${{ env.RECOVERY_ID }}" in workflow
    assert '--recovery-id "$RECOVERY_ID"' in workflow
    assert '--release-tag "$RELEASE_TAG"' in workflow


def test_exact_state_admission_precedes_trusted_publication() -> None:
    """Permit skip-existing only after exact names and hashes are checked."""
    workflow = _workflow("publish.yml")
    admit = workflow.index("python -m tools.admit_release_publication")
    publish = workflow.index("pypa/gh-action-pypi-publish@release/v1")
    audit = workflow.index("  verify-published:")
    release = workflow.index("  release-product:")
    assert admit < publish < audit < release
    assert "skip-existing: true" in workflow[publish:audit]
    assert "PyPI state complete" in workflow[audit:release]
    assert "publication-receipt-${{ env.RECOVERY_ID }}" in workflow


def test_release_workflows_enforce_sub_hour_job_budgets() -> None:
    """Prevent accidental hour-long serial jobs in the release critical path."""
    for name in ("release.yml", "publish.yml", "verify.yml"):
        workflow = _workflow(name)
        timeouts = [
            int(value) for value in re.findall(r"timeout-minutes: (\d+)", workflow)
        ]
        assert timeouts
        assert max(timeouts) <= 30
    release = _workflow("release.yml")
    verify = _workflow("verify.yml")
    assert "timeout-minutes: 30" in release[release.index("  publish-waterfall:") :]
    assert "python tools/test.py ci" in verify


def test_verification_uses_exact_candidate_ref_and_versions() -> None:
    """Keep candidate wheel metadata exact without prematurely pushing tags."""
    workflow = _workflow("verify.yml")
    workflow_environment = workflow[workflow.index("env:") : workflow.index("jobs:")]
    assert "source_ref:" in workflow
    assert "ref: ${{ inputs.source_ref || github.sha }}" in workflow
    assert (
        "SETUPTOOLS_SCM_PRETEND_VERSION_FOR_QPANE: "
        "${{ inputs.qpane_version }}" in workflow_environment
    )
    assert (
        "SETUPTOOLS_SCM_PRETEND_VERSION_FOR_CUTECANVAS: "
        "${{ inputs.cutecanvas_version }}" in workflow_environment
    )
    assert workflow.count("SETUPTOOLS_SCM_PRETEND_VERSION_FOR_QPANE") == 1
    assert workflow.count("SETUPTOOLS_SCM_PRETEND_VERSION_FOR_CUTECANVAS") == 1
    assert "python -m tools.verify_python_wheels" in workflow
    assert "python tools/verify_python_wheels.py" not in workflow


def test_publication_waterfall_stops_on_first_failure() -> None:
    """Never publish downstream after an upstream publication failure."""
    gateway = _ActionsGateway(outcomes={"qpane-v3.0.2": "failure"})
    tags = ("ferrastra-v1.0.0", "qpane-v3.0.2", "cutecanvas-v1.0.3")
    with pytest.raises(PublicationError, match=r"qpane-v3\.0\.2 completed"):
        dispatch_publication_waterfall(
            gateway,
            tags,
            orchestrator_run_id="12345",
            recovery_id=_RECOVERY,
            pause=lambda _seconds: None,
        )
    assert gateway.dispatched == [
        ("ferrastra-v1.0.0", "12345", _RECOVERY),
        ("qpane-v3.0.2", "12345", _RECOVERY),
    ]


def test_recovery_requires_successful_finalization_and_owned_sealed_plan() -> None:
    """Accept completed failed waterfalls but reject foreign recovery identities."""
    run = {
        "path": ".github/workflows/release.yml",
        "status": "completed",
        "conclusion": "failure",
        "repository": {"full_name": "Artificial-Sweetener/CuteCanvas"},
    }
    jobs = (
        {"name": "Candidate gate", "conclusion": "success"},
        {"name": "Finalize release lineage", "conclusion": "success"},
    )
    artifacts = ({"name": f"sealed-plan-{_RECOVERY}", "expired": False},)
    gateway = _ActionsGateway(
        workflow_run=run,
        workflow_jobs=jobs,
        workflow_artifacts=artifacts,
    )
    confirm_verified_orchestrator(
        gateway,
        run_id=12345,
        repository="Artificial-Sweetener/CuteCanvas",
        recovery_id=_RECOVERY,
    )
    with pytest.raises(PublicationError, match="does not own active artifact"):
        confirm_verified_orchestrator(
            gateway,
            run_id=12345,
            repository="Artificial-Sweetener/CuteCanvas",
            recovery_id="0" * 32,
        )


def _workflow(name: str) -> str:
    """Read one authoritative GitHub workflow."""
    return (repository_root() / ".github/workflows" / name).read_text("utf-8")
