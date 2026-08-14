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
"""Protect repository dependency and supply-chain automation."""

from __future__ import annotations

import re

from tools.testing.policy import repository_root

_ROOT = repository_root()
_EXTERNAL_ACTION = re.compile(r"uses:\s+(?!\./)([^\s@]+)@([^\s#]+)")
_FULL_COMMIT_SHA = re.compile(r"[0-9a-f]{40}")


def test_dependabot_covers_every_owned_dependency_ecosystem() -> None:
    """Update every Python manifest, Cargo workspace, toolchain, and Action."""
    configuration = (_ROOT / ".github/dependabot.yml").read_text("utf-8")
    assert configuration.count("package-ecosystem: pip") == 4
    for directory in (
        "/",
        "/packages/ferrastra",
        "/packages/qpane",
        "/packages/cutecanvas",
    ):
        assert f'directory: "{directory}"' in configuration
    assert "package-ecosystem: cargo" in configuration
    assert "package-ecosystem: github-actions" in configuration
    assert configuration.count("interval: weekly") == 6


def test_ci_runs_weekly_security_and_dependency_proof() -> None:
    """Detect newly disclosed vulnerabilities and upstream drift without a PR."""
    ci_workflow = _workflow("ci.yml")
    verify_workflow = _workflow("verify.yml")
    assert "schedule:" in ci_workflow
    assert "cron:" in ci_workflow
    assert "python-audit:" in verify_workflow
    assert "python -m pip_audit --local" in verify_workflow
    assert "actions/dependency-review-action@" in verify_workflow
    gate = verify_workflow[verify_workflow.index("  gate:") :]
    assert "python-audit" in gate
    assert "dependency-review" in gate
    assert '"success"' in gate and '"skipped"' in gate


def test_every_external_action_is_pinned_to_a_full_commit() -> None:
    """Prevent mutable tags from changing trusted workflow code."""
    references: list[tuple[str, str, str]] = []
    for workflow in sorted((_ROOT / ".github/workflows").glob("*.yml")):
        for action, revision in _EXTERNAL_ACTION.findall(workflow.read_text("utf-8")):
            references.append((workflow.name, action, revision))
            assert _FULL_COMMIT_SHA.fullmatch(
                revision
            ), f"{workflow.name} uses mutable {action}@{revision}"
    assert references


def test_release_credentials_are_scoped_to_the_jobs_that_use_them() -> None:
    """Keep write and OIDC authority out of build and admission jobs."""
    release = _workflow("release.yml")
    publish = _workflow("publish.yml")
    release_defaults = release[
        release.index("permissions:") : release.index("concurrency:")
    ]
    publish_defaults = publish[publish.index("permissions:") : publish.index("env:")]
    assert "contents: read" in release_defaults
    assert "contents: write" not in release_defaults
    assert "actions: write" not in release_defaults
    assert "contents: read" in publish_defaults
    assert "contents: write" not in publish_defaults
    assert "id-token: write" not in publish_defaults

    verification_job = release[
        release.index("  verify:") : release.index("  build-python:")
    ]
    assert "contents: read" in verification_job
    assert "pull-requests: read" in verification_job

    finalize_job = release[
        release.index("  finalize:") : release.index("  publish-waterfall:")
    ]
    assert "contents: write" in finalize_job
    assert "statuses: write" in finalize_job
    assert "statuses/${{ needs.prepare.outputs.candidate_sha }}" in finalize_job

    publication_job = publish[
        publish.index("  publish:") : publish.index("  verify-published:")
    ]
    assert "id-token: write" in publication_job
    assert "contents: write" not in publication_job


def test_security_policy_uses_private_vulnerability_reporting() -> None:
    """Route vulnerability disclosure away from public issue traffic."""
    policy = (_ROOT / "SECURITY.md").read_text("utf-8")
    assert "security/advisories/new" in policy
    assert "Do not open a public issue" in policy


def _workflow(name: str) -> str:
    """Read one authoritative GitHub workflow."""
    return (_ROOT / ".github/workflows" / name).read_text("utf-8")
